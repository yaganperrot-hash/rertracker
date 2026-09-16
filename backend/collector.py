import logging
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.models import Incident

logger = logging.getLogger(__name__)

PRIM_BASE_URL = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia"
# Flux SIRI Estimated Timetable : tous les trains d'une ligne sur ~2 h, arrêt par arrêt, suppressions comprises
PRIM_ET_URL = "https://prim.iledefrance-mobilites.fr/marketplace/estimated-timetable"

QUOTA_ALERTE = 150  # warning quand il reste moins de requêtes PRIM pour la journée
# Derniers x-ratelimit-remaining-day lus. Deux compteurs distincts de 1 000 req/jour, constatés dans les
# en-têtes le 2026-09-16 : Navitia (perturbations) et Estimated Timetable (retards, suppressions).
quota_restant: int | None = None
quota_restant_et: int | None = None


def collecte_autorisee(maintenant: datetime | None = None) -> bool:
    """Relevés PRIM de collecte_heure_debut à minuit, heure de Paris : la nuit ne pèse rien dans le calcul."""
    maintenant = maintenant or datetime.now(timezone.utc)
    return maintenant.astimezone(PARIS_TZ).hour >= get_settings().collecte_heure_debut


def _suivre_quota(resp, flux: str = "navitia") -> None:
    """Retient le quota restant renvoyé par PRIM dans chaque réponse (y compris un 429).
    `flux` : "navitia" ou "et" (Estimated Timetable), chacun son compteur."""
    global quota_restant, quota_restant_et
    headers = getattr(resp, "headers", None)
    if not isinstance(headers, Mapping):
        return
    valeur = headers.get("x-ratelimit-remaining-day")
    if valeur is not None and str(valeur).isdigit():
        if flux == "et":
            quota_restant_et = int(valeur)
        else:
            quota_restant = int(valeur)


def _journaliser_quota() -> None:
    for libelle, reste in (("Navitia", quota_restant), ("Estimated Timetable", quota_restant_et)):
        if reste is None:
            continue
        niveau = logging.WARNING if reste < QUOTA_ALERTE else logging.INFO
        logger.log(niveau, "Quota PRIM restant aujourd'hui : %d requêtes (%s)", reste, libelle)

# Mapping Navitia line ID → internal line_id
LIGNES_CIBLES: dict[str, str] = {
    "line:IDFM:C01742": "RER_A",
    "line:IDFM:C01743": "RER_B",
    "line:IDFM:C01727": "RER_C",
    "line:IDFM:C01728": "RER_D",
    "line:IDFM:C01729": "RER_E",
    # Transilien : IDs vérifiés sur PRIM (pt_objects) le 2026-09-15. Avant, J/K/U pointaient
    # sur P/R/N, L/N/P sur des bus et R sur rien — voir backend/relabel_transilien.py
    "line:IDFM:C01737": "TRANSILIEN_H",
    "line:IDFM:C01739": "TRANSILIEN_J",
    "line:IDFM:C01738": "TRANSILIEN_K",
    "line:IDFM:C01740": "TRANSILIEN_L",
    "line:IDFM:C01736": "TRANSILIEN_N",
    "line:IDFM:C01730": "TRANSILIEN_P",
    "line:IDFM:C01731": "TRANSILIEN_R",
    "line:IDFM:C01741": "TRANSILIEN_U",
}


