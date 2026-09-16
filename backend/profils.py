"""
profils.py — Profils horaires de fréquentation, construits depuis les validations open data
d'Île-de-France Mobilités.

Deux usages bien séparés :
  * hors ligne, `python -m backend.profils build` interroge le portail open data et écrit
    `data/profils_horaires.json` (versionné, à régénérer quand IDFM publie un nouveau trimestre) ;
  * à l'exécution, le backend ne lit que ce fichier — aucun appel réseau, aucun quota consommé.

Les données open data sont par arrêt et par « réseau » (code_stif_res), jamais par ligne :
les cinq RER ont chacun leur réseau, les huit lignes Transilien se partagent cinq réseaux
regroupés par gare parisienne. Le regroupement est explicite dans LIGNE_RESEAU, et reporté
tel quel dans le JSON pour rester auditable.

Réserve de méthode : une validation est une entrée dans le réseau, pas un voyageur à bord.
Le profil décrit où et quand les voyageurs embarquent — bon indicateur du flux, pas de la charge.
"""
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

OPENDATA = "https://data.iledefrance-mobilites.fr/api/explore/v2.1/catalog/datasets"
DS_PROFILS = "validations-reseau-ferre-profils-horaires-par-jour-type-3eme-trimestre"
DS_VOLUMES = "validations-reseau-ferre-nombre-validations-par-jour-3eme-trimestre"

CHEMIN = Path(__file__).parent.parent / "data" / "profils_horaires.json"

# Ligne → code_stif_res. Plusieurs lignes peuvent partager un réseau (cf. docstring).
LIGNE_RESEAU: dict[str, str] = {
    "RER_A": "801",
    "RER_B": "802",
    "RER_C": "803",
    "RER_D": "804",
    "RER_E": "805",
    "TRANSILIEN_P": "850",              # Paris-Est
    "TRANSILIEN_R": "851",              # Paris-Lyon
    "TRANSILIEN_N": "852", "TRANSILIEN_U": "852",   # Montparnasse
    "TRANSILIEN_H": "853", "TRANSILIEN_K": "853",   # Paris-Nord
    "TRANSILIEN_J": "854", "TRANSILIEN_L": "854",   # Saint-Lazare
}

RESEAU_LIBELLE: dict[str, str] = {
    "801": "RER A", "802": "RER B", "803": "RER C", "804": "RER D", "805": "RER E",
    "850": "Transilien Paris-Est", "851": "Transilien Paris-Lyon",
    "852": "Transilien Montparnasse", "853": "Transilien Paris-Nord",
    "854": "Transilien Saint-Lazare",
}

# Jours types du jeu de données. On en retient trois : les vacances scolaires (JOVS, SAVS)
# demanderaient le calendrier scolaire — limite documentée sur la page Méthode.
CAT_SEMAINE, CAT_SAMEDI, CAT_DIMANCHE = "JOHV", "SAHV", "DIJFP"
CATEGORIES = (CAT_SEMAINE, CAT_SAMEDI, CAT_DIMANCHE)

_TRANCHE = re.compile(r"^(\d{1,2})H-")


def _heure(tranche: str | None) -> int | None:
    """« 8H-9H » → 8. « ND » et tout format inattendu → None."""
    m = _TRANCHE.match(tranche or "")
    if not m:
        return None
    h = int(m.group(1))
    return h if 0 <= h <= 23 else None


# ─────────────────────────── Jours fériés ───────────────────────────

def _paques(annee: int) -> date:
    """Dimanche de Pâques (algorithme de Meeus/Jones/Butcher, calendrier grégorien)."""
    a, b, c = annee % 19, annee // 100, annee % 100
    d, e = b // 4, b % 4
    f, g = (b + 8) // 25, (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mois = (h + l - 7 * m + 114) // 31
    jour = ((h + l - 7 * m + 114) % 31) + 1
    return date(annee, mois, jour)


def feries(annee: int) -> set[date]:
    """Les 11 jours fériés français d'une année."""
    p = _paques(annee)
    return {
        date(annee, 1, 1), date(annee, 5, 1), date(annee, 5, 8),
        date(annee, 7, 14), date(annee, 8, 15), date(annee, 11, 1),
        date(annee, 11, 11), date(annee, 12, 25),
        p + timedelta(days=1),    # lundi de Pâques
        p + timedelta(days=39),   # Ascension
        p + timedelta(days=50),   # lundi de Pentecôte
    }


