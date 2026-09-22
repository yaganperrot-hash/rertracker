import asyncio
import gzip
import json
import logging
import re
import shutil
from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.models import Incident

logger = logging.getLogger(__name__)

PRIM_BASE_URL = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia"
# Flux SIRI Estimated Timetable, arrêt par arrêt, suppressions comprises. Interrogé pour tout le réseau d'un coup
# (LineRef=ALL, ~4 h 30 d'horizon) : 1 requête par relevé au lieu d'une par ligne (13), même compteur de quota.
PRIM_ET_URL = "https://prim.iledefrance-mobilites.fr/marketplace/estimated-timetable"
REQUETES_ET_PAR_RELEVE = 1

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

            # Ignorer les incidents de nuit (avant le début de la journée comptée, heure de Paris)
            paris_hour = heure_debut.astimezone(ZoneInfo("Europe/Paris")).hour
            if paris_hour < get_settings().collecte_heure_debut:
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

# Un arrêt n'est mesuré (retard, suppression) que si son passage est estimé dans moins de FENETRE_MESURE_MINUTES
# au relevé, ou déjà passé : une annonce faite des heures à l'avance (retard rattrapé, suppression levée) n'est
# pas une mesure. Avec un relevé toutes les 5 min, chaque arrêt est vu au moins deux fois dans la fenêtre
# (10 min avant le passage, ~3 min après : durée de passé visible dans le flux).
FENETRE_MESURE_MINUTES = 10

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


