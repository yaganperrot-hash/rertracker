import logging
import statistics
from datetime import date, datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, func, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.models import Incident, DailyMetric
from backend.profils import CAT_SEMAINE, categorie_jour, charger as _charger_profils
from backend import frequentation, offre

logger = logging.getLogger(__name__)

PARIS_TZ = ZoneInfo("Europe/Paris")

# Max duration for open incidents (no heure_fin, no duree_minutes)
MAX_OPEN_DURATION_MIN = 180

# Voyageurs montant dans un train par ligne, gare, jour type et heure (comptages SNCF, validations IDFM),
# construits par `python -m backend.frequentation build`. Lecteur unique : backend/frequentation.py.
FREQ_GARES: dict = frequentation.charger()

if not FREQ_GARES:
    logger.error("frequentation_gares.json illisible — minutes-voyageurs nulles")

# Voyageurs montés par jour ouvré ordinaire, par ligne : ordre de grandeur affiché (/api/reference)
FREQUENTATION: dict[str, int] = {
    ligne: round(sum(cats.get(CAT_SEMAINE, {}).values()))
    for ligne, cats in FREQ_GARES.get("montees_jour", {}).items()
}

# Profils horaires et calendrier scolaire, construits hors ligne par
# `python -m backend.profils build`. Un seul lecteur, dans backend/profils.py.
PROFILS: dict = _charger_profils()

if not PROFILS:
    logger.error("profils_horaires.json illisible — jours types sans vacances scolaires")

# Offre théorique GTFS (départs, intervalles, missions), construite par `python -m backend.offre build`
OFFRE: dict = offre.charger()

if not OFFRE:
    logger.error("offre_theorique.json illisible — parcours et intervalles inconnus")


def part_horaire(line_id: str, quand: datetime) -> float | None:
    """Part des validations du jour sur l'heure de `quand` (heure de Paris), profil du réseau de la ligne.
    None quand la ligne n'a pas de profil open data."""
    reseau = PROFILS.get("lignes", {}).get(line_id)
    if reseau is None:
        return None
    profil = PROFILS.get("profils", {}).get(reseau, {}).get(categorie_jour(quand.date()))
    if not profil or len(profil) != 24:
        return None
    return profil[quand.hour]


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
    """Heure prévue du train en heure de Paris, sinon le début de l'incident (heure du relevé).
    Le jour type dépend de la date, pas seulement de l'heure — d'où le datetime complet."""
    instant = getattr(incident, "heure_theorique", None) or incident.heure_debut
    if instant is None:
        return None
    return instant.astimezone(PARIS_TZ)


def arrets_du_train(incident, now_utc: datetime) -> list[dict] | None:
    """Arrêts du train, dans l'ordre : {"g", "quand" (Paris), "r", "s", "w"}.

    Relevés arrêt par arrêt dans le flux SIRI (colonne `arrets`) depuis la bascule. Le flux ne remonte
    qu'une cinquantaine de minutes dans le passé : les gares déjà desservies quand le train a été relevé
    pour la première fois sont reprises de la mission GTFS, sans retard connu (leurs voyageurs comptent,
    avec le retard mesuré là où ils descendent).
    Pour un incident d'avant la bascule, parcours reconstitué depuis la mission GTFS : pas de retard
    avant la gare où le pire retard a été relevé, ce retard à partir d'elle (ou suppression à partir
    d'elle), heure prévue partout.
    """
    if getattr(incident, "arrets", None):
        releves = [{"g": a.get("g"), "quand": datetime.fromisoformat(a["p"]).astimezone(PARIS_TZ),
                    "r": a.get("r"), "s": bool(a.get("s")), "w": a.get("w")} for a in incident.arrets if a.get("p")]
        if not releves:
            return None
        parcours = offre.parcours_mission(incident.line_id, getattr(incident, "mission", None), releves[0]["g"])
        if parcours and releves[0]["g"] in parcours:
            avant = parcours[:parcours.index(releves[0]["g"])]
            releves = [{"g": g, "quand": releves[0]["quand"], "r": None, "s": False, "w": None} for g in avant] + releves
        return releves
    quand = _incident_dt_paris(incident)
    gares = offre.parcours_mission(incident.line_id, getattr(incident, "mission", None), getattr(incident, "gare", None))
    if quand is None or not gares:
        return None
    gare = getattr(incident, "gare", None)
    debut = gares.index(gare) if gare in gares else 0
    supprime = bool(getattr(incident, "is_cancelled", False))
    retard = 0 if supprime else _effective_duration(incident, now_utc)
    return [{"g": g, "quand": quand, "r": retard if i >= debut else 0, "s": supprime and i >= debut, "w": None}
            for i, g in enumerate(gares)]


