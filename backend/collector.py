import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
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
    "line:IDFM:C01732": "TRANSILIEN_L",
    "line:IDFM:C01733": "TRANSILIEN_N",
    "line:IDFM:C01734": "TRANSILIEN_P",
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
                    if d.get("status") == "active":
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
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["navitia_id"],
                    set_={
                        "heure_fin": heure_fin,
                        "duree_minutes": duree_minutes,
                        "updated_at": now,
                    },
                )
            )
            await session.execute(stmt)
            inserted += 1

        await session.commit()

    logger.info("Upserted %d incidents for tracked lines", inserted)