PARIS_TZ = ZoneInfo("Europe/Paris")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # PRIM returns ISO 8601 e.g. "20240101T063000" in Paris local time
        dt = datetime.strptime(value, "%Y%m%dT%H%M%S")
        return dt.replace(tzinfo=PARIS_TZ).astimezone(timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(value).replace(tzinfo=PARIS_TZ).astimezone(timezone.utc)
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


# Perturbations par mode physique : 1 appel pour les 5 RER, 1 pour les 8 Transilien.
# L'appel global /line_reports (sans filtre) renvoie une liste vide depuis le 2026-09-12.
MODES_PHYSIQUES = ("physical_mode:RapidTransit", "physical_mode:LocalTrain")


async def collect_disruptions() -> None:
    settings = get_settings()
    if not settings.prim_api_key:
        logger.warning("PRIM_API_KEY not set — skipping collection")
        return

    headers = {"apikey": settings.prim_api_key}

    all_disruptions: list[tuple[str, dict]] = []  # (line_id_interne, disruption)
    vues: set[str] = set()  # une même perturbation peut revenir dans les deux modes
    nb_appels = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for mode in MODES_PHYSIQUES:
            url = f"{PRIM_BASE_URL}/physical_modes/{mode}/line_reports"
            page = 0
            while True:
                params = {"count": 250, "start_page": page, "disable_geojson": "true"}
                nb_appels += 1
                try:
                    resp = await client.get(url, headers=headers, params=params)
                    _suivre_quota(resp)
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPError as exc:
                    logger.error("PRIM API error (disruptions %s): %s", mode, exc)
                    break
                except Exception as exc:
                    logger.error("Unexpected error (disruptions %s): %s", mode, exc)
                    break

                line_reports = data.get("line_reports", [])
                # Réponse 200 mais vide : panne silencieuse (cas de l'appel global du 12 au 15/09)
                if page == 0 and not line_reports:
                    logger.warning("PRIM : 0 line_report pour %s — perturbations non collectées", mode)

                for d in data.get("disruptions", []):
                    if d.get("status") not in ("active", "future"):
                        continue
                    did = d.get("id")
                    if did and did in vues:
                        continue
                    line_id = _extract_line_id(d.get("impacted_objects", []))
                    if line_id:
                        if did:
                            vues.add(did)
                        all_disruptions.append((line_id, d))

                # Pagination : s'arrêter si moins de résultats que demandé
                if len(line_reports) < 250:
                    break
                page += 1
                if page > 10:  # sécurité anti-boucle infinie
                    break

    logger.info("Fetched %d disruptions from PRIM (%d calls)", len(all_disruptions), nb_appels)

    # Diagnostic : lignes sans aucune disruption
    lines_with = {lid for lid, _ in all_disruptions}
    for lid in LIGNES_CIBLES.values():
        if lid not in lines_with:
            logger.debug("0 disruption pour %s — vérifier le payload PRIM si persistant", lid)

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


MIN_DELAY_MINUTES = 2  # retard minimum pour être enregistré (et compté, arrêt par arrêt)
# Train fantôme : au-delà de ce retard, une heure estimée collée à l'heure du relevé
# (à la tolérance près) glisse d'un relevé à l'autre — ce n'est pas une mesure.
GHOST_MIN_DELAY_MINUTES = 60
GHOST_SLIDE_TOLERANCE_MIN = 3

CANCEL_DEFAULT_IMPACT_MIN = 5  # valeur stockée pour un train supprimé ; le calcul lit les attentes mesurées

STATUT_SUPPRIME = "CANCELLED"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _valeur(champ) -> str | None:
    """SIRI JSON : {"value": x} ou [{"value": x}] → x."""
    if isinstance(champ, list):
        champ = champ[0] if champ else None
    if isinstance(champ, dict):
        return champ.get("value")
    return None


def _iso(value: str | None) -> datetime | None:
    """Horodatage SIRI (« 2026-09-16T11:01:08.000Z ») → datetime UTC."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _minutes(debut: datetime, fin: datetime) -> int:
    return int((fin - debut).total_seconds() // 60)


def _numero_arret(call: dict) -> str | None:
    """« STIF:StopArea:SP:43169: » → « 43169 »."""
    parties = [p for p in (_valeur(call.get("StopPointRef")) or "").split(":") if p]
    return parties[-1] if parties else None


def _uid_train(journey: dict, jour_prevu: datetime) -> str | None:
    """Identifiant d'incident d'un train, au format de la collecte d'avant la bascule :
    « rt_vehicle_journey:IDFM:TN:SNCF:<uuid>_AAAAMMJJ » (uuid = trip_id GTFS), jour de Paris."""
    ref = _valeur(journey.get("DatedVehicleJourneyRef"))
    if not ref:
        return None
    m = _UUID.search(ref)
    train = f"vehicle_journey:IDFM:TN:SNCF:{m.group(0)}" if m else ref
    return f"rt_{train}_{jour_prevu.astimezone(PARIS_TZ).strftime('%Y%m%d')}"


def _appels(journey: dict) -> list[dict]:
    """Arrêts d'un train dans l'ordre des heures prévues (le flux ne les ordonne pas).

    Chaque arrêt : numero, prevu (départ, ou arrivée au terminus), estime (idem),
    retard_arrivee (min, arrivée estimée − prévue ; départ au premier arrêt), supprime.
    """
    appels = []
    for c in (journey.get("EstimatedCalls") or {}).get("EstimatedCall", []):
        prevu_dep, prevu_arr = _iso(c.get("AimedDepartureTime")), _iso(c.get("AimedArrivalTime"))
        estime_dep, estime_arr = _iso(c.get("ExpectedDepartureTime")), _iso(c.get("ExpectedArrivalTime"))
        prevu = prevu_dep or prevu_arr
        if prevu is None:
            continue
        if prevu_arr and estime_arr:
            retard = _minutes(prevu_arr, estime_arr)
        elif prevu_dep and estime_dep:
            retard = _minutes(prevu_dep, estime_dep)
        else:
            retard = None
        appels.append({
            "numero": _numero_arret(c),
            "prevu": prevu,
            "estime": estime_dep or estime_arr,
            "retard_arrivee": retard,
            "supprime": STATUT_SUPPRIME in (c.get("DepartureStatus"), c.get("ArrivalStatus")),
        })
    appels.sort(key=lambda a: a["prevu"])
    return appels


def trains_du_flux(data: dict) -> list[dict]:
    """EstimatedVehicleJourney d'une réponse SIRI Estimated Timetable."""
    trains = []
    livraison = (data.get("Siri") or {}).get("ServiceDelivery") or {}
    for d in livraison.get("EstimatedTimetableDelivery") or []:
        for cadre in d.get("EstimatedJourneyVersionFrame") or []:
            trains.extend(cadre.get("EstimatedVehicleJourney") or [])
    return trains


def attentes_mesurees(trains: list[dict]) -> dict[tuple[str, str], int]:
    """Attente mesurée pour chaque arrêt supprimé : (uid-ref du train, numéro d'arrêt) → minutes.

    = heure estimée du premier train suivant du même sens (DirectionRef) qui dessert réellement cet
    arrêt, moins l'heure prévue du train supprimé. Absente si aucun train suivant n'est dans le flux.
    """
    passages: dict[tuple[str | None, str], list[datetime]] = defaultdict(list)
    appels_par_train = []
    for j in trains:
        sens = _valeur(j.get("DirectionRef"))
        appels = _appels(j)
        appels_par_train.append((j, sens, appels))
        for a in appels:
            if not a["supprime"] and a["estime"] is not None and a["numero"]:
                passages[(sens, a["numero"])].append(a["estime"])
    attentes: dict[tuple[str, str], int] = {}
    for j, sens, appels in appels_par_train:
        ref = _valeur(j.get("DatedVehicleJourneyRef")) or ""
        for a in appels:
            if not a["supprime"] or not a["numero"]:
                continue
            suivants = [t for t in passages.get((sens, a["numero"]), []) if t > a["prevu"]]
            if suivants:
                attentes[(ref, a["numero"])] = _minutes(a["prevu"], min(suivants))
    return attentes


def analyser_train(journey: dict, obs_dt: datetime, nom_arret, attentes: dict | None = None) -> dict | None:
    """Observation d'un train du flux. None si le train n'a ni retard ≥ MIN_DELAY_MINUTES ni arrêt supprimé.

    * Un arrêt supprimé (train entier, ou fin de parcours) fait du train un train supprimé : gare et
      heure prévue du premier arrêt supprimé.
    * Sinon, pire retard parmi les arrêts non supprimés, hors train fantôme (retard ≥
      GHOST_MIN_DELAY_MINUTES dont l'heure estimée colle à l'heure du relevé).
    * « arrets » : tous les arrêts du train (format de la colonne Incident.arrets), base du calcul.
    Résultat : {"uid", "supprime", "retard", "prevu", "gare", "mission", "direction", "fantome", "arrets"}.
    """
    appels = _appels(journey)
    if not appels:
        return None
    uid = _uid_train(journey, appels[0]["prevu"])
    if uid is None:
        return None
    ref = _valeur(journey.get("DatedVehicleJourneyRef")) or ""
    attentes = attentes or {}
    arrets = [{
        "g": nom_arret(a["numero"]) if a["numero"] else None,
        "p": a["prevu"].isoformat(),
        "r": a["retard_arrivee"],
        "s": a["supprime"],
        "w": attentes.get((ref, a["numero"])) if a["supprime"] else None,
    } for a in appels]
    base = {"uid": uid, "mission": _valeur(journey.get("JourneyNote")),
            "direction": _valeur(journey.get("DestinationName")), "fantome": False, "arrets": arrets}

    supprimes = [a for a in appels if a["supprime"]]
    if supprimes:
        a = supprimes[0]
        return {**base, "supprime": True, "retard": 0, "prevu": a["prevu"],
                "gare": nom_arret(a["numero"]) if a["numero"] else None}

    pire = None
    for a in appels:
        if a["estime"] is None:
            continue
        retard = _minutes(a["prevu"], a["estime"])
        if (retard >= GHOST_MIN_DELAY_MINUTES
                and abs((a["estime"] - obs_dt).total_seconds()) <= GHOST_SLIDE_TOLERANCE_MIN * 60):
            return {**base, "supprime": False, "retard": 0, "prevu": None, "gare": None, "fantome": True}
        if retard >= MIN_DELAY_MINUTES and (pire is None or retard > pire[0]):
            pire = (retard, a)
    if pire is None:
        return None
    retard, a = pire
    return {**base, "supprime": False, "retard": retard, "prevu": a["prevu"],
            "gare": nom_arret(a["numero"]) if a["numero"] else None}


def fusionner_arrets(anciens: list | None, nouveaux: list) -> list:
    """Arrêts d'un train fusionnés d'un relevé à l'autre : le flux ne montre que ~50 min de passé,
    un arrêt sorti de la fenêtre garde sa dernière mesure. Clé : (gare, heure prévue)."""
    par_cle = {(a.get("g"), a.get("p")): a for a in (anciens or [])}
    for a in nouveaux:
        precedent = par_cle.get((a.get("g"), a.get("p")))
        if precedent and a.get("r") is None:
            a = {**a, "r": precedent.get("r")}
        if precedent and a.get("w") is None:
            a = {**a, "w": precedent.get("w")}
        par_cle[(a.get("g"), a.get("p"))] = a
    return sorted(par_cle.values(), key=lambda a: a.get("p") or "")


def couverture_releve(trains: list[dict]) -> dict:
    """Ce qu'un relevé a vu : trains distincts, arrêts et plage des heures prévues (UTC)."""
    ids: set[str] = set()
    arrets = 0
    debut = fin = None
    for j in trains:
        appels = _appels(j)
        ref = _valeur(j.get("DatedVehicleJourneyRef"))
        if not appels or not ref:
            continue
        ids.add(ref)
        arrets += len(appels)
        debut = appels[0]["prevu"] if debut is None or appels[0]["prevu"] < debut else debut
        fin = appels[-1]["prevu"] if fin is None or appels[-1]["prevu"] > fin else fin
    return {"trains": len(ids), "passages": arrets, "debut": debut, "fin": fin}


def _journaliser_couverture(line_id: str, couv: dict) -> None:
    if couv["debut"] is None:
        logger.warning("PRIM : 0 train dans le flux temps réel de %s", line_id)
        return
    d, f = couv["debut"].astimezone(PARIS_TZ), couv["fin"].astimezone(PARIS_TZ)
    logger.info("Couverture %s : %d trains, %d arrêts, horaires prévus %s → %s",
                line_id, couv["trains"], couv["passages"], d.strftime("%H:%M"), f.strftime("%H:%M"))


async def collect_rt_delays() -> None:
    """Retards et trains supprimés, depuis le flux SIRI Estimated Timetable (un appel par ligne)."""
    from backend.offre import nom_arret   # import local : offre.py importe LIGNES_CIBLES d'ici

    settings = get_settings()
    if not settings.prim_api_key:
        logger.warning("PRIM_API_KEY not set — skipping RT collection")
        return

    headers = {"apikey": settings.prim_api_key}
    observations: dict[str, tuple[str, dict]] = {}   # uid → (line_id, observation)
    ghosts = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for navitia_id, line_id in LIGNES_CIBLES.items():
            code = navitia_id.removeprefix("line:IDFM:")
            try:
                resp = await client.get(PRIM_ET_URL, headers=headers,
                                        params={"LineRef": f"STIF:Line::{code}:"})
                _suivre_quota(resp, "et")
                resp.raise_for_status()
                trains = trains_du_flux(resp.json())
            except httpx.HTTPError as exc:
                logger.error("PRIM RT error for %s: %s", line_id, exc)
                continue
            except Exception as exc:
                logger.error("Unexpected RT error for %s: %s", line_id, exc)
                continue

            obs_dt = datetime.now(timezone.utc)
            _journaliser_couverture(line_id, couverture_releve(trains))
            attentes = attentes_mesurees(trains)
            for j in trains:
                obs = analyser_train(j, obs_dt, nom_arret, attentes)
                if obs is None:
                    continue
                if obs["fantome"]:
                    ghosts += 1
                    logger.warning("Train fantôme écarté : %s %s", line_id, obs["uid"])
                    continue
                observations[obs["uid"]] = (line_id, obs)

    nb_supprimes = sum(1 for _, o in observations.values() if o["supprime"])
    logger.info("Fetched %d RT delays, %d cancelled trains from PRIM (%d trains fantômes écartés)",
                len(observations) - nb_supprimes, nb_supprimes, ghosts)
    _journaliser_quota()

    now = datetime.now(timezone.utc)
    cancel_impact = getattr(settings, "cancel_default_impact_minutes", CANCEL_DEFAULT_IMPACT_MIN)

    async with AsyncSessionLocal() as session:
        # Arrêts déjà en base, à fusionner avec ceux du relevé
        anciens: dict[str, list | None] = {}
        if observations:
            rows = await session.execute(
                select(Incident.navitia_id, Incident.arrets).where(Incident.navitia_id.in_(list(observations)))
            )
            anciens = {nid: arr for nid, arr in rows.all()}

        for uid, (line_id, o) in observations.items():
            arrets = fusionner_arrets(anciens.get(uid), o["arrets"])
            if o["supprime"]:
                cause = f"Train supprimé à partir de {o['gare']}" if o["gare"] else "Train supprimé"
                duree, type_incident = cancel_impact, "CANCELLED"
            else:
                cause = f"Retard de {o['retard']} min à {o['gare']}" if o["gare"] else f"Retard de {o['retard']} min (temps réel)"
                duree, type_incident = o["retard"], "DELAY_REALTIME"
            stmt = insert(Incident).values(
                navitia_id=uid,
                line_id=line_id,
                type_incident=type_incident,
                cause=cause,
                heure_debut=now,
                heure_fin=now + timedelta(minutes=duree),
                duree_minutes=duree,
                source="realtime",
                heure_theorique=o["prevu"],
                is_cancelled=o["supprime"],
                gare=o["gare"],
                direction=o["direction"],
                mission=o["mission"],
                arrets=arrets,
                created_at=now,
                updated_at=now,
            )
            ex = stmt.excluded
            if o["supprime"]:
                # La suppression l'emporte sur un retard observé plus tôt
                set_ = {c: getattr(ex, c) for c in ("type_incident", "cause", "duree_minutes", "heure_fin",
                                                    "heure_theorique", "is_cancelled", "gare")}
            else:
                # Pire retard observé du train sur l'ensemble des relevés. Un train qui n'a plus
                # aucun arrêt supprimé dans le flux n'est plus un train supprimé.
                remplace = (ex.duree_minutes >= Incident.duree_minutes) | Incident.is_cancelled.is_(True)
                set_ = {
                    "duree_minutes": case((Incident.is_cancelled.is_(True), ex.duree_minutes),
                                          else_=func.greatest(Incident.duree_minutes, ex.duree_minutes)),
                    **{c: case((remplace, getattr(ex, c)), else_=getattr(Incident, c))
                       for c in ("cause", "heure_theorique", "gare")},
                    "heure_fin": ex.heure_fin,
                    "type_incident": "DELAY_REALTIME",
                    "is_cancelled": False,
                }
            set_.update({"direction": ex.direction, "mission": ex.mission, "arrets": ex.arrets,
                         "source": "realtime", "updated_at": now})
            await session.execute(stmt.on_conflict_do_update(index_elements=["navitia_id"], set_=set_))

        await session.commit()

    logger.info("Upserted %d RT incidents (%d cancelled)", len(observations), nb_supprimes)
