"""
offre.py — Offre théorique des lignes (horaires prévus GTFS d'Île-de-France Mobilités).

Deux usages bien séparés, comme `profils.py` :
  * hors ligne, `python -m backend.offre build` télécharge le GTFS open data et écrit
    `data/offre_theorique.json` (versionné, à régénérer avec les profils) ;
  * à l'exécution, le backend ne lit que ce fichier — aucun appel réseau, aucun quota PRIM.

Trains équivalents de l'heure h, pour une ligne et une date : Σ sur les trains du jour de
(arrêts du train dont le départ prévu tombe dans h) ÷ (arrêts du train). Un train de 7 h 50 à
8 h 30 dont la moitié des arrêts précède 8 h compte 0,5 à 7 h et 0,5 à 8 h.
Invariant : la somme des 24 heures vaut le nombre de trains du jour. Les voyageurs qui montent
pendant h se répartissent sur les trains qui desservent des gares pendant h ; diviser les
voyageurs de l'heure par ce nombre donne des voyageurs par train dont la somme sur tous les
trains redonne les voyageurs du jour.

Intervalle de l'heure h : pour chaque couple (gare, sens) desservi pendant h, nombre moyen de
départs dans l'heure n, soit un intervalle de 60 ÷ n ; on retient la médiane de ces intervalles
pondérée par les départs (une gare du tronc commun pèse plus qu'un terminus de branche), bornée
à 60 min. C'est l'attente du train suivant pour un voyageur dont le train est supprimé.

Fenêtre : les dates du GTFS où circule au moins la moitié du nombre médian de trains. Les bords
de fenêtre publiés partiellement (services commencés avant la date de publication) sont écartés.

Départs par gare (trains_gare) : nombre moyen de trains de la ligne au départ de chaque gare,
deux sens confondus, par jour type et par heure. Il divise les voyageurs montés à la gare pendant
l'heure (backend/frequentation.py) pour obtenir les montées dans un train.

Missions : suite ordonnée des gares de chaque code mission (la variante la plus fréquente), qui
reconstitue le parcours d'un train relevé avant que le détail arrêt par arrêt ne soit enregistré.

Les correspondances d'identifiants ont été vérifiées sur les données (2026-09-16) :
route_id GTFS = ligne PRIM sans « line: », trip_id GTFS = vehicle_journey PRIM sans
« vehicle_journey: », trip_headsign = code mission, stop_name = nom de gare PRIM.
"""
import csv
import io
import json
import statistics
import sys
import tempfile
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from backend.collector import LIGNES_CIBLES
from backend.profils import CAT_SAMEDI, CAT_SAMEDI_VAC, CAT_SEMAINE, CAT_SEMAINE_VAC, CATEGORIES, categorie_jour

GTFS_URL = ("https://data.iledefrance-mobilites.fr/explore/dataset/offre-horaires-tc-gtfs-idfm/"
            "files/a925e164271e4bca93433756d6a340d1/download/")
DS_GTFS = "offre-horaires-tc-gtfs-idfm"

CHEMIN = Path(__file__).parent.parent / "data" / "offre_theorique.json"

INTERVALLE_MAX_MIN = 60.0
PART_MIN_DATE = 0.5   # une date du GTFS est retenue si elle compte au moins cette part du nombre médian de trains

# Jour type absent de la fenêtre GTFS (30 jours) → jour type dont on reprend l'offre
REPLIS = {CAT_SEMAINE_VAC: CAT_SEMAINE, CAT_SAMEDI_VAC: CAT_SAMEDI}

# Ligne interne → route_id GTFS, dérivé des identifiants PRIM vérifiés du collecteur
LIGNE_ROUTE: dict[str, str] = {ligne: nav.removeprefix("line:") for nav, ligne in LIGNES_CIBLES.items()}


# ─────────────────────────── Lecture ───────────────────────────

_cache: dict | None = None


def charger() -> dict:
    """Contenu de data/offre_theorique.json, lu une seule fois ({} si absent ou illisible)."""
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CHEMIN.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def _valeur(table: str, line_id: str, quand: datetime) -> float | None:
    serie = charger().get(table, {}).get(line_id, {}).get(categorie_jour(quand.date()))
    if not serie or len(serie) != 24:
        return None
    return serie[quand.hour]