def categorie_jour(jour: date) -> str:
    """Jour type d'une date : semaine, samedi, ou dimanche et fériés."""
    if jour in feries(jour.year):
        return CAT_DIMANCHE
    j = jour.weekday()
    if j == 6:
        return CAT_DIMANCHE
    if j == 5:
        return CAT_SAMEDI
    return CAT_SEMAINE


# ─────────────────────────── Construction ───────────────────────────

def _export(client: httpx.Client, dataset: str, where: str, select: str) -> list[dict]:
    """Export complet d'une requête open data (pas de pagination à 100 comme /records)."""
    r = client.get(
        f"{OPENDATA}/{dataset}/exports/json",
        params={"where": where, "select": select},
        timeout=180.0,
    )
    r.raise_for_status()
    return r.json()


def _volumes_par_gare(client: httpx.Client, res: str) -> dict[str, float]:
    """Validations totales du trimestre par gare (id_zdc). Sert à pondérer les profils :
    sans ça, une petite gare de grande banlieue pèserait autant qu'un nœud parisien."""
    lignes = _export(client, DS_VOLUMES, f'code_stif_res="{res}"', "id_zdc,nb_vald")
    volumes: dict[str, float] = {}
    for l in lignes:
        zdc = l.get("id_zdc")
        if not zdc:
            continue
        try:
            volumes[zdc] = volumes.get(zdc, 0.0) + float(l.get("nb_vald") or 0)
        except (TypeError, ValueError):
            continue  # « NON DEFINI » et autres valeurs non numériques
    return volumes


def _profil_reseau(client: httpx.Client, res: str, cat: str,
                   volumes: dict[str, float]) -> list[float]:
    """Profil horaire d'un réseau pour un jour type : 24 parts sommant à 1.

    Moyenne des profils de gare pondérée par le volume de chaque gare. Une gare sans volume
    connu retombe sur un poids de 1 plutôt que d'être écartée.
    """
    lignes = _export(client, DS_PROFILS, f'code_stif_res="{res}" and cat_jour="{cat}"',
                     "id_zdc,trnc_horr_60,pourcentage_validations")

    cumul = [0.0] * 24
    poids_total = 0.0
    vus: set[str] = set()

    for l in lignes:
        h = _heure(l.get("trnc_horr_60"))
        if h is None:
            continue
        zdc = l.get("id_zdc") or ""
        poids = volumes.get(zdc, 1.0)
        cumul[h] += float(l.get("pourcentage_validations") or 0.0) * poids
        if zdc not in vus:
            vus.add(zdc)
            poids_total += poids

    total = sum(cumul)
    if total <= 0:
        raise RuntimeError(f"profil vide pour le réseau {res} / {cat}")
    return [round(v / total, 6) for v in cumul]


def build() -> None:
    reseaux = sorted(set(LIGNE_RESEAU.values()))
    resultat: dict[str, dict[str, list[float]]] = {}

    with httpx.Client() as client:
        for res in reseaux:
            print(f"Réseau {res} ({RESEAU_LIBELLE.get(res, '?')}) — volumes…", flush=True)
            volumes = _volumes_par_gare(client, res)
            resultat[res] = {}
            for cat in CATEGORIES:
                profil = _profil_reseau(client, res, cat, volumes)
                resultat[res][cat] = profil
                pointe = max(range(24), key=lambda h: profil[h])
                print(f"    {cat} : {len(volumes)} gares · pointe {pointe}h "
                      f"({profil[pointe] * 100:.2f} %)", flush=True)

    contenu = {
        "_source": {
            "portail": "data.iledefrance-mobilites.fr",
            "jeux": [DS_PROFILS, DS_VOLUMES],
            "genere_le": date.today().isoformat(),
            "methode": "moyenne des profils de gare pondérée par le volume de validations",
            "reserve": "une validation est une entrée dans le réseau, pas un voyageur à bord",
        },
        "reseaux_libelles": RESEAU_LIBELLE,
        "lignes": LIGNE_RESEAU,
        "profils": resultat,
    }
    CHEMIN.write_text(json.dumps(contenu, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{CHEMIN} écrit — {len(reseaux)} réseaux × {len(CATEGORIES)} jours types")


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "build":
        build()
    else:
        print("usage : python -m backend.profils build")
        sys.exit(1)


if __name__ == "__main__":
    main()
