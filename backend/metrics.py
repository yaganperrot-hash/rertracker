import json
import logging
from datetime import date, datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from sqlalchemy import select, func, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import AsyncSessionLocal
from backend.models import Incident, DailyMetric

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

# Hourly weight profile (sum = 18.0 to stay consistent with old /18 daily calc)
HOURLY_WEIGHTS: dict[int, float] = {
    6: 0.5,  7: 1.8,  8: 2.5,  9: 1.5, 10: 0.8, 11: 0.7,
    12: 0.8, 13: 0.7, 14: 0.7, 15: 0.8, 16: 1.2, 17: 2.2,
    18: 2.0, 19: 1.2, 20: 0.8, 21: 0.5, 22: 0.3, 23: 0.2,
}


def _minutes_voyageurs(duree_min: int, line_id: str, hour: int | None = None) -> int:
    """Calculate minutes-voyageurs for a given duration and line.

    If hour is provided, use the hourly weight profile for that hour.
    If hour is None (backward compat), use the flat daily average (voyageurs/18/60).
    """
    voyageurs_jour = FREQUENTATION.get(line_id, 0)
    if voyageurs_jour == 0 or duree_min <= 0:
        return 0

    if hour is not None:
        weight = HOURLY_WEIGHTS.get(hour, 0.0)
        if weight == 0.0:
            return 0
        # weight represents the share of daily passengers in that hour
        # voyageurs_jour * weight / 18 = passengers in that hour
        # divided by 60 = passengers per minute in that hour
        freq_minute = voyageurs_jour * weight / 18 / 60
    else:
        # Backward compat: flat average over 18h service window
        freq_minute = voyageurs_jour / 18 / 60

    return round(duree_min * freq_minute)


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


def _incident_hour_paris(incident) -> int | None:
    """Get the Paris-timezone hour of an incident's start."""
    if incident.heure_debut is None:
        return None
    return incident.heure_debut.astimezone(PARIS_TZ).hour


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
            for inc in rt_incidents:
                dur = _effective_duration(inc, now_utc)
                duree_totale += dur
                hour = _incident_hour_paris(inc)
                total_mv += _minutes_voyageurs(dur, line_id, hour=hour)

            # Cancelled trains also contribute
            for inc in cancelled:
                dur = _effective_duration(inc, now_utc)
                duree_totale += dur
                hour = _incident_hour_paris(inc)
                total_mv += _minutes_voyageurs(dur, line_id, hour=hour)

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

    return {
        "date": today.isoformat(),
        "total_incidents": total_incidents,
        "total_duree_min": total_duree,
        "total_minutes_voyageurs": total_mv,
        "lignes_perturbees": lignes_perturbees,
        "nb_lignes_perturbees": len(lignes_perturbees),
    }


async def get_line_stats(line_id: str, period: int, db: AsyncSession) -> dict:
    end = datetime.now(PARIS_TZ).date()
    start = end - timedelta(days=period - 1)

    stmt = (
        select(DailyMetric)
        .where(DailyMetric.line_id == line_id, DailyMetric.date >= start)
        .order_by(DailyMetric.date)
    )
    rows = (await db.execute(stmt)).scalars().all()

    return {
        "line_id": line_id,
        "period_days": period,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "total_incidents": sum(r.nb_incidents for r in rows),
        "total_duree_min": sum(r.duree_totale_min for r in rows),
        "total_minutes_voyageurs": sum(r.minutes_voyageurs for r in rows),
        "jours_perturbes": sum(1 for r in rows if r.est_jour_perturbe),
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