def trains_heure(line_id: str, quand: datetime) -> float | None:
    """Trains équivalents de la ligne pendant l'heure de `quand` (heure de Paris). None si inconnu."""
    return _valeur("trains_heure", line_id, quand)


def intervalle_min(line_id: str, quand: datetime) -> float | None:
    """Intervalle médian entre deux trains à l'heure de `quand` (heure de Paris). None si inconnu."""
    return _valeur("intervalle_min", line_id, quand)


def trains_gare(line_id: str, gare: str, quand: datetime) -> float | None:
    """Trains de la ligne au départ de `gare` pendant l'heure de `quand` (deux sens). None si inconnu."""
    serie = charger().get("trains_gare", {}).get(line_id, {}).get(categorie_jour(quand.date()), {}).get(gare)
    return serie[quand.hour] if serie and len(serie) == 24 else None


def parcours_mission(line_id: str, mission: str | None, gare: str | None = None) -> list[str] | None:
    """Gares de la mission, dans l'ordre. Mission inconnue : la mission la plus fréquente qui dessert
    `gare`, sinon la mission la plus fréquente de la ligne. None si la ligne est inconnue."""
    c = charger()
    missions = c.get("missions", {}).get(line_id, {})
    if mission in missions:
        return missions[mission]
    repli = c.get("mission_par_gare", {}).get(line_id, {}).get(gare or "") or \
        c.get("mission_principale", {}).get(line_id)
    return missions.get(repli) if repli else None


# ─────────────────────────── Construction ───────────────────────────

def _lire(z: zipfile.ZipFile, nom: str) -> Iterator[dict]:
    """Lignes d'un fichier du GTFS, lues en flux (stop_times.txt dépasse 700 Mo)."""
    with z.open(nom) as brut:
        yield from csv.DictReader(io.TextIOWrapper(brut, encoding="utf-8-sig", newline=""))


def _heure(hhmmss: str) -> int:
    """« 25:10:00 » → 1 : au-delà de 24 h, l'heure appartient au jour de service de la veille."""
    return int(hhmmss.split(":", 1)[0]) % 24


def _date(aaaammjj: str) -> date:
    return datetime.strptime(aaaammjj, "%Y%m%d").date()


def jours_actifs(z: zipfile.ZipFile) -> dict[str, set[date]]:
    """Dates de circulation de chaque service_id : calendar.txt puis exceptions de calendar_dates.txt."""
    noms = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    jours: dict[str, set[date]] = defaultdict(set)
    if "calendar.txt" in z.namelist():
        for r in _lire(z, "calendar.txt"):
            d, fin = _date(r["start_date"]), _date(r["end_date"])
            while d <= fin:
                if r[noms[d.weekday()]] == "1":
                    jours[r["service_id"]].add(d)
                d += timedelta(days=1)
    if "calendar_dates.txt" in z.namelist():
        for r in _lire(z, "calendar_dates.txt"):
            d = _date(r["date"])
            if r["exception_type"] == "1":
                jours[r["service_id"]].add(d)
            elif r["exception_type"] == "2":
                jours[r["service_id"]].discard(d)
    return jours


def trains_des_lignes(z: zipfile.ZipFile) -> dict[str, dict]:
    """trip_id → {ligne, service, mission, sens} pour les trains des lignes suivies."""
    route_ligne = {route: ligne for ligne, route in LIGNE_ROUTE.items()}
    trains = {}
    for r in _lire(z, "trips.txt"):
        ligne = route_ligne.get(r["route_id"])
        if ligne:
            trains[r["trip_id"]] = {"ligne": ligne, "service": r["service_id"],
                                    "mission": r.get("trip_headsign") or "", "sens": r.get("direction_id") or ""}
    return trains


def arrets(z: zipfile.ZipFile) -> dict[str, tuple[str, str]]:
    """stop_id → (gare parente, nom de la gare). Un arrêt sans parent est sa propre gare."""
    bruts = {r["stop_id"]: (r.get("parent_station") or "", r["stop_name"]) for r in _lire(z, "stops.txt")}
    resultat = {}
    for stop_id, (parent, nom) in bruts.items():
        gare = parent or stop_id
        resultat[stop_id] = (gare, bruts.get(gare, ("", nom))[1])
    return resultat


