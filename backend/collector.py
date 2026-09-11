import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.models import Incident

logger = logging.getLogger(__name__)

PRIM_BASE_URL = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia/line_reports"

# Mapping Navitia line ID → internal line_id
LIGNES_CIBLES: dict[str, str] = {
    "line:IDFM:C01742": "RER_A",
    "line:IDFM:C01743": "RER_B",
    "line:IDFM:C01727": "RER_C",
    "line:IDFM:C01728": "RER_D",
    "line:IDFM:C01729": "RER_E",
    "line:IDFM:C01737": "TRANSILIEN_H",
    "line:IDFM:C01730": "TRANSILIEN_J",
    "line:IDFM:C01731": "TRANSILIEN_K",
    "line:IDFM:C02142": "TRANSILIEN_L",
    "line:IDFM:C02629": "TRANSILIEN_N",
    "line:IDFM:C02152": "TRANSILIEN_P",
    "line:IDFM:C01735": "TRANSILIEN_R",
    "line:IDFM:C01736": "TRANSILIEN_U",
}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # PRIM returns ISO 8601 e.g. "20240101T063000"
        dt = datetime.strptime(value, "%Y%m%dT%H%M%S")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _extract_line_id(impacted_objects: list) -> str | None:
    for obj in impacted_objects:
        pt = obj.get("pt_object", {})
        if pt.get("embedded_type") == "line":
            line_id = pt.get("id", "")
            if line_id in LIGNES_CIBLES:
                return LIGNES_CIBLES[line_id]
    return None


async def collect_disruptions() -> None:
    settings = get_settings()
    if not settings.prim_api_key:
        logger.warning("PRIM_API_KEY not set — skipping collection")
        return

    headers = {"apikey": settings.prim_api_key}
    params = {"count": 100, "start_page": 0, "disable_geojson": "true"}

    all_disruptions: list[tuple[str, dict]] = []  # (line_id_interne, disruption)

    async with httpx.AsyncClient(timeout=30) as client:
        for navitia_id, line_id in LIGNES_CIBLES.items():
            url = f"{PRIM_BASE_URL}/lines/{navitia_id}/line_reports"
            try:
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                for d in data.get("disruptions", []):
                    if d.get("status") in ("active", "future"):
                        all_disruptions.append((line_id, d))
            except httpx.HTTPError as exc:
                logger.error("PRIM API error for %s: %s", line_id, exc)
            except Exception as exc:
                logger.error("Unexpected error for %s: %s", line_id, exc)

    logger.info("Fetched %d disruptions from PRIM", len(all_disruptions))

    inserted = 0
    async with AsyncSessionLocal() as session:
        for line_id, d in all_disruptions:

            periods = d.get("application_periods", [])
            heure_debut = _parse_dt(periods[0].get("begin") if periods else None)
            heure_fin = _parse_dt(periods[0].get("end") if periods else None)
            if heure_debut is None:
                continue

            messages = d.get("messages", [])
            cause = messages[0].get("text") if messages else None

            type_incident = d.get("severity", {}).get("effect", "UNKNOWN")
            navitia_id = d.get("id", "")
            if not navitia_id:
                continue

            now = datetime.now(timezone.utc)

            # Ignorer les incidents pas encore commencés
            if heure_debut > now:
                continue

            # Ignorer les incidents de nuit (00h-07h heure Paris)
            paris_hour = heure_debut.astimezone(ZoneInfo("Europe/Paris")).hour
            if paris_hour < 7:
                continue

            duree_minutes = None
            if heure_debut and heure_fin and heure_fin > heure_debut:
                duree_minutes = int((heure_fin - heure_debut).total_seconds() / 60)
                if duree_minutes > 720:  # > 12h = modification de service planifiée, pas un retard
                    continue
            stmt = (
                insert(Incident)
                .values(
                    navitia_id=navitia_id,
                    line_id=line_id,
                    type_incident=type_incident,
                    cause=cause,
                    heure_debut=heure_debut,
                    heure_fin=heure_fin,
                    duree_minutes=duree_minutes,
                    source="disruption",
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["navitia_id"],
                    set_={
                        "heure_fin": heure_fin,
                        "duree_minutes": duree_minutes,
                        "source": "disruption",
                        "updated_at": now,
                    },
                )
            )
            await session.execute(stmt)
            inserted += 1

        await session.commit()

    logger.info("Upserted %d incidents for tracked lines", inserted)


