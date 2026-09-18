"""
trajets.py — « Mon trajet » (bêta) : temps perdu sur un trajet régulier, jour par jour.

Pour chaque jour choisi :
  * train prévu : premier train des horaires GTFS qui passe à la gare de départ à partir de l'heure
    choisie et dessert ensuite la gare d'arrivée ;
  * train pris : parmi les trains qui passent réellement à la gare de départ à partir de cette heure
    (heure prévue + retard relevé) et ne sont supprimés ni au départ ni à l'arrivée, celui qui arrive
    le premier ;
  * perte = arrivée réelle − arrivée prévue, jamais négative.

Un train absent des incidents est supposé à l'heure : retard de moins de MIN_DELAY_MINUTES, ou non vu.
Les jours sans relevé autour du trajet (serveur arrêté) ne sont pas comptés. Arrêts sautés probables
(soupçon B, en observation) : signalés ; un train dont les relevés sont physiquement incohérents (arrivée avant
départ + trajet prévu) n'est pas retenu, c'est la trace qu'un arrêt sauté laisse en base.
Lecture seule : aucune écriture en base, aucune requête PRIM.
"""
import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import offre
from backend.config import get_settings
from backend.models import Incident

PARIS_TZ = ZoneInfo("Europe/Paris")

FENETRE_AVANT_MIN = 90       # un train prévu jusqu'à 1 h 30 avant l'heure choisie peut passer en retard après
FENETRE_APRES_MIN = 180      # trains suivants examinés
MARGE_RELEVE = timedelta(minutes=30)   # un relevé à moins de 30 min du passage prévu couvre le trajet
# Un train ne rattrape pas plus que cela sur le trajet : au-delà, l'arrivée relevée est une valeur périmée,
# laissée en base par un arrêt sorti du flux avant les précédents — signature d'un arrêt sauté (soupçon B)
RATTRAPAGE_MAX = timedelta(minutes=2)
RATTRAPAGE_PART = 0.10   # … plus 10 % du temps de trajet prévu entre deux gares
PERIODE_MAX_JOURS = 60

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def arrets_releves():
    """Condition SQL : l'incident a une liste d'arrêts relevés (ni NULL, ni le JSON « null » des anciens imports)."""
    return func.jsonb_typeof(Incident.arrets) == "array"


def cle_gare(nom: str) -> str:
    """Tri et comparaison sans accents ni casse."""
    return unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()


def gares_ligne(line_id: str) -> list[str]:
    """Gares de la ligne dans les horaires, par ordre alphabétique."""
    ligne = offre.charger_horaires().get("lignes", {}).get(line_id, {})
    return sorted(ligne.get("gares", []), key=cle_gare)


def uid_incident(trip_id: str, jour: date) -> str:
    """Identifiant d'incident d'un train GTFS un jour donné (voir collector._uid_train)."""
    m = _UUID.search(trip_id)
    train = f"vehicle_journey:IDFM:TN:SNCF:{m.group(0)}" if m else f"vehicle_journey:{trip_id}"
    return f"rt_{train}_{jour.strftime('%Y%m%d')}"


