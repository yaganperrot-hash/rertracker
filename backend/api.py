from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models import Incident, DailyMetric
from backend.metrics import (
    FREQ_GARES, FREQUENTATION, OFFRE, PROFILS, compute_daily_metrics, exemple_calcul, cout_eur, get_line_stats, get_today_stats,
    incident_minutes_voyageurs,
)
from backend.collector import (
    GHOST_MIN_DELAY_MINUTES, LIGNES_CIBLES, MIN_DELAY_MINUTES, MODES_PHYSIQUES,
    collect_disruptions, collect_rt_delays,
)
from backend.causes import categoriser_cause, resume_perturbation, texte_lisible

router = APIRouter(prefix="/api")

DbDep = Annotated[AsyncSession, Depends(get_db)]


def _impact(r: Incident, now_utc: datetime, smic: float) -> tuple[int | None, int | None, int | None]:
    """(durée comptée, minutes-voyageurs, coût €) d'un incident, calculés comme les métriques du jour.

    Seuls les retards temps réel et les trains supprimés comptent ; une perturbation
    déclarée n'a pas de coût propre (durée stockée, None, None). Un train supprimé compte pour
    l'intervalle jusqu'au train suivant, pas pour la valeur de repli stockée en base.
    """
    source = r.source or ("realtime" if r.type_incident == "DELAY_REALTIME" else "disruption")
    if source != "realtime" and not r.is_cancelled:
        return r.duree_minutes, None, None
    dur, mv = incident_minutes_voyageurs(r, now_utc)
    return dur, mv, cout_eur(mv, smic)


def _serialize_incident(r: Incident, now_utc: datetime, smic: float) -> dict:
    duree, minutes_voyageurs, cout = _impact(r, now_utc, smic)
    return {
        "id": r.id,
        "navitia_id": r.navitia_id,
        "line_id": r.line_id,
        "type_incident": r.type_incident,
        # Messages PRIM en HTML : texte lisible, résumé d'une ligne et cause classée pour l'affichage
        "cause": texte_lisible(r.cause) or None,
        "resume": resume_perturbation(r.cause) or None,
        "categorie": categoriser_cause(r.cause) if r.source == "disruption" else None,
        "heure_debut": r.heure_debut.isoformat(),
        "heure_fin": r.heure_fin.isoformat() if r.heure_fin else None,
        "duree_minutes": duree,
        "minutes_voyageurs": minutes_voyageurs,
        "cout_eur": cout,
        "source": r.source,
        "heure_theorique": r.heure_theorique.isoformat() if r.heure_theorique else None,
        "is_cancelled": r.is_cancelled,
        "gare": r.gare,
        "direction": r.direction,
        "mission": r.mission,
    }


@router.get("/stats/today")
async def stats_today(db: DbDep):
    return await get_today_stats(db)


@router.get("/stats/line/{line_id}")
async def stats_line(line_id: str, db: DbDep, period: int = Query(default=30, ge=1, le=365)):
    return await get_line_stats(line_id, period, db)


@router.get("/reference")
async def reference():
    """Paramètres de calcul affichés par les pages (méthode) : une seule source, la config."""
    s = get_settings()
    releves_jour = (24 - s.collecte_heure_debut) * 60 // s.polling_interval_minutes  # pas de relevé la nuit
    return {
        "smic_horaire": s.smic_horaire,
        "smic_source": s.smic_source,
        "polling_interval_minutes": s.polling_interval_minutes,
        "bilans_interval_minutes": s.bilans_interval_minutes,
        # À chaque relevé : un appel perturbations par mode (RER, Transilien, compteur Navitia)
        # + un appel Estimated Timetable par ligne (compteur distinct)
        "requetes_prim_jour": releves_jour * (len(MODES_PHYSIQUES) + len(LIGNES_CIBLES)),
        "requetes_navitia_jour": releves_jour * len(MODES_PHYSIQUES),
        "requetes_et_jour": releves_jour * len(LIGNES_CIBLES),
        "quota_prim_jour": s.prim_quota_jour,
        "collecte_heure_debut": s.collecte_heure_debut,
        # Voyageurs montés par jour ouvré ordinaire, par ligne (comptages SNCF, validations IDFM)
        "frequentation": FREQUENTATION,
        "frequentation_origines": {
            ligne: {"comptage": sum(o.startswith("comptage") for o in gares.values()),
                    "validations": sum(o.startswith("validations") for o in gares.values())}
            for ligne, gares in FREQ_GARES.get("origine", {}).items()
        },
        "frequentation_rapports_vacances": FREQ_GARES.get("_source", {}).get("rapports_vacances", {}),
        "exemple_calcul": exemple_calcul(),
        # Profils horaires réels (validations open data IDFM) : parts sommant à 1 sur 24 h,
        # par réseau et par jour type. `profils_lignes` dit quelle ligne lit quel réseau.
        "profils_horaires": PROFILS.get("profils", {}),
        "profils_lignes": PROFILS.get("lignes", {}),
        "profils_reseaux": PROFILS.get("reseaux_libelles", {}),
        "profils_source": PROFILS.get("_source", {}),
        "retard_min_minutes": MIN_DELAY_MINUTES,
        # Valeur de repli : un train supprimé compte pour l'intervalle de l'offre théorique
        "suppression_minutes": s.cancel_default_impact_minutes,
        # Offre théorique GTFS : trains équivalents et intervalle par ligne, jour type et heure
        "offre_trains_heure": OFFRE.get("trains_heure", {}),
        "offre_intervalle_min": OFFRE.get("intervalle_min", {}),
        "offre_source": OFFRE.get("_source", {}),
        "fantome_min_minutes": GHOST_MIN_DELAY_MINUTES,
    }


@router.get("/incidents/current")
async def incidents_current(db: DbDep, source: str | None = Query(default=None)):
    now = datetime.now(timezone.utc)
    stmt = (
        select(Incident)
        .where(
            Incident.heure_debut <= now,
            or_(Incident.heure_fin >= now, Incident.heure_fin.is_(None)),
        )
        .order_by(Incident.heure_debut.desc())
    )
    if source:
        stmt = stmt.where(Incident.source == source)
    rows = (await db.execute(stmt)).scalars().all()
    smic = get_settings().smic_horaire
    return [_serialize_incident(r, now, smic) for r in rows]


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
    now = datetime.now(timezone.utc)
    smic = get_settings().smic_horaire
    return [_serialize_incident(r, now, smic) for r in rows]


@router.post("/admin/collect")
async def admin_collect():
    await collect_disruptions()
    await collect_rt_delays()
    await compute_daily_metrics()
    return {"status": "ok"}
