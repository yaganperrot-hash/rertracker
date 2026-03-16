import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import AsyncSessionLocal
from backend.models import Incident, DailyMetric

logger = logging.getLogger(__name__)

_FREQ_PATH = Path(__file__).parent.parent / "data" / "frequentation.json"

def _load_frequentation() -> dict[str, int]:
    try:
        return json.loads(_FREQ_PATH.read_text())
    except Exception as exc:
        logger.error("Cannot load frequentation.json: %s", exc)
        return {}


FREQUENTATION: dict[str, int] = _load_frequentation()


def _minutes_voyageurs(duree_min: int, line_id: str) -> int:
    voyageurs_jour = FREQUENTATION.get(line_id, 0)
    if voyageurs_jour == 0:
        return 0
    freq_horaire = voyageurs_jour / 18  # 6h-24h
    freq_minute = freq_horaire / 60
    return round(duree_min * freq_minute)


async def compute_daily_metrics(target_date: date | None = None, db: AsyncSession | None = None) -> None:
    if target_date is None:
        target_date = date.today()

    async def _run(session: AsyncSession) -> None:
        # Fetch all closed incidents for this date
        stmt = select(
            Incident.line_id,
            func.count(Incident.id).label("nb_incidents"),
            func.coalesce(func.sum(Incident.duree_minutes), 0).label("duree_totale_min"),
        ).where(
            func.date(Incident.heure_debut) == target_date,
            Incident.duree_minutes.isnot(None),
        ).group_by(Incident.line_id)

        rows = (await session.execute(stmt)).all()
        now = datetime.now(timezone.utc)

        for row in rows:
            line_id = row.line_id
            nb = row.nb_incidents
            duree = int(row.duree_totale_min)
            mv = _minutes_voyageurs(duree, line_id)

            upsert = (
                insert(DailyMetric)
                .values(
                    date=target_date,
                    line_id=line_id,
                    nb_incidents=nb,
                    duree_totale_min=duree,
                    minutes_voyageurs=mv,
                    est_jour_perturbe=(nb > 0),
                    computed_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_daily_metrics_date_line",
                    set_={
                        "nb_incidents": nb,
                        "duree_totale_min": duree,
                        "minutes_voyageurs": mv,
                        "est_jour_perturbe": (nb > 0),
                        "computed_at": now,
                    },
                )
            )
            await session.execute(upsert)

        await session.commit()
        logger.info("Computed daily metrics for %s (%d lines)", target_date, len(rows))

    if db is not None:
        await _run(db)
    else:
        async with AsyncSessionLocal() as session:
            await _run(session)


async def get_today_stats(db: AsyncSession) -> dict:
    today = date.today()
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
    from datetime import timedelta
    end = date.today()
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
