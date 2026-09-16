import json
import logging
from datetime import date, datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from sqlalchemy import select, func, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.models import Incident, DailyMetric
from backend.profils import categorie_jour, charger as _charger_profils

logger = logging.getLogger(__name__)

PARIS_TZ = ZoneInfo("Europe/Paris")

# Max duration for open incidents (no heure_fin, no duree_minutes)
MAX_OPEN_DURATION_MIN = 180

_FREQ_PATH = Path(__file__).parent.parent / "data" / "frequentation.json"

def _load_frequentation() -> dict[str, int]:
    try:
        return json.loads(_FREQ_PATH.read_text())
    except Exception as exc:
        logger.error("Cannot load frequentation.json: %s", exc)
        return {}


FREQUENTATION: dict[str, int] = _load_frequentation()

# Profils horaires et calendrier scolaire, construits hors ligne par
# `python -m backend.profils build`. Un seul lecteur, dans backend/profils.py.
PROFILS: dict = _charger_profils()

if not PROFILS:
    logger.error("profils_horaires.json illisible — repli sur la moyenne plate 18 h")


def part_horaire(line_id: str, quand: datetime) -> float | None:
    """Part des voyageurs du jour qui embarquent pendant l'heure de `quand` (heure de Paris).

    Les 24 parts d'un profil somment à 1 : il n'y a plus de diviseur à tenir à jour.
    None quand la ligne n'a pas de profil open data (métro, ligne inconnue).
    """
    reseau = PROFILS.get("lignes", {}).get(line_id)
    if reseau is None:
        return None
    profil = PROFILS.get("profils", {}).get(reseau, {}).get(categorie_jour(quand.date()))
    if not profil or len(profil) != 24:
        return None
    return profil[quand.hour]


def _minutes_voyageurs(duree_min: int, line_id: str, quand: datetime | None = None) -> int:
    """Minutes-voyageurs d'un retard : durée × voyageurs par minute à cette heure-là.

    `quand` est l'instant du début du retard, en heure de Paris.
    """
    if duree_min <= 0:
        return 0
    return round(duree_min * _freq_minute(line_id, quand))


def _effective_duration(incident, now_utc: datetime) -> int:
    """Compute effective duration in minutes for an incident.

    Priority: duree_minutes > timestamp diff > capped open duration.
    """
    if incident.duree_minutes is not None:
        return incident.duree_minutes

    if incident.heure_fin is not None and incident.heure_debut is not None:
        diff = (incident.heure_fin - incident.heure_debut).total_seconds() / 60
        return min(int(diff), MAX_OPEN_DURATION_MIN)

    # Open incident: diff from heure_debut to now, capped
    if incident.heure_debut is not None:
        diff = (now_utc - incident.heure_debut).total_seconds() / 60
        return min(int(max(diff, 0)), MAX_OPEN_DURATION_MIN)

    return 0


def _incident_dt_paris(incident) -> datetime | None:
    """Début de l'incident en heure de Paris. Le jour type (semaine/samedi/dimanche)
    dépend de la date, pas seulement de l'heure — d'où le datetime complet."""
    if incident.heure_debut is None:
        return None
    return incident.heure_debut.astimezone(PARIS_TZ)


def incident_minutes_voyageurs(incident, now_utc: datetime) -> tuple[int, int]:
    """(durée effective, minutes-voyageurs) d'un retard temps réel ou d'un train supprimé.

    Même calcul pour les métriques du jour et pour le coût par incident servi par l'API.
    """
    dur = _effective_duration(incident, now_utc)
    return dur, _minutes_voyageurs(dur, incident.line_id, _incident_dt_paris(incident))


def cout_eur(minutes_voyageurs: int, smic_horaire: float) -> int:
    """floor(minutes × smic / 60). Appliqué à UNE ligne de daily_metrics (ou à un incident),
    jamais à une somme : un total est la somme de ces coûts arrondis.

    Calcul en centimes entiers : pas d'erreur d'arrondi flottant (19,999… au lieu de 20).
    """
    return (minutes_voyageurs * round(smic_horaire * 100)) // 6000


