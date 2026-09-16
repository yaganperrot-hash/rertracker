"""
frequentation.py — Voyageurs montant dans un train, par ligne, gare, jour type et heure.

Deux usages bien séparés, comme `profils.py` et `offre.py` :
  * hors ligne, `python -m backend.frequentation build` assemble les données ouvertes et écrit
    `data/frequentation_gares.json` (versionné) — à lancer après `python -m backend.offre build` ;
  * à l'exécution, le backend ne lit que ce fichier.

Sources, par ordre de préférence pour chaque gare d'une ligne :
  1. Comptages SNCF (`comptage-voyageurs-trains-transilien`, SNCF Open Data) : voyageurs montés dans
     les trains de la ligne, correspondances comprises, par gare, jour type (JOB, SAM, DIM, hors
     vacances et travaux) et tranche horaire (5 tranches). Répartis heure par heure selon le profil de
     validations de la gare, sur les heures où la ligne a des départs.
  2. Validations IDFM (`validations-reseau-ferre-*-3eme-trimestre`) pour les gares non comptées (partie
     RATP des RER A et B, gares partagées ou récentes) : validations moyennes du jour type, partagées
     entre les lignes suivies au prorata de leurs départs, puis profil horaire de la gare. Une validation
     est une entrée dans le réseau : les correspondances sans valideur n'y sont pas.
Jours de vacances scolaires : les comptages sont hors vacances ; on applique le rapport mesuré, sur les
validations du réseau, entre jours de vacances et jours ordinaires.

Montées dans un train = voyageurs montés à la gare pendant l'heure ÷ départs de la ligne à cette gare
pendant l'heure (offre GTFS, deux sens confondus).
Invariant : Σ_h montées_train × départs = montées du jour à la gare (heures avec départs).
"""
import json
import re
import statistics
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import httpx

from backend import offre
from backend.profils import (
    CAT_DIMANCHE, CAT_SAMEDI, CAT_SAMEDI_VAC, CAT_SEMAINE, CAT_SEMAINE_VAC, CATEGORIES, DS_PROFILS, DS_VOLUMES,
    LIGNE_RESEAU, _export, _heure, categorie_jour, charger as charger_profils,
)

CHEMIN = Path(__file__).parent.parent / "data" / "frequentation_gares.json"

SNCF_OPENDATA = "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets"
DS_COMPTAGES = "comptage-voyageurs-trains-transilien"

# Ligne interne → lettre des comptages SNCF
LETTRE: dict[str, str] = {ligne: ligne.rsplit("_", 1)[1] for ligne in LIGNE_RESEAU}

TRANCHES: dict[str, range] = {
    "Avant 6h": range(0, 6),
    "De 6h à 10h": range(6, 10),
    "De 10h à 16h": range(10, 16),
    "De 16h à 20h": range(16, 20),
    "Après 20h": range(20, 24),
}

# Jour type du calcul → (jour type des comptages, jour type ordinaire dont il est la version vacances)
JOUR_COMPTAGE: dict[str, tuple[str, str | None]] = {
    CAT_SEMAINE: ("JOB", None),
    CAT_SEMAINE_VAC: ("JOB", CAT_SEMAINE),
    CAT_SAMEDI: ("SAM", None),
    CAT_SAMEDI_VAC: ("SAM", CAT_SAMEDI),
    CAT_DIMANCHE: ("DIM", None),
}

_MOTS_VIDES = {"PARIS", "GARE", "DE", "DU", "DES", "D", "LA", "LE", "L", "LES", "ET", "AEROPORT"}
_ALIAS = {"CHARLES": "CDG", "GAULLE": ""}


# ─────────────────────────── Lecture ───────────────────────────

_cache: dict | None = None


def charger() -> dict:
    """Contenu de data/frequentation_gares.json, lu une seule fois ({} si absent ou illisible)."""
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CHEMIN.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def montees_train(line_id: str, gare: str, quand: datetime) -> float | None:
    """Voyageurs qui montent dans un train de la ligne à `gare`, à l'heure de `quand` (Paris). None si inconnu."""
    serie = charger().get("montees_train", {}).get(line_id, {}).get(categorie_jour(quand.date()), {}).get(gare)
    return serie[quand.hour] if serie and len(serie) == 24 else None


