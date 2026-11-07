"""
periodes.py — Agrégats d'une période (semaine, mois) pour les bilans publiables du dimanche.

Semaine : du lundi au dimanche de publication. Mois : du 1er au dernier dimanche du mois (jour de publication) ;
les jours qui suivent ce dimanche n'entrent dans aucun bilan mensuel (choix assumé, 2026-11-07).
Même règle de coût que le reste du site : arrondi par ligne × jour de daily_metrics, puis sommé.
Aucun jour antérieur à debut_donnees_fiables n'est compté.
"""
from datetime import date, timedelta

from backend.collector import LIGNES_CIBLES
from backend.metrics import cout_eur, premier_jour_affiche

LIGNES = set(LIGNES_CIBLES.values())


def semaine_de(dimanche: date) -> tuple[date, date]:
    """Lundi → dimanche de la semaine qui se termine `dimanche`."""
    if dimanche.weekday() != 6:
        raise ValueError(f"{dimanche} n'est pas un dimanche")
    return dimanche - timedelta(days=6), dimanche


def est_dernier_dimanche(jour: date) -> bool:
    return jour.weekday() == 6 and (jour + timedelta(days=7)).month != jour.month


def mois_de(dimanche: date) -> tuple[date, date]:
    """Du 1er du mois au dernier dimanche `dimanche`."""
    if not est_dernier_dimanche(dimanche):
        raise ValueError(f"{dimanche} n'est pas le dernier dimanche du mois")
    return dimanche.replace(day=1), dimanche


def agreger(rows, du: date, au: date, smic_horaire: float, trains_prevus=None) -> dict:
    """Totaux et détail par ligne de daily_metrics entre du et au inclus.

    trains_prevus(line_id, jour) -> float | None : offre théorique d'un jour ; sommée sur les jours comptés.
    `du` est ramené au début des données fiables ; `du_effectif` le dit.
    """
    du_eff = premier_jour_affiche(du)
    par_ligne: dict[str, dict] = {}
    for r in rows:
        if r.line_id not in LIGNES or not du_eff <= r.date <= au:
            continue
        l = par_ligne.setdefault(r.line_id, {
            "line_id": r.line_id, "nb_rt_delays": 0, "nb_cancelled": 0, "nb_incidents": 0,
            "minutes_voyageurs": 0, "cout_eur": 0, "jours_perturbes": 0,
        })
        l["nb_rt_delays"] += r.nb_rt_delays or 0
        l["nb_cancelled"] += r.nb_cancelled or 0
        l["nb_incidents"] += r.nb_incidents or 0
        l["minutes_voyageurs"] += r.minutes_voyageurs or 0
        l["cout_eur"] += cout_eur(r.minutes_voyageurs or 0, smic_horaire)
        l["jours_perturbes"] += 1 if r.est_jour_perturbe else 0

    jours = [du_eff + timedelta(days=i) for i in range((au - du_eff).days + 1)]
    for l in par_ligne.values():
        prevus = [trains_prevus(l["line_id"], j) for j in jours] if trains_prevus else []
        l["trains_prevus"] = round(sum(prevus)) if prevus and None not in prevus else None

    lignes = sorted(par_ligne.values(), key=lambda l: (-l["minutes_voyageurs"], l["line_id"]))
    return {
        "du": du.isoformat(),
        "au": au.isoformat(),
        "du_effectif": du_eff.isoformat(),
        "nb_jours": len(jours),
        "total_incidents": sum(l["nb_incidents"] for l in lignes),
        "total_minutes_voyageurs": sum(l["minutes_voyageurs"] for l in lignes),
        "cout_eur": sum(l["cout_eur"] for l in lignes),
        "nb_lignes_perturbees": sum(1 for l in lignes if l["jours_perturbes"]),
        "lignes": lignes,
    }


def trains_prevus_offre(line_id: str, jour: date) -> float | None:
    """Trains prévus un jour donné (offre théorique GTFS par jour type), comme /api/stats/today/lines."""
    from backend.metrics import OFFRE
    from backend.profils import categorie_jour
    return OFFRE.get("trains_jour", {}).get(line_id, {}).get(categorie_jour(jour))


def evolution_pct(actuel: int, precedent: int | None) -> int | None:
    """Écart en % arrondi à l'unité ; None sans base de comparaison."""
    if not precedent:
        return None
    return round((actuel - precedent) * 100 / precedent)