async def compute_daily_metrics(target_date: date | None = None, db: AsyncSession | None = None) -> None:
    if target_date is None:
        target_date = datetime.now(PARIS_TZ).date()

    async def _run(session: AsyncSession) -> None:
        now_utc = datetime.now(timezone.utc)

        # Time window: 07h00 Paris on target_date → min(07h00 next day, now)
        day_07h = datetime.combine(target_date, time(7, 0), tzinfo=PARIS_TZ).astimezone(timezone.utc)
        next_day_07h = day_07h + timedelta(days=1)
        upper_bound = min(next_day_07h, now_utc)

        # Fetch all incidents in the window
        stmt = select(Incident).where(
            Incident.heure_debut >= day_07h,
            Incident.heure_debut < upper_bound,
        )
        rows = (await session.execute(stmt)).scalars().all()

        # Group by line, separate RT vs disruption
        from collections import defaultdict
        line_data: dict[str, dict] = defaultdict(lambda: {
            "rt_incidents": [],
            "disruptions": [],
            "cancelled": [],
        })

        for inc in rows:
            # Determine source — backward compat for old data without source
            source = inc.source
            if source is None:
                source = "realtime" if inc.type_incident == "DELAY_REALTIME" else "disruption"

            if inc.is_cancelled:
                line_data[inc.line_id]["cancelled"].append(inc)
            elif source == "realtime":
                line_data[inc.line_id]["rt_incidents"].append(inc)
            else:
                line_data[inc.line_id]["disruptions"].append(inc)

        now = datetime.now(timezone.utc)

        for line_id, data in line_data.items():
            rt_incidents = data["rt_incidents"]
            disruptions = data["disruptions"]
            cancelled = data["cancelled"]

            # Only RT incidents count for duree_totale and minutes_voyageurs
            duree_totale = 0
            total_mv = 0
            # Cancelled trains also contribute
            for inc in rt_incidents + cancelled:
                dur, mv = incident_minutes_voyageurs(inc, now_utc)
                duree_totale += dur
                total_mv += mv

            nb_rt = len(rt_incidents)
            nb_disr = len(disruptions)
            nb_canc = len(cancelled)
            nb_total = nb_rt + nb_canc  # disruptions don't count as incidents

            upsert = (
                insert(DailyMetric)
                .values(
                    date=target_date,
                    line_id=line_id,
                    nb_incidents=nb_total,
                    duree_totale_min=duree_totale,
                    minutes_voyageurs=total_mv,
                    nb_rt_delays=nb_rt,
                    nb_disruptions=nb_disr,
                    nb_cancelled=nb_canc,
                    est_jour_perturbe=(nb_total > 0),
                    computed_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_daily_metrics_date_line",
                    set_={
                        "nb_incidents": nb_total,
                        "duree_totale_min": duree_totale,
                        "minutes_voyageurs": total_mv,
                        "nb_rt_delays": nb_rt,
                        "nb_disruptions": nb_disr,
                        "nb_cancelled": nb_canc,
                        "est_jour_perturbe": (nb_total > 0),
                        "computed_at": now,
                    },
                )
            )
            await session.execute(upsert)

        await session.commit()
        logger.info("Computed daily metrics for %s (%d lines)", target_date, len(line_data))

    if db is not None:
        await _run(db)
    else:
        async with AsyncSessionLocal() as session:
            await _run(session)


async def get_today_stats(db: AsyncSession) -> dict:
    today = datetime.now(PARIS_TZ).date()
    stmt = select(DailyMetric).where(DailyMetric.date == today)
    rows = (await db.execute(stmt)).scalars().all()

    total_incidents = sum(r.nb_incidents for r in rows)
    total_duree = sum(r.duree_totale_min for r in rows)
    total_mv = sum(r.minutes_voyageurs for r in rows)
    lignes_perturbees = [r.line_id for r in rows if r.est_jour_perturbe]
    smic = get_settings().smic_horaire

    return {
        "date": today.isoformat(),
        "total_incidents": total_incidents,
        "total_duree_min": total_duree,
        "total_minutes_voyageurs": total_mv,
        # Arrondi par ligne puis sommé, comme les bilans : même coût du jour partout
        "cout_eur": sum(cout_eur(r.minutes_voyageurs, smic) for r in rows),
        "smic_horaire": smic,
        "lignes_perturbees": lignes_perturbees,
        "nb_lignes_perturbees": len(lignes_perturbees),
    }