def trains_du_jour(line_id: str, depart: str, arrivee: str, jour: date) -> list[dict]:
    """Trains de la ligne qui circulent `jour` et desservent `depart` puis `arrivee` :
    [{"trip_id", "mission", "depart": datetime Paris, "arrivee": datetime Paris}], triés par départ."""
    h = offre.charger_horaires()
    ligne = h.get("lignes", {}).get(line_id)
    if not ligne or not h.get("debut"):
        return []
    gares = ligne["gares"]
    try:
        i_dep, i_arr = gares.index(depart), gares.index(arrivee)
    except ValueError:
        return []
    decalage = (jour - date.fromisoformat(h["debut"])).days
    minuit = datetime.combine(jour, time(0), tzinfo=PARIS_TZ)
    resultat = []
    for trip_id, mission, service, passages in ligne["trains"]:
        if decalage not in h["services"][service]:
            continue
        m_dep = m_arr = None
        for k in range(0, len(passages), 2):
            if passages[k] == i_dep and m_dep is None:
                m_dep = passages[k + 1]
            elif passages[k] == i_arr and m_dep is not None:
                m_arr = passages[k + 1]
                break
        if m_dep is None or m_arr is None:
            continue
        # Minutes au-delà de 24 h : lendemain ; l'addition de timedelta suit le changement d'heure
        resultat.append({"trip_id": trip_id, "mission": mission,
                         "depart": (minuit.astimezone(timezone.utc) + timedelta(minutes=m_dep)).astimezone(PARIS_TZ),
                         "arrivee": (minuit.astimezone(timezone.utc) + timedelta(minutes=m_arr)).astimezone(PARIS_TZ)})
    return sorted(resultat, key=lambda t: t["depart"])


def _arret(arrets: list[dict], gare: str, prevu: datetime) -> dict:
    """Relevé de `gare` dans les arrêts d'un incident : {"reel", "supprime", "saute"}.
    Gare absente des arrêts : dernier retard connu avant elle (0 sinon)."""
    candidats = [a for a in arrets if a.get("g") == gare and a.get("p")]
    if candidats:
        a = min(candidats, key=lambda a: abs(datetime.fromisoformat(a["p"]) - prevu))
        p = datetime.fromisoformat(a["p"]).astimezone(PARIS_TZ)
        return {"reel": p + timedelta(minutes=a.get("r") or 0), "supprime": bool(a.get("s")),
                "saute": bool(a.get("k"))}
    avant = [a for a in arrets if a.get("p") and datetime.fromisoformat(a["p"]) <= prevu and a.get("r") is not None]
    retard = max(avant, key=lambda a: a["p"])["r"] if avant else 0
    return {"reel": prevu + timedelta(minutes=retard), "supprime": False, "saute": False}


def arrivee_perimee(arrets: list[dict], depart_prevu: datetime, gare_arrivee: str, arrivee_prevue: datetime) -> bool:
    """Le retard relevé à l'arrivée est-il plus faible que celui d'une gare précédente du trajet (départ compris),
    au-delà de ce qu'un train peut rattraper (RATTRAPAGE_MAX + RATTRAPAGE_PART du temps prévu entre les deux) ?
    Alors la valeur d'arrivée est périmée : l'arrêt a quitté le flux avant les précédents (arrêt sauté probable)."""
    arrivees = [a for a in arrets if a.get("g") == gare_arrivee and a.get("p") and a.get("r") is not None]
    if not arrivees:
        return False
    arr = min(arrivees, key=lambda a: abs(datetime.fromisoformat(a["p"]) - arrivee_prevue))
    p_arr = datetime.fromisoformat(arr["p"])
    for a in arrets:
        if not a.get("p") or a.get("r") is None or a.get("s"):
            continue
        p = datetime.fromisoformat(a["p"])
        if not (depart_prevu - timedelta(minutes=1) <= p < p_arr):
            continue
        marge = RATTRAPAGE_MAX + (p_arr - p) * RATTRAPAGE_PART
        if timedelta(minutes=a["r"] - arr["r"]) > marge:
            return True
    return False