PRIM_NAVITIA_BASE = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia"
MIN_DELAY_MINUTES = 2  # retard minimum pour être enregistré
# Train fantôme : au-delà de ce retard, un départ estimé collé à l'heure du relevé
# (à la tolérance près) glisse d'un relevé à l'autre — ce n'est pas une mesure.
GHOST_MIN_DELAY_MINUTES = 60
GHOST_SLIDE_TOLERANCE_MIN = 3


CANCEL_DEFAULT_IMPACT_MIN = 5  # default impact for cancelled trains
CANCEL_MARGIN_MIN = 2  # marge avant le départ attendu pour considérer une disparition comme suppression
PARIS_TZ = ZoneInfo("Europe/Paris")


async def collect_rt_delays() -> None:
    """Collecte les retards temps réel via l'endpoint /departures."""
    settings = get_settings()
    if not settings.prim_api_key:
        logger.warning("PRIM_API_KEY not set — skipping RT collection")
        return

    headers = {"apikey": settings.prim_api_key}
    # uid → (line_id, delay_min, base_dt, gare, direction, mission) : pire retard du train dans ce relevé
    all_delays: dict[str, tuple[str, int, datetime, str | None, str | None, str | None]] = {}
    # Track fetched navitia_ids per line for cancellation detection
    fetched_ids_by_line: dict[str, set[str]] = {}
    ghosts = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for navitia_id, line_id in LIGNES_CIBLES.items():
            url = f"{PRIM_NAVITIA_BASE}/lines/{navitia_id}/departures"
            fetched_ids_by_line[line_id] = set()
            try:
                resp = await client.get(url, headers=headers, params={
                    "count": 50,
                    "disable_geojson": "true",
                    "data_freshness": "realtime",
                })
                resp.raise_for_status()
                data = resp.json()
                obs_dt = datetime.now(timezone.utc)
                for dep in data.get("departures", []):
                    sdt = dep.get("stop_date_time", {})
                    if sdt.get("data_freshness") != "realtime":
                        continue
                    base_s = sdt.get("base_departure_date_time")
                    rt_s   = sdt.get("departure_date_time")
                    if not base_s or not rt_s:
                        continue
                    # Navitia renvoie les heures en heure locale de Paris
                    base_dt = datetime.strptime(base_s, "%Y%m%dT%H%M%S").replace(tzinfo=PARIS_TZ).astimezone(timezone.utc)
                    rt_dt   = datetime.strptime(rt_s,   "%Y%m%dT%H%M%S").replace(tzinfo=PARIS_TZ).astimezone(timezone.utc)
                    delay_min = int((rt_dt - base_dt).total_seconds() / 60)
                    vj_id = next(
                        (l["id"] for l in dep.get("links", []) if l.get("type") == "vehicle_journey"),
                        None,
                    )
                    if not vj_id:
                        continue
                    # Un incident par train et par jour, pas un par gare desservie.
                    # Le suffixe ":RealTime:<uuid>" change à chaque mise à jour temps réel :
                    # on garde l'identifiant de base du train.
                    train_id = vj_id.split(":RealTime:")[0]
                    uid = f"rt_{train_id}_{base_s[:8]}"
                    fetched_ids_by_line[line_id].add(uid)
                    if delay_min < MIN_DELAY_MINUTES:
                        continue
                    gare = dep.get("stop_point", {}).get("name") or None
                    # Train fantôme (supprimé ou arrêté mais resté dans le flux) : son départ
                    # estimé suit l'heure du relevé. Il reste « présent » pour la détection des
                    # suppressions, mais son retard n'est pas enregistré.
                    if (delay_min >= GHOST_MIN_DELAY_MINUTES
                            and abs((rt_dt - obs_dt).total_seconds()) <= GHOST_SLIDE_TOLERANCE_MIN * 60):
                        ghosts += 1
                        logger.warning("Train fantôme écarté : %s %s à %s, %d min", line_id, uid, gare, delay_min)
                        continue
                    infos = dep.get("display_informations", {})
                    # "Corbeil-Essonnes (Corbeil-Essonnes)" → "Corbeil-Essonnes"
                    direction = re.sub(r"\s*\([^)]*\)$", "", infos.get("direction") or "") or None
                    mission = infos.get("headsign") or None
                    prev = all_delays.get(uid)
                    if prev is None or delay_min > prev[1]:
                        all_delays[uid] = (line_id, delay_min, base_dt, gare, direction, mission)
            except httpx.HTTPError as exc:
                logger.error("PRIM RT error for %s: %s", line_id, exc)
                # Don't detect cancellations for lines with fetch errors
                fetched_ids_by_line.pop(line_id, None)
            except Exception as exc:
                logger.error("Unexpected RT error for %s: %s", line_id, exc)
                fetched_ids_by_line.pop(line_id, None)

    logger.info("Fetched %d RT delays from PRIM (%d trains fantômes écartés)", len(all_delays), ghosts)

    now = datetime.now(timezone.utc)
    inserted = 0
    cancelled = 0
    cancel_impact = getattr(settings, "cancel_default_impact_minutes", CANCEL_DEFAULT_IMPACT_MIN)

    async with AsyncSessionLocal() as session:
        for uid, (line_id, delay_min, base_dt, gare, direction, mission) in all_delays.items():
            heure_fin = now + timedelta(minutes=delay_min)
            cause = f"Retard de {delay_min} min à {gare}" if gare else f"Retard de {delay_min} min (temps réel)"
            stmt = insert(Incident).values(
                    navitia_id=uid,
                    line_id=line_id,
                    type_incident="DELAY_REALTIME",
                    cause=cause,
                    heure_debut=now,
                    heure_fin=heure_fin,
                    duree_minutes=delay_min,
                    source="realtime",
                    heure_theorique=base_dt,
                    is_cancelled=False,
                    gare=gare,
                    direction=direction,
                    mission=mission,
                    created_at=now,
                    updated_at=now,
            )
            # Garder le pire retard observé du train sur l'ensemble des relevés
            worse = stmt.excluded.duree_minutes >= Incident.duree_minutes
            stmt = stmt.on_conflict_do_update(
                index_elements=["navitia_id"],
                set_={
                    "duree_minutes": func.greatest(Incident.duree_minutes, stmt.excluded.duree_minutes),
                    "cause": case((worse, stmt.excluded.cause), else_=Incident.cause),
                    "heure_theorique": case((worse, stmt.excluded.heure_theorique), else_=Incident.heure_theorique),
                    "gare": case((worse, stmt.excluded.gare), else_=Incident.gare),
                    "direction": case((worse, stmt.excluded.direction), else_=Incident.direction),
                    "mission": case((worse, stmt.excluded.mission), else_=Incident.mission),
                    "heure_fin": heure_fin,
                    "source": "realtime",
                    # Un train revenu dans le flux n'était pas supprimé
                    "type_incident": "DELAY_REALTIME",
                    "is_cancelled": False,
                    "updated_at": now,
                },
            )
            await session.execute(stmt)
            inserted += 1

        # --- Cancellation detection ---
        # Un train qui disparaît du flux AVANT son départ attendu (heure prévue + retard)
        # à la gare enregistrée a été supprimé. Disparaître après ce départ est normal :
        # le train est parti ou arrivé au terminus.
        lookback = now - timedelta(hours=2)
        margin = timedelta(minutes=CANCEL_MARGIN_MIN)
        for line_id, fetched_ids in fetched_ids_by_line.items():
            if not fetched_ids:
                continue  # no departures fetched, skip
            stmt_recent = (
                select(Incident)
                .where(
                    Incident.line_id == line_id,
                    Incident.source == "realtime",
                    Incident.is_cancelled.isnot(True),
                    Incident.heure_theorique.isnot(None),
                    Incident.heure_theorique >= lookback,
                )
            )
            rows = (await session.execute(stmt_recent)).scalars().all()
            for row in rows:
                depart_attendu = row.heure_theorique + timedelta(minutes=row.duree_minutes or 0)
                if row.navitia_id not in fetched_ids and depart_attendu > now + margin:
                    row.is_cancelled = True
                    row.duree_minutes = cancel_impact
                    row.type_incident = "CANCELLED"
                    row.cause = "Train supprimé (disparu du flux temps réel)"
                    row.updated_at = now
                    cancelled += 1

        await session.commit()

    logger.info("Upserted %d RT delays, marked %d cancelled", inserted, cancelled)