def dessertes(z: zipfile.ZipFile, trip_ids: set[str]) -> dict[str, list[tuple[int, str, str]]]:
    """trip_id → [(ordre, heure de départ prévue « HH:MM:SS », stop_id)] triés dans l'ordre du parcours."""
    resultat: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for r in _lire(z, "stop_times.txt"):
        if r["trip_id"] in trip_ids:
            resultat[r["trip_id"]].append((int(r["stop_sequence"]), r["departure_time"], r["stop_id"]))
    for liste in resultat.values():
        liste.sort()
    return resultat


def mediane_ponderee(valeurs_poids: list[tuple[float, float]]) -> float:
    """Plus petite valeur dont le poids cumulé atteint la moitié du poids total."""
    ordonnees = sorted(valeurs_poids)
    total = sum(p for _, p in ordonnees)
    cumul = 0.0
    for valeur, poids in ordonnees:
        cumul += poids
        if cumul >= total / 2:
            return valeur
    raise ValueError("liste vide")


PREFIXE_ARRET = "IDFM:monomodalStopPlace:"


def noms_arrets(trains: dict[str, dict], gares: dict[str, tuple[str, str]],
                parcours: dict[str, list[tuple[int, str, str]]]) -> dict[str, str]:
    """Numéro d'arrêt → nom de la gare, pour les arrêts desservis par les lignes suivies.

    Le flux SIRI de PRIM désigne un arrêt par « STIF:StopArea:SP:43169: » ; le GTFS par
    « IDFM:monomodalStopPlace:43169 ». Le nom est celui de la gare parente, clé de toutes les tables.
    """
    noms: dict[str, str] = {}
    for trip_id in trains:
        for _, _, stop_id in parcours.get(trip_id, ()):
            if stop_id.startswith(PREFIXE_ARRET):
                noms[stop_id.removeprefix(PREFIXE_ARRET)] = gares.get(stop_id, ("", stop_id))[1]
    return dict(sorted(noms.items()))


def nom_arret(numero: str) -> str | None:
    """Nom de la gare d'un numéro d'arrêt SIRI (voir noms_arrets). None si inconnu."""
    return charger().get("arrets", {}).get(numero)


def missions_des_lignes(trains: dict[str, dict], gares: dict[str, tuple[str, str]],
                        parcours: dict[str, list[tuple[int, str, str]]]) -> tuple[dict, dict, dict]:
    """(ligne → mission → gares ordonnées, ligne → gare → mission la plus fréquente qui la dessert,
    ligne → mission la plus fréquente). Parmi les variantes d'un code mission, la plus fréquente fait foi."""
    suites: dict[tuple[str, str], dict[tuple, int]] = defaultdict(lambda: defaultdict(int))
    for trip_id, t in trains.items():
        desserte = parcours.get(trip_id)
        if not desserte or not t["mission"]:
            continue
        suite: list[str] = []
        for _, _, stop_id in desserte:
            nom = gares.get(stop_id, (stop_id, stop_id))[1]
            if not suite or suite[-1] != nom:
                suite.append(nom)
        suites[(t["ligne"], t["mission"])][tuple(suite)] += 1

    missions: dict[str, dict[str, list[str]]] = defaultdict(dict)
    frequence: dict[str, dict[str, int]] = defaultdict(dict)
    for (ligne, mission), variantes in sorted(suites.items()):
        suite, _ = max(variantes.items(), key=lambda kv: (kv[1], kv[0]))
        missions[ligne][mission] = list(suite)
        frequence[ligne][mission] = sum(variantes.values())

    par_gare: dict[str, dict[str, str]] = defaultdict(dict)
    principale: dict[str, str] = {}
    for ligne, freq in frequence.items():
        ordre = sorted(freq, key=lambda m: (-freq[m], m))
        principale[ligne] = ordre[0]
        for mission in reversed(ordre):   # la plus fréquente écrit en dernier
            for gare in missions[ligne][mission]:
                par_gare[ligne][gare] = mission
    return dict(missions), {l: dict(sorted(g.items())) for l, g in par_gare.items()}, principale