def perte_du_jour(trains: list[dict], incidents: dict[str, Incident], heure: datetime) -> dict | None:
    """Train prévu, train pris et perte d'un jour. `trains` : trains_du_jour complétés de "uid", "gare_depart",
    "gare_arrivee" ; `incidents` : uid → Incident. None si aucun train prévu à partir de `heure`.

    Un train dont l'arrivée relevée précède son départ relevé + trajet prévu − RATTRAPAGE_MAX, ou dont le retard à
    l'arrivée est plus faible que celui d'une gare précédente au-delà du rattrapage possible, est incohérent :
    il n'est pas retenu et le jour est marqué « arrêt sauté probable », comme un arrêt marqué « k » au départ ou
    à l'arrivée d'un train que le voyageur aurait pu prendre (celui-ci reste retenu : soupçon B en observation).
    """
    prevus = [t for t in trains if t["depart"] >= heure]
    if not prevus:
        return None
    prevu = prevus[0]
    pris = None
    mesure = incidents.get(prevu["uid"]) is not None
    signales: list[datetime] = []   # départs réels des trains à arrêt sauté probable
    for t in trains:
        inc = incidents.get(t["uid"])
        if inc is not None and inc.arrets:
            dep, arr = _arret(inc.arrets, t["gare_depart"], t["depart"]), _arret(inc.arrets, t["gare_arrivee"], t["arrivee"])
        elif inc is not None and inc.is_cancelled:
            continue   # train supprimé sans détail d'arrêts (collecte d'avant la bascule)
        else:
            dep = {"reel": t["depart"], "supprime": False, "saute": False}
            arr = {"reel": t["arrivee"], "supprime": False, "saute": False}
        if dep["supprime"] or arr["supprime"] or dep["reel"] < heure:
            continue
        incoherent = arr["reel"] < dep["reel"] + (t["arrivee"] - t["depart"]) - RATTRAPAGE_MAX or \
            (inc is not None and bool(inc.arrets) and arrivee_perimee(inc.arrets, t["depart"], t["gare_arrivee"], t["arrivee"]))
        if incoherent:
            signales.append(heure)   # départ relevé douteux lui aussi : toujours signalé
        elif dep["saute"] or arr["saute"]:
            signales.append(dep["reel"])
        if incoherent:
            continue
        if pris is None or arr["reel"] < pris["arrivee_reelle"]:
            pris = {**t, "depart_reel": dep["reel"], "arrivee_reelle": arr["reel"], "incident": inc is not None}
    if pris is None:
        return {"prevu": prevu, "pris": None, "perte_min": None, "mesure": mesure, "saute": bool(signales)}
    perte = max(0, round((pris["arrivee_reelle"] - prevu["arrivee"]).total_seconds() / 60))
    return {"prevu": prevu, "pris": pris, "perte_min": perte, "mesure": mesure or pris["incident"],
            "saute": any(d <= pris["depart_reel"] for d in signales)}


def _heure(hhmm: str) -> tuple[int, int]:
    h, m = hhmm.split(":")
    h, m = int(h), int(m)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(hhmm)
    return h, m