def montees_jour(line_id: str, gare: str, quand: datetime) -> float | None:
    """Voyageurs montés à `gare` sur la ligne, le jour type de `quand`. None si inconnu."""
    return charger().get("montees_jour", {}).get(line_id, {}).get(categorie_jour(quand.date()), {}).get(gare)


# ─────────────────────────── Construction ───────────────────────────

def jetons(nom: str) -> frozenset[str]:
    """Nom de gare → mots significatifs, sans accents ni mots vides.
    « PARIS-GARE-DU-NORD » et « Gare du Nord » donnent le même ensemble."""
    brut = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().upper()
    mots = (_ALIAS.get(m, m) for m in re.split(r"[^A-Z0-9]+", brut))
    return frozenset(m for m in mots if m and m not in _MOTS_VIDES)


def _nombre(valeur) -> float | None:
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None   # « NON DEFINI », « Moins de 5 »…


def comptages_par_gare(lignes_comptages: list[dict], gares_ligne: dict[str, list[str]]) -> dict:
    """ligne → gare (nom GTFS) → jour type SNCF → tranche → (montants, année).

    Rattachement par les mots du nom. Plusieurs campagnes pour une même clé : la plus récente."""
    index = {ligne: {jetons(g): g for g in gares} for ligne, gares in gares_ligne.items()}
    lettre_ligne = {LETTRE[l]: l for l in gares_ligne if l in LETTRE}
    retenus: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    dates: dict = {}
    for r in lignes_comptages:
        ligne = lettre_ligne.get(r.get("ligne"))
        tranche = r.get("tranche_horaire")
        montants = _nombre(r.get("somme_de_montants"))
        if not ligne or tranche not in TRANCHES or montants is None:
            continue
        gare = index[ligne].get(jetons(r.get("nom_gare") or ""))
        if gare is None:
            continue
        cle = (ligne, gare, r.get("type_jour"), tranche)
        if cle in dates and dates[cle] >= (r.get("date") or ""):
            continue
        dates[cle] = r.get("date") or ""
        retenus[ligne][gare][r.get("type_jour")][tranche] = (montants, r.get("annee"))
    return retenus


def repartir(total: float, heures: range, profil: list[float] | None, departs: list[float]) -> dict[int, float]:
    """Répartit `total` sur les `heures` où la ligne a des départs, au prorata du profil horaire
    (à défaut, au prorata des départs). Rien si aucune heure n'a de départ."""
    ouvertes = [h for h in heures if departs[h] > 0]
    if not ouvertes:
        return {}
    poids = {h: (profil[h] if profil else 0.0) for h in ouvertes}
    if sum(poids.values()) <= 0:
        poids = {h: departs[h] for h in ouvertes}
    somme = sum(poids.values())
    return {h: total * p / somme for h, p in poids.items()}


def zdc_par_nom(gare: str, reseau: str | None, noms_validations: dict) -> str | None:
    """Gare dont l'identifiant GTFS n'existe pas dans les validations (ex. Châtelet - Les Halles :
    474151 dans le GTFS, 71264 « CHATELET » dans les validations) : rattachement par le nom, dans le
    réseau de la ligne de préférence. Tous les mots du libellé (abrégé) doivent figurer dans le nom."""
    mots = jetons(gare)
    candidats = [(res == reseau, len(jetons(lib)), z) for (res, z), lib in noms_validations.items()
                 if jetons(lib) and jetons(lib) <= mots]
    # Réseau de la ligne d'abord (Châtelet n'est publié que sous le réseau du RER A, pas du B)
    return max(candidats)[2] if candidats else None


