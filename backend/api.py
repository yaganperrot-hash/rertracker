from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Incident, DailyMetric
from backend.metrics import get_today_stats, get_line_stats, compute_daily_metrics
from backend.collector import collect_disruptions

router = APIRouter(prefix="/api")

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("/stats/today")
async def stats_today(db: DbDep):
    return await get_today_stats(db)


@router.get("/stats/line/{line_id}")
async def stats_line(line_id: str, db: DbDep, period: int = Query(default=30, ge=1, le=365)):
    return await get_line_stats(line_id, period, db)


@router.get("/incidents/current")
async def incidents_current(db: DbDep):
    stmt = (
        select(Incident)
        .where(Incident.heure_fin.is_(None))
        .order_by(Incident.heure_debut.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "navitia_id": r.navitia_id,
            "line_id": r.line_id,
            "type_incident": r.type_incident,
            "cause": r.cause,
            "heure_debut": r.heure_debut.isoformat(),
            "heure_fin": None,
        }
        for r in rows
    ]


@router.get("/incidents/history")
async def incidents_history(
    db: DbDep,
    line: str | None = Query(default=None),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    stmt = select(Incident).order_by(Incident.heure_debut.desc()).limit(limit)
    if line:
        stmt = stmt.where(Incident.line_id == line)
    if from_date:
        stmt = stmt.where(Incident.heure_debut >= from_date)
    if to_date:
        stmt = stmt.where(Incident.heure_debut <= to_date)

    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "navitia_id": r.navitia_id,
            "line_id": r.line_id,
            "type_incident": r.type_incident,
            "cause": r.cause,
            "heure_debut": r.heure_debut.isoformat(),
            "heure_fin": r.heure_fin.isoformat() if r.heure_fin else None,
            "duree_minutes": r.duree_minutes,
        }
        for r in rows
    ]


@router.post("/admin/collect")
async def admin_collect():
    await collect_disruptions()
    await compute_daily_metrics()
    return {"status": "ok"}