async def calculer(db: AsyncSession, line_id: str, depart: str, arrivee: str, hhmm: str,
                   jours_semaine: set[int], periode: int, aujourd_hui: datetime | None = None) -> dict:
    """Détail jour par jour et totaux sur les `periode` derniers jours (jours_semaine : 1 = lundi … 7 = dimanche)."""
    maintenant = (aujourd_hui or datetime.now(timezone.utc)).astimezone(PARIS_TZ)
    h, m = _heure(hhmm)
    periode = max(1, min(periode, PERIODE_MAX_JOURS))
    horaires = offre.charger_horaires()
    fenetre = horaires.get("_source", {}).get("fenetre") or [None, None]

    mesure_depuis = (await db.execute(
        select(func.min(Incident.heure_debut)).where(arrets_releves()))).scalar()
    mesure_depuis = mesure_depuis.astimezone(PARIS_TZ) if mesure_depuis else None

    jours = [maintenant.date() - timedelta(days=k) for k in range(periode)]
    jours = [j for j in jours if j.isoweekday() in jours_semaine]

    # Trains candidats de chaque jour
    par_jour: dict[date, tuple[datetime, list[dict]]] = {}
    uids: set[str] = set()
    for jour in jours:
        heure = datetime.combine(jour, time(h, m), tzinfo=PARIS_TZ)
        trains = [t for t in trains_du_jour(line_id, depart, arrivee, jour)
                  if heure - timedelta(minutes=FENETRE_AVANT_MIN) <= t["depart"] <= heure + timedelta(minutes=FENETRE_APRES_MIN)]
        for t in trains:
            t["gare_depart"], t["gare_arrivee"] = depart, arrivee
            t["uids"] = {uid_incident(t["trip_id"], jour), uid_incident(t["trip_id"], jour + timedelta(days=1))}
            uids |= t["uids"]
        par_jour[jour] = (heure, trains)

    incidents: dict[str, Incident] = {}
    if uids:
        rows = (await db.execute(select(Incident).where(Incident.navitia_id.in_(sorted(uids))))).scalars().all()
        incidents = {i.navitia_id: i for i in rows}

    smic = get_settings().smic_horaire
    detail = []
    total = 0
    for jour in jours:
        heure, trains = par_jour[jour]
        ligne_jour = {"date": jour.isoformat(), "statut": None, "perte_min": None, "perte_eur": None,
                      "train_prevu": None, "train_pris": None, "arret_saute_probable": False}
        detail.append(ligne_jour)
        if mesure_depuis is None or jour < mesure_depuis.date() or not fenetre[0] or \
                not (fenetre[0] <= jour.isoformat() <= fenetre[1]):
            ligne_jour["statut"] = "hors_mesure"
            continue
        for t in trains:
            t["uid"] = next((u for u in sorted(t["uids"]) if u in incidents), uid_incident(t["trip_id"], jour))
        resultat = perte_du_jour(trains, incidents, heure)
        if resultat is None:
            ligne_jour["statut"] = "aucun_train"
            continue
        prevu = resultat["prevu"]
        ligne_jour["train_prevu"] = {"mission": prevu["mission"], "depart": prevu["depart"].strftime("%H:%M"),
                                     "arrivee": prevu["arrivee"].strftime("%H:%M")}
        if prevu["depart"] < mesure_depuis:
            ligne_jour["statut"] = "hors_mesure"
            continue
        if prevu["arrivee"] > maintenant:
            ligne_jour["statut"] = "a_venir"
            continue
        # Relevé arrêt par arrêt autour du trajet (l'ancienne collecte ne voyait pas les trains supprimés en route)
        couvert = (await db.execute(select(Incident.id).where(
            Incident.source == "realtime",
            arrets_releves(),
            Incident.heure_debut <= prevu["depart"] + MARGE_RELEVE,
            Incident.updated_at >= prevu["depart"] - MARGE_RELEVE).limit(1))).first()
        if couvert is None:
            ligne_jour["statut"] = "sans_releve"
            continue
        pris = resultat["pris"]
        if pris is None:
            ligne_jour["statut"] = "aucun_train_reel"
            continue
        ligne_jour["train_pris"] = {"mission": pris["mission"], "depart": pris["depart_reel"].strftime("%H:%M"),
                                    "arrivee": pris["arrivee_reelle"].strftime("%H:%M")}
        ligne_jour["statut"] = "mesure" if resultat["mesure"] else "a_l_heure"
        ligne_jour["arret_saute_probable"] = resultat["saute"]
        ligne_jour["perte_min"] = resultat["perte_min"]
        ligne_jour["perte_eur"] = round(resultat["perte_min"] * smic / 60, 2)
        total += resultat["perte_min"]

    comptes = [d for d in detail if d["perte_min"] is not None]
    return {
        "ligne": line_id, "depart": depart, "arrivee": arrivee, "heure": f"{h:02d}:{m:02d}",
        "jours_semaine": sorted(jours_semaine), "periode": periode,
        "mesure_depuis": mesure_depuis.date().isoformat() if mesure_depuis else None,
        "horaires_fenetre": fenetre,
        "smic_horaire": smic,
        "jours": detail,
        "jours_comptes": len(comptes),
        "jours_en_retard": sum(1 for d in comptes if d["perte_min"] > 0),
        "total_min": total,
        "total_eur": round(total * smic / 60, 2),
    }