def assembler(offre_c: dict, profils_c: dict, lignes_comptages: list[dict],
              validations: dict, profils_gares: dict, rapports_vacances: dict,
              noms_validations: dict | None = None) -> dict:
    """Tables finales à partir de données déjà téléchargées (fonction pure, testée).

    validations : (réseau, id_zdc) → jour type → validations moyennes par jour
    profils_gares : (réseau, id_zdc) → jour type → 24 parts
    rapports_vacances : réseau → jour type vacances → rapport au jour type ordinaire
    """
    missions = offre_c.get("missions", {})
    gares_ligne = {l: sorted({g for suite in m.values() for g in suite}) for l, m in missions.items()}
    comptes = comptages_par_gare(lignes_comptages, gares_ligne)
    zdc = offre_c.get("zdc", {})
    departs_gare = offre_c.get("trains_gare", {})

    montees_t: dict = defaultdict(lambda: defaultdict(dict))
    montees_j: dict = defaultdict(lambda: defaultdict(dict))
    origine: dict = defaultdict(dict)
    perdus: dict[str, float] = defaultdict(float)

    for ligne, gares in sorted(gares_ligne.items()):
        reseau = LIGNE_RESEAU.get(ligne)
        for cat in CATEGORIES:
            jour_sncf, ordinaire = JOUR_COMPTAGE[cat]
            facteur = rapports_vacances.get(reseau, {}).get(cat, 1.0) if ordinaire else 1.0
            for gare in gares:
                departs = departs_gare.get(ligne, {}).get(cat, {}).get(gare)
                if not departs or sum(departs) <= 0:
                    continue
                id_zdc = zdc.get(gare)
                profil = profils_gares.get((reseau, id_zdc), {}).get(cat) \
                    or profils_c.get("profils", {}).get(reseau, {}).get(cat)
                heures: dict[int, float] = defaultdict(float)

                par_tranche = comptes.get(ligne, {}).get(gare, {}).get(jour_sncf)
                if par_tranche:
                    annees = sorted({a for _, a in par_tranche.values() if a})
                    origine[ligne][gare] = f"comptage SNCF {'/'.join(annees)}"
                    for tranche, (montants, _) in par_tranche.items():
                        reparti = repartir(montants * facteur, TRANCHES[tranche], profil, departs)
                        if not reparti and not ordinaire:   # jours de vacances : mêmes comptages, déjà signalés
                            perdus[ligne] += montants
                        for h, v in reparti.items():
                            heures[h] += v
                else:
                    # Validations de la gare (toutes lignes suivies du réseau confondues), part de la ligne
                    total = sum(v.get(cat, 0.0) for (res, z), v in validations.items() if z == id_zdc and id_zdc)
                    if total <= 0:
                        id_zdc = zdc_par_nom(gare, reseau, noms_validations or {})
                        total = sum(v.get(cat, 0.0) for (res, z), v in validations.items() if z == id_zdc and id_zdc)
                        profil = profils_gares.get((reseau, id_zdc), {}).get(cat) or profil
                    if total <= 0:
                        origine[ligne].setdefault(gare, "inconnue")
                        continue
                    toutes = sum(sum(departs_gare.get(l, {}).get(cat, {}).get(gare) or [0.0])
                                 for l in departs_gare)
                    part = sum(departs) / toutes if toutes else 1.0
                    origine[ligne][gare] = "validations IDFM 2025 T3"
                    for h, v in repartir(total * part, range(24), profil, departs).items():
                        heures[h] += v

                montees_j[ligne][cat][gare] = round(sum(heures.values()), 1)
                montees_t[ligne][cat][gare] = [
                    round(heures[h] / departs[h], 2) if departs[h] > 0 else 0.0 for h in range(24)
                ]

    return {
        "montees_train": montees_t,
        "montees_jour": montees_j,
        "origine": origine,
        "perdus": {l: round(v) for l, v in perdus.items() if v},
    }