def agreger(chemin_zip: Path | str) -> dict:
    """Trains équivalents, trains du jour, intervalles et départs par gare, par ligne × jour type × heure ;
    noms des arrêts SIRI, missions et identifiant de validations (id_zdc) de chaque gare."""
    with zipfile.ZipFile(chemin_zip) as z:
        jours = jours_actifs(z)
        trains = trains_des_lignes(z)
        gares = arrets(z)
        parcours = dessertes(z, set(trains))

    # Fenêtre : dates suffisamment complètes (voir docstring) ; nombre de dates par jour type
    trains_par_date: dict[date, int] = defaultdict(int)
    for trip_id, t in trains.items():
        if trip_id in parcours:
            for d in jours.get(t["service"], ()):
                trains_par_date[d] += 1
    if not trains_par_date:
        raise RuntimeError("aucun train des lignes suivies dans le GTFS")
    seuil = PART_MIN_DATE * statistics.median(trains_par_date.values())
    fenetre = sorted(d for d, n in trains_par_date.items() if n >= seuil)
    retenues = set(fenetre)
    dates_par_cat: dict[str, int] = defaultdict(int)
    for d in fenetre:
        dates_par_cat[categorie_jour(d)] += 1

    trains_h = defaultdict(lambda: [0.0] * 24)        # (ligne, cat) → somme sur les dates
    trains_j = defaultdict(float)                     # (ligne, cat) → somme sur les dates
    departs = defaultdict(float)                      # (ligne, cat, gare, sens, h) → somme sur les dates

    for trip_id, t in trains.items():
        desserte = parcours.get(trip_id)
        if not desserte:
            continue
        # Dates de circulation du train, comptées par jour type
        par_cat: dict[str, int] = defaultdict(int)
        for d in jours.get(t["service"], ()):
            if d in retenues:
                par_cat[categorie_jour(d)] += 1
        if not par_cat:
            continue
        heures = [_heure(dep) for _, dep, _ in desserte]
        n = len(heures)
        for cat, nb in par_cat.items():
            cle = (t["ligne"], cat)
            trains_j[cle] += nb
            for h in heures:
                trains_h[cle][h] += nb / n
            for h, (_, _, stop_id) in zip(heures, desserte):
                gare = gares.get(stop_id, (stop_id, ""))[0]
                departs[(t["ligne"], cat, gare, t["sens"], h)] += nb

    # Par ligne × jour type × heure : (intervalle, départs) de chaque couple (gare, sens)
    par_heure: dict[tuple[str, str, int], list[tuple[float, float]]] = defaultdict(list)
    for (ligne, cat, _gare, _sens, h), somme in departs.items():
        n = somme / dates_par_cat[cat]
        par_heure[(ligne, cat, h)].append((min(60 / n, INTERVALLE_MAX_MIN), n))

    resultat_trains: dict[str, dict[str, list[float]]] = defaultdict(dict)
    resultat_jour: dict[str, dict[str, float]] = defaultdict(dict)
    resultat_intervalle: dict[str, dict[str, list[float | None]]] = defaultdict(dict)
    resultat_gares: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(dict)
    nom_gare = {gare: nom for gare, nom in gares.values()}
    departs_gare: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0.0] * 24)
    for (ligne, cat, gare, _sens, h), somme in departs.items():
        departs_gare[(ligne, cat, nom_gare.get(gare, gare))][h] += somme
    for ligne in LIGNE_ROUTE:
        for cat in CATEGORIES:
            nb_dates = dates_par_cat.get(cat, 0)
            if nb_dates == 0:
                continue   # jour type absent de la fenêtre : repli plus bas
            # Jour type présent mais sans train sur la ligne : des zéros, pas un repli
            resultat_trains[ligne][cat] = [round(v / nb_dates, 2) for v in trains_h[(ligne, cat)]]
            resultat_jour[ligne][cat] = round(trains_j[(ligne, cat)] / nb_dates, 2)
            serie: list[float | None] = []
            for h in range(24):
                valeurs = par_heure.get((ligne, cat, h))
                if not valeurs:
                    serie.append(None)
                else:
                    serie.append(round(mediane_ponderee(valeurs), 1))
            resultat_intervalle[ligne][cat] = serie
            resultat_gares[ligne][cat] = {
                g: [round(v / nb_dates, 2) for v in serie_g]
                for (l, c, g), serie_g in sorted(departs_gare.items()) if l == ligne and c == cat
            }

    replis: dict[str, str] = {}
    for ligne in LIGNE_ROUTE:
        if not any(ligne == l for l, _ in trains_j):
            raise RuntimeError(f"aucun train pour {ligne} dans le GTFS")
        for cat in CATEGORIES:
            if cat in resultat_trains[ligne]:
                continue
            source = REPLIS.get(cat)
            if source is None or source not in resultat_trains[ligne]:
                raise RuntimeError(f"jour type {cat} absent du GTFS pour {ligne}, sans repli possible")
            resultat_trains[ligne][cat] = resultat_trains[ligne][source]
            resultat_jour[ligne][cat] = resultat_jour[ligne][source]
            resultat_intervalle[ligne][cat] = resultat_intervalle[ligne][source]
            resultat_gares[ligne][cat] = resultat_gares[ligne][source]
            replis[cat] = source

    contenu = {
        "_source": {
            "portail": "data.iledefrance-mobilites.fr",
            "jeu": DS_GTFS,
            "genere_le": date.today().isoformat(),
            "fenetre": [fenetre[0].isoformat(), fenetre[-1].isoformat()],
            "replis": replis,
            "methode": "trains équivalents : part des arrêts du train dans l'heure ; intervalle : médiane, "
                       "pondérée par les départs, de 60 ÷ départs par heure de chaque gare et sens, bornée à 60 min",
        },
        "lignes": LIGNE_ROUTE,
        "trains_jour": resultat_jour,
        "trains_heure": resultat_trains,
        "intervalle_min": resultat_intervalle,
    }
    contenu["trains_gare"] = resultat_gares
    contenu["arrets"] = noms_arrets(trains, gares, parcours)
    contenu["missions"], contenu["mission_par_gare"], contenu["mission_principale"] = \
        missions_des_lignes(trains, gares, parcours)
    # Gare → id_zdc des jeux de validations : l'arrêt parent GTFS « IDFM:71517 » porte l'id_zdc 71517
    utilisees = {nom for suites in contenu["missions"].values() for suite in suites.values() for nom in suite}
    contenu["zdc"] = dict(sorted({nom: gare.removeprefix("IDFM:") for gare, nom in gares.values()
                                  if nom in utilisees and gare.removeprefix("IDFM:").isdigit()}.items()))
    return contenu