def _freq_minute(line_id: str, quand: datetime | None) -> float:
    """Voyageurs par minute sur une ligne à un instant donné (heure de Paris).

    Unique endroit où la fréquentation devient un débit : _minutes_voyageurs et le retard
    moyen pondéré s'appuient tous deux dessus.
    """
    voyageurs_jour = FREQUENTATION.get(line_id, 0)
    if voyageurs_jour == 0:
        return 0.0
    if quand is not None:
        part = part_horaire(line_id, quand)
        if part is not None:
            return voyageurs_jour * part / 60
    # Repli plat sur les 18 h de service : lignes sans profil open data (métro), ou instant inconnu
    return voyageurs_jour / 18 / 60


async def _retard_moyen_pondere(line_id: str, start: date, end: date, db: AsyncSession) -> float:
    """Retard moyen pondéré par la fréquentation horaire (minutes).

    = Σ(durée_i × poids_horaire_i) / Σ(poids_horaire_i)
    Un retard de 48 min en heure de pointe pèse plus qu'un retard de 5 min à 22 h.
    """
    start_utc = datetime.combine(start, time(7, 0), tzinfo=PARIS_TZ).astimezone(timezone.utc)
    end_utc = datetime.combine(end + timedelta(days=1), time(7, 0), tzinfo=PARIS_TZ).astimezone(timezone.utc)
    now_utc = datetime.now(timezone.utc)
    upper = min(end_utc, now_utc)

    stmt = select(Incident).where(
        Incident.line_id == line_id,
        Incident.heure_debut >= start_utc,
        Incident.heure_debut < upper,
        or_(
            Incident.source == "realtime",
            Incident.is_cancelled == True,
        ),
    )
    incidents = (await db.execute(stmt)).scalars().all()

    sum_dur_x_poids = 0.0
    sum_poids = 0.0
    for inc in incidents:
        dur = _effective_duration(inc, now_utc)
        if dur <= 0:
            continue
        poids = _freq_minute(line_id, _incident_dt_paris(inc))
        if poids <= 0:
            continue
        sum_dur_x_poids += dur * poids
        sum_poids += poids

    if sum_poids == 0:
        return 0.0
    return sum_dur_x_poids / sum_poids


async def get_line_stats(line_id: str, period: int, db: AsyncSession) -> dict:
    end = datetime.now(PARIS_TZ).date()
    start = end - timedelta(days=period - 1)

    stmt = (
        select(DailyMetric)
        .where(DailyMetric.line_id == line_id, DailyMetric.date >= start)
        .order_by(DailyMetric.date)
    )
    rows = (await db.execute(stmt)).scalars().all()
    smic = get_settings().smic_horaire

    retard_moyen = await _retard_moyen_pondere(line_id, start, end, db)

    return {
        "line_id": line_id,
        "period_days": period,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "total_incidents": sum(r.nb_incidents for r in rows),
        "total_duree_min": sum(r.duree_totale_min for r in rows),
        "total_minutes_voyageurs": sum(r.minutes_voyageurs for r in rows),
        "total_cout_eur": sum(cout_eur(r.minutes_voyageurs, smic) for r in rows),
        "jours_perturbes": sum(1 for r in rows if r.est_jour_perturbe),
        "retard_moyen_min": round(retard_moyen, 1),
        "retard_moyen_eur": round(retard_moyen * smic / 60, 2),
        "daily": [
            {
                "date": r.date.isoformat(),
                "nb_incidents": r.nb_incidents,
                "duree_totale_min": r.duree_totale_min,
                "minutes_voyageurs": r.minutes_voyageurs,
                "est_jour_perturbe": r.est_jour_perturbe,
            }
            for r in rows
        ],
    }