def _telecharger_validations(client: httpx.Client) -> tuple[dict, dict, dict, dict]:
    """(validations moyennes par (réseau, zdc) et jour type, profils horaires par (réseau, zdc),
    rapports vacances / ordinaire par réseau, libellés par (réseau, zdc)), sur le 3e trimestre publié."""
    noms: dict = {}
    validations: dict = defaultdict(dict)
    profils_gares: dict = defaultdict(dict)
    rapports: dict = {}
    for reseau in sorted(set(LIGNE_RESEAU.values())):
        par_zdc_date: dict = defaultdict(lambda: defaultdict(float))
        for r in _export(client, DS_VOLUMES, f'code_stif_res="{reseau}"', "jour,id_zdc,libelle_arret,nb_vald"):
            v = _nombre(r.get("nb_vald"))
            if v is None or not r.get("id_zdc") or not r.get("jour"):
                continue
            noms[(reseau, r["id_zdc"])] = r.get("libelle_arret") or ""
            par_zdc_date[r["id_zdc"]][r["jour"][:10]] += v
        dates_cat: dict = defaultdict(set)
        total_date: dict = defaultdict(float)
        for z, jours in par_zdc_date.items():
            for j, v in jours.items():
                dates_cat[categorie_jour(date.fromisoformat(j))].add(j)
                total_date[j] += v
        for z, jours in par_zdc_date.items():
            for cat, dates in dates_cat.items():
                validations[(reseau, z)][cat] = sum(jours.get(j, 0.0) for j in dates) / len(dates)
        moyenne = {cat: statistics.mean(total_date[j] for j in dates) for cat, dates in dates_cat.items()}
        rapports[reseau] = {
            vac: moyenne[vac] / moyenne[ordi]
            for vac, ordi in ((CAT_SEMAINE_VAC, CAT_SEMAINE), (CAT_SAMEDI_VAC, CAT_SAMEDI))
            if moyenne.get(vac) and moyenne.get(ordi)
        }

        cumul: dict = defaultdict(lambda: defaultdict(lambda: [0.0] * 24))
        for r in _export(client, DS_PROFILS, f'code_stif_res="{reseau}"',
                         "id_zdc,cat_jour,trnc_horr_60,pourcentage_validations"):
            h = _heure(r.get("trnc_horr_60"))
            v = _nombre(r.get("pourcentage_validations"))
            if h is None or v is None or not r.get("id_zdc"):
                continue
            cumul[r["id_zdc"]][r["cat_jour"]][h] += v
        for z, cats in cumul.items():
            for cat, serie in cats.items():
                total = sum(serie)
                if total > 0:
                    profils_gares[(reseau, z)][cat] = [v / total for v in serie]
    return validations, profils_gares, rapports, noms


def build() -> None:
    offre_c = offre.charger()
    if not offre_c.get("trains_gare"):
        raise SystemExit("data/offre_theorique.json sans départs par gare : lancer d'abord python -m backend.offre build")
    with httpx.Client() as client:
        print("Comptages SNCF…", flush=True)
        r = client.get(f"{SNCF_OPENDATA}/{DS_COMPTAGES}/exports/json", timeout=300.0)
        r.raise_for_status()
        comptages = r.json()
        print("Validations IDFM par gare…", flush=True)
        validations, profils_gares, rapports, noms = _telecharger_validations(client)

    tables = assembler(offre_c, charger_profils(), comptages, validations, profils_gares, rapports, noms)
    contenu = {
        "_source": {
            "jeux": [f"{DS_COMPTAGES} (SNCF Open Data)", f"{DS_VOLUMES} (IDFM)", f"{DS_PROFILS} (IDFM)",
                     f"{offre.DS_GTFS} (IDFM, départs par gare)"],
            "genere_le": date.today().isoformat(),
            "rapports_vacances": {res: {c: round(v, 3) for c, v in r.items()} for res, r in rapports.items()},
            "methode": "montées comptées (SNCF) ou validations (IDFM) par gare et heure ÷ départs de la ligne",
        },
        **tables,
    }
    lignes = [f" {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
              for k, v in contenu.items()]
    CHEMIN.write_text("{\n" + ",\n".join(lignes) + "\n}\n", encoding="utf-8")
    global _cache
    _cache = None

    print(f"\n{'ligne':14}{'montées JOHV':>14}{'SAHV':>10}{'DIJFP':>10}   gares comptées / validations / inconnues")
    for ligne in sorted(tables["montees_jour"]):
        mj = tables["montees_jour"][ligne]
        orig = list(tables["origine"][ligne].values())
        print(f"{ligne:14}{sum(mj.get(CAT_SEMAINE, {}).values()):14,.0f}{sum(mj.get(CAT_SAMEDI, {}).values()):10,.0f}"
              f"{sum(mj.get(CAT_DIMANCHE, {}).values()):10,.0f}   "
              f"{sum(o.startswith('comptage') for o in orig)} / {sum(o.startswith('validations') for o in orig)} / "
              f"{orig.count('inconnue')}")
    if tables["perdus"]:
        print("Montants sans départ dans leur tranche (non répartis) :", tables["perdus"])
    print(f"\n{CHEMIN} écrit")


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "build":
        build()
    else:
        print("usage : python -m backend.frequentation build")


if __name__ == "__main__":
    main()