def _attente(line_id: str, arret: dict) -> int:
    """Attente d'un voyageur à un arrêt supprimé : mesurée (train suivant réellement passé) ; à défaut,
    intervalle prévu à cette heure ; à défaut, valeur de repli de la configuration."""
    if arret.get("w") is not None:
        return arret["w"]
    intervalle = offre.intervalle_min(line_id, arret["quand"])
    return round(intervalle) if intervalle is not None else get_settings().cancel_default_impact_minutes


def minutes_voyageurs_train(line_id: str, arrets: list[dict]) -> int:
    """Minutes perdues par les voyageurs d'un train.

    Voyageurs montés à l'arrêt i : montées dans un train à cette gare et à cette heure (mesurées).
    Destination : arrêt j > i avec la probabilité w_j ÷ Σ_{l>i} w_l, w = voyageurs montés sur la journée
    à la gare j (hypothèse : une gare voit descendre autant de voyageurs qu'elle en voit monter).
    Perte du voyageur i → j :
      * un arrêt supprimé entre i et j (inclus) : attente au premier arrêt supprimé ;
      * sinon retard à l'arrivée mesuré en j, compté dès MIN_DELAY_MINUTES.
    Invariant : chaque voyageur monté (hors terminus) est affecté à exactement une destination.
    """
    from backend.collector import MIN_DELAY_MINUTES

    n = len(arrets)
    if n < 2:
        return 0
    montees = [frequentation.montees_train(line_id, a["g"], a["quand"]) or 0.0 if a["g"] else 0.0 for a in arrets]
    montees[-1] = 0.0
    poids = [frequentation.montees_jour(line_id, a["g"], a["quand"]) or 0.0 if a["g"] else 0.0 for a in arrets]
    connus = [p for p in poids if p > 0]
    repli = statistics.median(connus) if connus else 1.0
    poids = [p if p > 0 else repli for p in poids]

    retards = [a["r"] if a.get("r") is not None and a["r"] >= MIN_DELAY_MINUTES else 0 for a in arrets]
    attentes = [_attente(line_id, a) if a.get("s") else None for a in arrets]

    total = 0.0
    for i in range(n - 1):
        if montees[i] <= 0:
            continue
        somme_poids = sum(poids[i + 1:])
        premier_supprime = None
        if attentes[i] is not None:
            premier_supprime = i
        for j in range(i + 1, n):
            if premier_supprime is None and attentes[j] is not None:
                premier_supprime = j
            perte = attentes[premier_supprime] if premier_supprime is not None else retards[j]
            if perte:
                total += montees[i] * poids[j] / somme_poids * perte
    return round(total)


def incident_minutes_voyageurs(incident, now_utc: datetime) -> tuple[int, int]:
    """(durée affichée, minutes-voyageurs) d'un retard temps réel ou d'un train supprimé.

    Durée affichée : pire retard relevé, ou plus longue attente pour un train supprimé.
    Même calcul pour les métriques du jour et pour le coût par incident servi par l'API.
    """
    arrets = arrets_du_train(incident, now_utc)
    if getattr(incident, "is_cancelled", False):
        attentes = [_attente(incident.line_id, a) for a in (arrets or []) if a["s"]]
        dur = max(attentes) if attentes else get_settings().cancel_default_impact_minutes
    else:
        dur = _effective_duration(incident, now_utc)
    if not arrets or dur <= 0:
        return dur, 0
    return dur, minutes_voyageurs_train(incident.line_id, arrets)


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


async def _retard_moyen_pondere(line_id: str, start: date, end: date, db: AsyncSession) -> float:
    """Retard moyen pondéré par les voyageurs touchés (minutes).

    = Σ(durée_i × voyageurs_touchés_i) / Σ(voyageurs_touchés_i), voyageurs_touchés = minutes-voyageurs ÷ durée
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
        dur, mv = incident_minutes_voyageurs(inc, now_utc)
        if dur <= 0:
            continue
        poids = mv / dur   # voyageurs touchés
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