def attentes_mesurees(trains: list[dict], obs_dt: datetime | None = None) -> dict[tuple[str, str], int]:
    """Attente mesurée pour chaque arrêt supprimé : (uid-ref du train, numéro d'arrêt) → minutes.

    = heure estimée du premier train suivant du même sens (DirectionRef) qui dessert réellement cet
    arrêt, moins l'heure prévue du train supprimé. Absente si aucun train suivant n'est dans le flux.

    Mesurée seulement pour un arrêt dont l'heure prévue n'est pas passée au relevé : le flux retire
    les arrêts peu après le passage du train, un train passé entre l'heure prévue et le relevé serait
    invisible et l'attente fausse.
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
            # Arrêt déjà passé au relevé : le train suivant a pu disparaître du flux
            if obs_dt is not None and a["prevu"] < obs_dt:
                continue
            suivants = [t for t in passages.get((sens, a["numero"]), []) if t > a["prevu"]]
            if suivants:
                attentes[(ref, a["numero"])] = _minutes(a["prevu"], min(suivants))
    return attentes


def ecarts_train_suivant(trains: list[dict], obs_dt: datetime) -> dict[tuple[str, str], dict[str, int]]:
    """Écarts mesurés avec le train suivant : (uid-ref du train, numéro d'arrêt de montée i) →
    {numéro d'arrêt de descente j: minutes}. Minutes = passage en i du premier AUTRE train du même sens qui
    dessert i puis j, moins l'heure prévue du train en i. C'est ce que perd au plus un voyageur i → j à quai
    à l'heure prévue quand son train passe plus tard : il peut prendre ce train-là. Par destination, car
    un train d'une autre branche ne sert à rien au voyageur.

    Mesuré seulement pour un arrêt dont l'heure prévue n'est pas passée au relevé : le flux retire un arrêt
    peu après le passage du train, un train passé entre l'heure prévue et le relevé serait invisible et l'écart
    faux. Un arrêt mesuré sans train suivant visible vers j n'a pas d'entrée j (aucun gain possible).
    """
    trains_par_sens: dict[str | None, list[tuple[str, dict[str, datetime]]]] = defaultdict(list)
    appels_par_train = []
    for jr in trains:
        sens = _valeur(jr.get("DirectionRef"))
        ref = _valeur(jr.get("DatedVehicleJourneyRef")) or ""
        appels = _appels(jr)
        appels_par_train.append((ref, sens, appels))
        desservis = {a["numero"]: a["estime"] for a in appels
                     if not a["supprime"] and a["estime"] is not None and a["numero"]}
        trains_par_sens[sens].append((ref, desservis))
    ecarts: dict[tuple[str, str], dict[str, int]] = {}
    for ref, sens, appels in appels_par_train:
        for i, a in enumerate(appels):
            if a["supprime"] or not a["numero"] or a["prevu"] < obs_dt:
                continue
            candidats = sorted(((d[a["numero"]], d) for autre, d in trains_par_sens[sens]
                                if autre != ref and a["numero"] in d and d[a["numero"]] > a["prevu"]),
                               key=lambda c: c[0])
            par_destination: dict[str, int] = {}
            for b in appels[i + 1:]:
                if not b["numero"]:
                    continue
                for passage, d in candidats:
                    if b["numero"] in d and d[b["numero"]] > passage:
                        par_destination[b["numero"]] = _minutes(a["prevu"], passage)
                        break
            ecarts[(ref, a["numero"])] = par_destination
    return ecarts


def _ecarts_par_gare(ecarts: dict[str, int] | None, nom_arret) -> dict[str, int] | None:
    """{numéro d'arrêt: minutes} → {nom de gare: minutes} ; None si l'arrêt n'a pas été mesuré."""
    if ecarts is None:
        return None
    return {nom: m for numero, m in ecarts.items() if (nom := nom_arret(numero))}


def _dans_la_fenetre(appel: dict, obs_dt: datetime) -> bool:
    """Passage de l'arrêt estimé (prévu, si supprimé ou sans estimation) dans moins de FENETRE_MESURE_MINUTES,
    ou déjà passé."""
    return (appel["estime"] or appel["prevu"]) <= obs_dt + timedelta(minutes=FENETRE_MESURE_MINUTES)


def analyser_train(journey: dict, obs_dt: datetime, nom_arret, attentes: dict | None = None,
                   ecarts: dict | None = None, suivi: bool = False) -> dict | None:
    """Observation d'un train du flux. None si le train n'a ni retard ≥ MIN_DELAY_MINUTES ni arrêt supprimé
    (sauf `suivi` : l'observation est rendue quand même, avec retard 0, pour mettre à jour un train déjà en base).

    Seuls les arrêts dans la fenêtre de mesure (voir FENETRE_MESURE_MINUTES) comptent : retard et suppression
    d'un arrêt plus lointain ne sont ni relevés (r None, s False) ni retenus pour le train.

    * Un arrêt supprimé (train entier, ou fin de parcours) fait du train un train supprimé : gare et
      heure prévue du premier arrêt supprimé.
    * Sinon, pire retard parmi les arrêts non supprimés, hors train fantôme (retard ≥
      GHOST_MIN_DELAY_MINUTES dont l'heure estimée colle à l'heure du relevé).
    * « arrets » : tous les arrêts du train (format de la colonne Incident.arrets), base du calcul.
      r : retard à l'arrivée ; s : supprimé ; w : attente mesurée (arrêt supprimé) ;
      a : écarts mesurés avec le train suivant, par gare de descente (arrêt desservi, voir ecarts_train_suivant).
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
    ecarts = ecarts or {}
    proches = [_dans_la_fenetre(a, obs_dt) for a in appels]
    arrets = [{
        "g": nom_arret(a["numero"]) if a["numero"] else None,
        "p": a["prevu"].isoformat(),
        "r": a["retard_arrivee"] if proche else None,
        "s": a["supprime"] if proche else None,
        "w": attentes.get((ref, a["numero"])) if a["supprime"] and proche else None,
        "a": _ecarts_par_gare(ecarts.get((ref, a["numero"])), nom_arret) if not a["supprime"] else None,
    } for a, proche in zip(appels, proches)]
    base = {"uid": uid, "mission": _valeur(journey.get("JourneyNote")),
            "direction": _valeur(journey.get("DestinationName")), "fantome": False, "arrets": arrets}

    supprimes = [a for a, proche in zip(appels, proches) if a["supprime"] and proche]
    if supprimes:
        a = supprimes[0]
        return {**base, "supprime": True, "retard": 0, "prevu": a["prevu"],
                "gare": nom_arret(a["numero"]) if a["numero"] else None}

    pire = None
    for a, proche in zip(appels, proches):
        if a["estime"] is None:
            continue
        retard = _minutes(a["prevu"], a["estime"])
        if (retard >= GHOST_MIN_DELAY_MINUTES
                and abs((a["estime"] - obs_dt).total_seconds()) <= GHOST_SLIDE_TOLERANCE_MIN * 60):
            return {**base, "supprime": False, "retard": 0, "prevu": None, "gare": None, "fantome": True}
        if proche and retard >= MIN_DELAY_MINUTES and (pire is None or retard > pire[0]):
            pire = (retard, a)
    if pire is None:
        return {**base, "supprime": False, "retard": 0, "prevu": None, "gare": None} if suivi else None
    retard, a = pire
    return {**base, "supprime": False, "retard": retard, "prevu": a["prevu"],
            "gare": nom_arret(a["numero"]) if a["numero"] else None}


def fusionner_arrets(anciens: list | None, nouveaux: list) -> list:
    """Arrêts d'un train fusionnés d'un relevé à l'autre : le flux retire les arrêts passés
    (quelques minutes après le passage), un arrêt sorti garde sa dernière mesure. Clé : (gare, heure prévue)."""
    par_cle = {(a.get("g"), a.get("p")): a for a in (anciens or [])}
    for a in nouveaux:
        precedent = par_cle.get((a.get("g"), a.get("p")))
        for champ in ("r", "s", "w", "a", "k"):
            if precedent and a.get(champ) is None and precedent.get(champ) is not None:
                a = {**a, champ: precedent[champ]}
        par_cle[(a.get("g"), a.get("p"))] = a
    return sorted(par_cle.values(), key=lambda a: a.get("p") or "")


# Relevé précédent de chaque ligne, en mémoire : line_id → (instant, {uid-ref: [(numéro, heure prévue, supprimé)]})
_releves_precedents: dict[str, tuple[datetime, dict[str, list[tuple[str | None, datetime, bool]]]]] = {}
ECART_MAX_RELEVES = timedelta(minutes=45)   # au-delà (nuit, serveur arrêté), pas de comparaison


def resume_releve(trains: list[dict]) -> dict[str, list[tuple[str | None, datetime, bool]]]:
    """Ce qu'il faut garder d'un relevé pour le comparer au suivant : arrêts de chaque train."""
    return {ref: [(a["numero"], a["prevu"], a["supprime"]) for a in _appels(j)]
            for j in trains if (ref := _valeur(j.get("DatedVehicleJourneyRef")))}


def arrets_sautes(precedent: dict[str, list[tuple[str | None, datetime, bool]]],
                  trains: list[dict]) -> list[tuple[str, str, datetime]]:
    """Arrêts sautés probables (soupçon B, en observation) : (uid-ref, numéro d'arrêt, heure prévue).

    Un arrêt desservi au relevé précédent qui disparaît du flux alors qu'un arrêt prévu AVANT lui sur le même train
    est encore visible : le train n'y est pas encore passé (le flux retire les arrêts dans l'ordre du parcours),
    l'arrêt a été retiré de sa desserte. Un train sorti du flux n'est pas comparé.
    """
    sautes = []
    for j in trains:
        ref = _valeur(j.get("DatedVehicleJourneyRef"))
        if not ref or ref not in precedent:
            continue
        appels = _appels(j)
        visibles = {a["numero"] for a in appels}
        if not appels:
            continue
        premier_visible = appels[0]["prevu"]
        for numero, prevu, supprime in precedent[ref]:
            if numero and not supprime and numero not in visibles and prevu > premier_visible:
                sautes.append((ref, numero, prevu))
    return sautes


def marquer_sautes(arrets: list, sautes: list[tuple[str, str]]) -> list:
    """« k » : arrêt sauté probable, sur les arrêts déjà connus du train (clé gare + heure prévue). En observation :
    le calcul ne le lit pas encore, et un arrêt absent de `arrets` n'y est pas ajouté."""
    cles = set(sautes)
    return [{**a, "k": True} if (a.get("g"), a.get("p")) in cles else a for a in arrets]


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


ARCHIVE_FLUX_DIR = Path(__file__).resolve().parent.parent / "logs" / "flux_brut"


def archiver_flux(line_id: str, contenu: bytes, instant: datetime, jours: int,
                  racine: Path = ARCHIVE_FLUX_DIR) -> Path | None:
    """Réponse brute du flux Estimated Timetable, gzippée : <racine>/AAAA-MM-JJ/HHMMSS-<ligne>.json.gz
    (heure de Paris). Vérité terrain pour rejouer un relevé ; aucune requête PRIM en plus.
    Les dossiers de plus de `jours` jours sont supprimés. Une erreur d'écriture ne bloque jamais la collecte."""
    if not isinstance(jours, int) or isinstance(jours, bool) or jours <= 0:
        return None
    paris = instant.astimezone(PARIS_TZ)
    try:
        dossier = racine / paris.date().isoformat()
        dossier.mkdir(parents=True, exist_ok=True)
        chemin = dossier / f"{paris.strftime('%H%M%S')}-{line_id}.json.gz"
        chemin.write_bytes(gzip.compress(contenu))
        limite = paris.date() - timedelta(days=jours)
        for ancien in racine.iterdir():
            try:
                jour = date.fromisoformat(ancien.name)
            except ValueError:
                continue
            if ancien.is_dir() and jour < limite:
                shutil.rmtree(ancien)
        return chemin
    except OSError as exc:
        logger.warning("Archive du flux brut impossible pour %s : %s", line_id, exc)
        return None


def _journaliser_couverture(line_id: str, couv: dict) -> None:
    if couv["debut"] is None:
        logger.warning("PRIM : 0 train dans le flux temps réel de %s", line_id)
        return
    d, f = couv["debut"].astimezone(PARIS_TZ), couv["fin"].astimezone(PARIS_TZ)
    logger.info("Couverture %s : %d trains, %d arrêts, horaires prévus %s → %s",
                line_id, couv["trains"], couv["passages"], d.strftime("%H:%M"), f.strftime("%H:%M"))


def trains_par_ligne(trains: list[dict]) -> dict[str, list[dict]]:
    """Trains du flux global rangés par ligne suivie (LineRef « STIF:Line::C01742: ») ; les autres sont écartés."""
    codes = {nid.removeprefix("line:IDFM:"): lid for nid, lid in LIGNES_CIBLES.items()}
    par_ligne: dict[str, list[dict]] = defaultdict(list)
    for j in trains:
        parties = [p for p in (_valeur(j.get("LineRef")) or "").split(":") if p]
        line_id = codes.get(parties[-1]) if parties else None
        if line_id:
            par_ligne[line_id].append(j)
    return par_ligne


def trains_attendus(line_id: str, jour: date, heure_debut: int, heure_fin: int) -> list[tuple[str, str, int, int]]:
    """Trains GTFS attendus pour une ligne un jour donné entre deux heures (minutes depuis minuit).

    Retourne [(trip_uuid, mission, premier départ, dernier passage — en min), …] pour les trains dont le premier
    départ est entre heure_debut et heure_fin. Ne dépend que des données statiques.
    """
    from backend.offre import charger_horaires
    h = charger_horaires()
    if not h:
        return []
    debut = date.fromisoformat(h["debut"])
    decalage = (jour - debut).days
    ligne = h.get("lignes", {}).get(line_id)
    if not ligne:
        return []
    attendus = []
    for t in ligne["trains"]:
        trip_id, mission, service_idx, passages = t[0], t[1], t[2], t[3]
        if decalage not in h["services"][service_idx]:
            continue
        premier = passages[1] if len(passages) >= 2 else None
        if premier is not None and heure_debut <= premier < heure_fin:
            uuid = trip_id.split(":")[-1] if ":" in trip_id else trip_id
            attendus.append((uuid, mission, premier, passages[-1]))
    return attendus


def diagnostiquer_trains_manquants(line_id: str, trains: list[dict], obs_dt: datetime) -> None:
    """Compare les trains du flux aux trains GTFS attendus dans la dernière heure. Loggue les manquants.

    Diagnostic seulement (bug D) : un train absent du flux n'est pas forcément supprimé (trou PRIM).
    """
    paris = obs_dt.astimezone(PARIS_TZ)
    heure_fin = paris.hour * 60 + paris.minute
    heure_debut = heure_fin - 60
    if heure_debut < 0:
        return  # pas de comparaison autour de minuit
    attendus = trains_attendus(line_id, paris.date(), heure_debut, heure_fin)
    if not attendus:
        return
    # UUIDs des trains dans le flux
    vus: set[str] = set()
    for j in trains:
        ref = _valeur(j.get("DatedVehicleJourneyRef")) or ""
        m = _UUID.search(ref)
        if m:
            vus.add(m.group(0))
    # Aucun train du flux dans le GTFS : ce sont les horaires qui sont périmés (IDFM renouvelle les trip_id à chaque
    # publication — 2026-09-22), pas des trains absents. « Mon trajet » ne relie alors plus aucun incident.
    from backend.offre import charger_horaires
    connus = {m.group(0) for t in charger_horaires()["lignes"][line_id]["trains"] if (m := _UUID.search(t[0]))}
    if vus and not vus & connus:
        logger.warning("Horaires GTFS périmés pour %s : aucun des %d trains du flux n'y figure — "
                       "reconstruire avec « python -m backend.offre horaires »", line_id, len(vus))
        return
    # Un train arrivé au terminus quitte le flux quelques minutes après (bug C) : seuls ceux encore en
    # circulation au relevé doivent y figurer
    attendus = [a for a in attendus if a[3] >= heure_fin]
    manquants = [(uuid, mission, premier) for uuid, mission, premier, _ in attendus if uuid not in vus]
    if manquants:
        h_m = lambda m: f"{m // 60}:{m % 60:02d}"
        logger.info("Trains GTFS absents du flux %s (%d/%d en circulation, partis dans l'heure) : %s",
                    line_id, len(manquants), len(attendus),
                    ", ".join(f"{mission} {h_m(premier)}" for _, mission, premier in manquants[:10])
                    + (f" … +{len(manquants) - 10}" if len(manquants) > 10 else ""))


def flux_siri(trains: list[dict]) -> dict:
    """Réponse SIRI Estimated Timetable réduite à ces trains (archive par ligne, relisible par trains_du_flux)."""
    return {"Siri": {"ServiceDelivery": {"EstimatedTimetableDelivery": [
        {"EstimatedJourneyVersionFrame": [{"EstimatedVehicleJourney": trains}]}]}}}


async def dernier_releve(source: str) -> datetime | None:
    """Dernière écriture en base d'une source (« realtime », « disruption ») : sert à ne pas refaire un relevé
    tout juste fait quand le serveur redémarre."""
    async with AsyncSessionLocal() as session:
        return (await session.execute(
            select(func.max(Incident.updated_at)).where(Incident.source == source))).scalar()


async def collect_rt_delays() -> None:
    """Retards et trains supprimés, depuis le flux SIRI Estimated Timetable : un seul appel pour tout le réseau
    (LineRef=ALL : ~4,5 Mo compressés, ~50 Mo de JSON, mesuré le 2026-09-17), filtré sur les lignes suivies."""
    from backend.offre import nom_arret   # import local : offre.py importe LIGNES_CIBLES d'ici

    settings = get_settings()
    if not settings.prim_api_key:
        logger.warning("PRIM_API_KEY not set — skipping RT collection")
        return

    headers = {"apikey": settings.prim_api_key}
    observations: dict[str, tuple[str, dict]] = {}   # uid → (line_id, observation)
    ghosts = 0

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(PRIM_ET_URL, headers=headers, params={"LineRef": "ALL"})
        _suivre_quota(resp, "et")
        resp.raise_for_status()
        # ~50 Mo de JSON : lu hors de la boucle d'événements, le site reste servi pendant ce temps
        tous = trains_du_flux(await asyncio.to_thread(json.loads, resp.content))
    except httpx.HTTPError as exc:
        logger.error("PRIM RT error (flux global) : %s", exc)
        _journaliser_quota()
        return
    except Exception as exc:
        logger.error("Unexpected RT error (flux global) : %s", exc)
        _journaliser_quota()
        return
    obs_dt = datetime.now(timezone.utc)
    if not tous:
        logger.warning("PRIM : 0 train dans le flux temps réel global")
    par_ligne = trains_par_ligne(tous)
    del tous

    for line_id in LIGNES_CIBLES.values():
        trains = par_ligne.get(line_id, [])
        archiver_flux(line_id, json.dumps(flux_siri(trains)).encode("utf-8"), obs_dt,
                      getattr(settings, "archive_flux_jours", 0))
        _journaliser_couverture(line_id, couverture_releve(trains))
        try:
            diagnostiquer_trains_manquants(line_id, trains, obs_dt)
        except Exception:
            logger.exception("Diagnostic trains manquants impossible pour %s", line_id)
        attentes = attentes_mesurees(trains, obs_dt)
        try:
            ecarts = ecarts_train_suivant(trains, obs_dt)
        except Exception:
            # Mesure d'appoint : son échec ne doit jamais perdre le relevé (repli sur l'offre prévue)
            logger.exception("Écarts avec le train suivant non mesurés pour %s", line_id)
            ecarts = {}
        sautes: dict[str, list[tuple[str, str]]] = defaultdict(list)   # uid-ref → [(gare, heure prévue ISO)]
        precedent = _releves_precedents.get(line_id)
        try:
            if precedent and obs_dt - precedent[0] <= ECART_MAX_RELEVES:
                for ref, numero, prevu in arrets_sautes(precedent[1], trains):
                    gare = nom_arret(numero) or numero
                    sautes[ref].append((gare, prevu.isoformat()))
                    logger.info("Arrêt sauté probable : %s %s %s (prévu %s)", line_id, ref, gare,
                                prevu.astimezone(PARIS_TZ).strftime("%H:%M"))
            _releves_precedents[line_id] = (obs_dt, resume_releve(trains))
        except Exception:
            # Observation seulement : jamais au prix du relevé
            logger.exception("Détection des arrêts sautés impossible pour %s", line_id)
        for j in trains:
            # suivi=True : un train sans retard dans la fenêtre est gardé pour mettre à jour ses arrêts s'il est
            # déjà en base (retard rattrapé : l'arrêt mesuré plus tôt reçoit sa dernière mesure)
            obs = analyser_train(j, obs_dt, nom_arret, attentes, ecarts, suivi=True)
            if obs is None:
                continue
            if obs["fantome"]:
                ghosts += 1
                logger.warning("Train fantôme écarté : %s %s", line_id, obs["uid"])
                continue
            obs["sautes"] = sautes.get(_valeur(j.get("DatedVehicleJourneyRef")) or "", [])
            observations[obs["uid"]] = (line_id, obs)

    nb_supprimes = sum(1 for _, o in observations.values() if o["supprime"])
    nb_retards = sum(1 for _, o in observations.values() if not o["supprime"] and o["retard"] > 0)
    logger.info("Fetched %d RT delays, %d cancelled trains from PRIM (%d trains fantômes écartés)",
                nb_retards, nb_supprimes, ghosts)
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

        suivis = 0
        for uid, (line_id, o) in observations.items():
            arrets = marquer_sautes(fusionner_arrets(anciens.get(uid), o["arrets"]), o.get("sautes", []))
            if not o["supprime"] and o["retard"] <= 0:
                # Aucun retard dans la fenêtre : seulement la mise à jour des arrêts d'un train déjà en base
                if uid in anciens:
                    await session.execute(update(Incident).where(Incident.navitia_id == uid).values(
                        arrets=arrets, direction=o["direction"], mission=o["mission"], updated_at=now))
                    suivis += 1
                continue
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
                # Pire retard observé du train sur l'ensemble des relevés. is_cancelled préservé :
                # les arrêts supprimés sortent de la fenêtre de mesure avant la fin du relevé,
                # l'absence de suppression visible ne signifie pas que la suppression n'a pas eu lieu.
                remplace = (ex.duree_minutes >= Incident.duree_minutes) | Incident.is_cancelled.is_(True)
                set_ = {
                    "duree_minutes": case((Incident.is_cancelled.is_(True), ex.duree_minutes),
                                          else_=func.greatest(Incident.duree_minutes, ex.duree_minutes)),
                    **{c: case((remplace, getattr(ex, c)), else_=getattr(Incident, c))
                       for c in ("cause", "heure_theorique", "gare")},
                    "heure_fin": ex.heure_fin,
                    "type_incident": "DELAY_REALTIME",
                    "is_cancelled": Incident.is_cancelled,
                }
            set_.update({"direction": ex.direction, "mission": ex.mission, "arrets": ex.arrets,
                         "source": "realtime", "updated_at": now})
            await session.execute(stmt.on_conflict_do_update(index_elements=["navitia_id"], set_=set_))

        await session.commit()

    logger.info("Upserted %d RT incidents (%d cancelled), %d trains déjà en base mis à jour sans retard",
                nb_retards + nb_supprimes, nb_supprimes, suivis)