def telecharger(destination: Path) -> None:
    with httpx.stream("GET", GTFS_URL, follow_redirects=True, timeout=600.0) as r:
        r.raise_for_status()
        with open(destination, "wb") as f:
            for bloc in r.iter_bytes(1 << 20):
                f.write(bloc)


def build() -> None:
    with tempfile.TemporaryDirectory() as dossier:
        chemin_zip = Path(dossier) / "gtfs.zip"
        print("Téléchargement du GTFS IDFM…", flush=True)
        telecharger(chemin_zip)
        print("Agrégation…", flush=True)
        contenu = agreger(chemin_zip)

    # Une table par ligne du fichier : lisible dans un diff sans exploser en milliers de lignes
    lignes = [f" {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
              for k, v in contenu.items()]
    CHEMIN.write_text("{\n" + ",\n".join(lignes) + "\n}\n", encoding="utf-8")
    global _cache
    _cache = None
    src = contenu["_source"]
    print(f"Fenêtre {src['fenetre'][0]} → {src['fenetre'][1]} · replis : {src['replis'] or 'aucun'}")
    for ligne in LIGNE_ROUTE:
        print(f"    {ligne:14} {contenu['trains_jour'][ligne][CAT_SEMAINE]:7.1f} trains/jour · "
              f"8 h : {contenu['trains_heure'][ligne][CAT_SEMAINE][8]:5.1f} trains, "
              f"intervalle {contenu['intervalle_min'][ligne][CAT_SEMAINE][8]} min")
    print(f"\n{CHEMIN} écrit")


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "build":
        build()
    else:
        print("usage : python -m backend.offre build")


if __name__ == "__main__":
    main()
