"""
bilans.py — Bilans des pages /statistiques (7 et 30 jours glissants) et /annee.

Recalculés toutes les 10 min et écrits en JSON statique dans frontend/data/ : aucune requête base
par visiteur. Source unique : daily_metrics, la table que lit aussi l'accueil.

Cohérence : le coût est arrondi une fois par ligne de daily_metrics (une ligne × un jour), puis
additionné. Tout total affiché est donc exactement la somme de son détail (lignes, mois).
"""
import json
import logging
import math
import os
from calendar import monthrange
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.causes import CATEGORIES, NON_PRECISE, categoriser_cause
from backend.collector import LIGNES_CIBLES
from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.metrics import PARIS_TZ, cout_eur, debut_journee, journee_de, premier_jour_affiche  # cout_eur : même arrondi que l'accueil
from backend.models import DailyMetric, Incident

logger = logging.getLogger(__name__)

LIGNES: list[str] = list(LIGNES_CIBLES.values())
PERIODES: tuple[int, ...] = (7, 30)
SEUIL_CREUX = 0.6      # mois « creux » : coût < 60 % de la moyenne des mois complets
MIN_MOIS_CREUX = 3     # pas de creux calculé avec moins de 3 mois complets
DOSSIER_BILANS = Path(__file__).parent.parent / "frontend" / "data"

_RANG_LIGNE = {l: i for i, l in enumerate(LIGNES)}
_RANG_CATEGORIE = {c: i for i, c in enumerate(CATEGORIES)}


# ── Utilitaires ────────────────────────────────────────────────


def delta_pct(actuel: int, precedent: int | None) -> float | None:
    if not precedent:
        return None
    return round((actuel - precedent) / precedent * 100, 1)


def repartition_causes(categories: list[str]) -> dict:
    compte = Counter(categories)
    total = sum(compte.values())
    if not total:
        return {"total": 0, "repartition": []}

    items = sorted(compte.items(), key=lambda kv: (-kv[1], _RANG_CATEGORIE.get(kv[0], len(CATEGORIES))))
    bruts = [n * 100 / total for _, n in items]
    pcts = [math.floor(b) for b in bruts]
    # Méthode du plus fort reste : la somme affichée vaut exactement 100
    for i in sorted(range(len(items)), key=lambda i: (pcts[i] - bruts[i], i))[: 100 - sum(pcts)]:
        pcts[i] += 1

    return {
        "total": total,
        "repartition": [{"categorie": c, "n": n, "pct": p} for (c, n), p in zip(items, pcts)],
    }


def journee_paris(dt: datetime) -> date:
    """Journée de rattachement à Paris, la même que compute_daily_metrics (metrics.journee_de)."""
    return journee_de(dt)


def _vide() -> dict:
    return {"cout_eur": 0, "minutes": 0, "incidents": 0}


def _ajouter(agg: dict, row, smic_horaire: float) -> None:
    agg["cout_eur"] += cout_eur(row.minutes_voyageurs, smic_horaire)
    agg["minutes"] += row.minutes_voyageurs
    agg["incidents"] += row.nb_incidents


def _par_ligne(rows, du: date, au: date, smic_horaire: float) -> dict[str, dict]:
    aggs = {l: _vide() for l in LIGNES}
    for r in rows:
        if r.line_id in aggs and du <= r.date <= au:
            _ajouter(aggs[r.line_id], r, smic_horaire)
    return aggs


def _somme(aggs) -> dict:
    total = _vide()
    for a in aggs:
        for k in total:
            total[k] += a[k]
    return total


def _trier(aggs: dict[str, dict]) -> list[str]:
    return sorted(LIGNES, key=lambda l: (-aggs[l]["minutes"], _RANG_LIGNE[l]))


def _moins_un_an(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 février
        return date(d.year - 1, 2, 28)


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


# ── /statistiques ──────────────────────────────────────────────

def construire_statistiques(
    periode_jours: int,
    aujourdhui: date,
    lignes_metriques,
    categories_causes: list[str],
    debut_donnees: date | None,
    smic_horaire: float,
    genere_a: datetime,
) -> dict:
    au = aujourdhui
    du = au - timedelta(days=periode_jours - 1)
    au_prec = du - timedelta(days=1)
    du_prec = du - timedelta(days=periode_jours)

    courant = _par_ligne(lignes_metriques, du, au, smic_horaire)
    precedent = _par_ligne(lignes_metriques, du_prec, au_prec, smic_horaire)

    jours_couverts = 0 if debut_donnees is None else max(0, (au - max(du, debut_donnees)).days + 1)
    precedente_complete = debut_donnees is not None and debut_donnees <= du_prec

    lignes = [
        {
            "id": l,
            **courant[l],
            "delta_pct_minutes": (
                delta_pct(courant[l]["minutes"], precedent[l]["minutes"]) if precedente_complete else None
            ),
        }
        for l in _trier(courant)
    ]

    total = _somme(courant.values())
    total_prec = _somme(precedent.values()) if precedente_complete else None
    deltas = {k: delta_pct(total[k], total_prec[k]) for k in total} if total_prec else None

    pire = lignes[0]
    pire_ligne = (
        {k: pire[k] for k in ("id", "minutes", "incidents", "delta_pct_minutes")}
        if pire["minutes"] > 0 else None
    )

    return {
        "meta": {
            "genere_a": genere_a.isoformat(timespec="seconds"),
            "periode_jours": periode_jours,
            "du": du.isoformat(),
            "au": au.isoformat(),
            "precedente": {"du": du_prec.isoformat(), "au": au_prec.isoformat()},
            "smic_horaire": smic_horaire,
            "debut_donnees": _iso(debut_donnees),
            "jours_couverts": jours_couverts,
            "precedente_complete": precedente_complete,
        },
        "total": total,
        "total_prec": total_prec,
        "delta_pct": deltas,
        "lignes": lignes,
        "pire_ligne": pire_ligne,
        "causes": repartition_causes(categories_causes),
    }


# ── /annee ─────────────────────────────────────────────────────

def _cause_principale(categories: list[str]) -> str | None:
    compte = Counter(categories)
    if len(compte) > 1:
        compte.pop(NON_PRECISE, None)
    if not compte:
        return None
    return max(compte, key=lambda c: (compte[c], -_RANG_CATEGORIE.get(c, len(CATEGORIES))))


def construire_annee(
    annee: int,
    aujourdhui: date,
    lignes_metriques,
    categories_par_mois: dict[int, list[str]],
    debut_donnees: date | None,
    smic_horaire: float,
    genere_a: datetime,
) -> dict:
    debut_annee, fin_annee = date(annee, 1, 1), date(annee, 12, 31)
    au = min(aujourdhui, fin_annee)

    par_mois = {m: _vide() for m in range(1, 13)}
    for r in lignes_metriques:
        if r.line_id in _RANG_LIGNE and debut_annee <= r.date <= au:
            _ajouter(par_mois[r.date.month], r, smic_horaire)
    par_ligne = _par_ligne(lignes_metriques, debut_annee, au, smic_horaire)

    mois = []
    for m in range(1, 13):
        nb_jours = monthrange(annee, m)[1]
        debut_m, fin_m = date(annee, m, 1), date(annee, m, nb_jours)
        renseigne = debut_donnees is not None and debut_m <= au and fin_m >= debut_donnees
        if not renseigne:
            mois.append({"mois": m, "cout_eur": None, "minutes": None, "incidents": None,
                         "jours_couverts": 0, "partiel": False, "cause_principale": None})
            continue
        jours = (min(fin_m, au) - max(debut_m, debut_donnees)).days + 1
        mois.append({
            "mois": m,
            **par_mois[m],
            "jours_couverts": jours,
            "partiel": jours < nb_jours,
            "cause_principale": _cause_principale(categories_par_mois.get(m, [])),
        })

    renseignes = [m for m in mois if m["cout_eur"] is not None]
    total = _somme(renseignes)

    avec_cout = [m for m in renseignes if m["cout_eur"] > 0]
    pire_mois = max(avec_cout, key=lambda m: (m["cout_eur"], -m["mois"]))["mois"] if avec_cout else None

    complets = [m for m in renseignes if not m["partiel"]]
    creux: list[int] = []
    if len(complets) >= MIN_MOIS_CREUX:
        moyenne = sum(m["cout_eur"] for m in complets) / len(complets)
        creux = [m["mois"] for m in complets
                 if m["cout_eur"] < SEUIL_CREUX * moyenne and m["mois"] != pire_mois]

    # Comparaison à date équivalente : 1er janvier N-1 → même jour qu'aujourd'hui en N-1
    annee_prec_disponible = debut_donnees is not None and debut_donnees <= date(annee - 1, 1, 1)
    precedent = (
        _par_ligne(lignes_metriques, date(annee - 1, 1, 1), _moins_un_an(au), smic_horaire)
        if annee_prec_disponible else None
    )

    lignes = [
        {
            "id": l,
            **par_ligne[l],
            "delta_pct_minutes": delta_pct(par_ligne[l]["minutes"], precedent[l]["minutes"]) if precedent else None,
        }
        for l in _trier(par_ligne)
    ]

    en_recul = [l for l in lignes if l["delta_pct_minutes"] is not None and l["delta_pct_minutes"] < 0]
    meilleure = min(en_recul, key=lambda l: l["delta_pct_minutes"]) if en_recul else None

    return {
        "meta": {
            "annee": annee,
            "au": au.isoformat(),
            "en_cours": au < fin_annee,
            "genere_a": genere_a.isoformat(timespec="seconds"),
            "smic_horaire": smic_horaire,
            "debut_donnees": _iso(debut_donnees),
            "mois_renseignes": [m["mois"] for m in renseignes],
            "annee_prec_disponible": annee_prec_disponible,
        },
        "total": total,
        "mois": mois,
        "pire_mois": pire_mois,
        "creux": creux,
        "lignes": lignes,
        "meilleure_progression": (
            {"id": meilleure["id"], "delta_pct_minutes": meilleure["delta_pct_minutes"],
             "nb_lignes_en_recul": len(en_recul)}
            if meilleure else None
        ),
    }


# ── Hall of Shame ─────────────────────────────────────────────


def _percentile(values: list[int], p: float) -> float:
    """Percentile (interpolation linéaire) sans dépendance numpy."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = f + 1
    if c >= len(s):
        return float(s[f])
    return s[f] + (k - f) * (s[c] - s[f])


def _niveau_gravite(cout: int, seuils: tuple[float, float, float, float]) -> int:
    """0-4 selon les seuils p25, p50, p75, p90."""
    if cout <= 0:
        return 0
    if cout <= seuils[0]:
        return 1
    if cout <= seuils[1]:
        return 2
    if cout <= seuils[2]:
        return 3
    return 4


def construire_hall_of_shame(
    aujourdhui: date,
    lignes_metriques,
    perturbations_par_ligne: dict[str, list[str]],
    directions_par_ligne: dict[str, list[str]],
    smic_horaire: float,
    genere_a: datetime,
    debut_donnees: date | None = None,
) -> dict:
    """Construit le JSON hall-of-shame avec coûts, gravité quotidienne, causes et directions.
    Périodes calendaires, comme le panneau de ligne : semaine depuis lundi, mois depuis le 1er, année depuis le
    1er janvier (jours d'avant les données fiables déjà absents de `lignes_metriques`)."""
    annee = aujourdhui.year
    debut_annee = date(annee, 1, 1)
    du_semaine = aujourdhui - timedelta(days=aujourdhui.weekday())
    du_mois = aujourdhui.replace(day=1)

    # Agréger les daily_metrics par ligne
    par_ligne: dict[str, dict] = {}
    par_ligne_jour: dict[str, dict[date, int]] = {}  # ligne → {date → cout_eur}

    for r in lignes_metriques:
        if r.line_id not in _RANG_LIGNE:
            continue
        if r.date > aujourdhui:
            continue

        c = cout_eur(r.minutes_voyageurs, smic_horaire)

        if r.line_id not in par_ligne:
            par_ligne[r.line_id] = {
                "semaine": _vide(), "mois": _vide(), "annee": _vide(),
            }
            par_ligne_jour[r.line_id] = {}

        agg = par_ligne[r.line_id]
        if du_semaine <= r.date <= aujourdhui:
            agg["semaine"]["cout_eur"] += c
            agg["semaine"]["minutes"] += r.minutes_voyageurs
            agg["semaine"]["incidents"] += r.nb_incidents
        if du_mois <= r.date <= aujourdhui:
            agg["mois"]["cout_eur"] += c
            agg["mois"]["minutes"] += r.minutes_voyageurs
            agg["mois"]["incidents"] += r.nb_incidents
        if debut_annee <= r.date <= aujourdhui:
            agg["annee"]["cout_eur"] += c
            agg["annee"]["minutes"] += r.minutes_voyageurs
            agg["annee"]["incidents"] += r.nb_incidents

        if debut_annee <= r.date <= aujourdhui:
            par_ligne_jour.setdefault(r.line_id, {})[r.date] = c

    # Construire résultat par ligne
    resultats = []
    for lid in LIGNES:
        agg = par_ligne.get(lid)
        if not agg:
            agg = {"semaine": _vide(), "mois": _vide(), "annee": _vide()}

        jours = par_ligne_jour.get(lid, {})

        # Coûts par période
        cout = {
            "semaine": {"euros": agg["semaine"]["cout_eur"], "minutes": agg["semaine"]["minutes"]},
            "mois": {"euros": agg["mois"]["cout_eur"], "minutes": agg["mois"]["minutes"]},
            "annee": {"euros": agg["annee"]["cout_eur"], "minutes": agg["annee"]["minutes"]},
        }

        # Seuils de gravité par percentile sur les coûts quotidiens de l'année
        couts_annee = [v for v in jours.values() if v > 0]
        if couts_annee:
            seuils = (
                _percentile(couts_annee, 25),
                _percentile(couts_annee, 50),
                _percentile(couts_annee, 75),
                _percentile(couts_annee, 90),
            )
        else:
            seuils = (0.0, 0.0, 0.0, 0.0)

        # Gravité quotidienne
        gravite = []
        d = debut_annee
        while d <= aujourdhui:
            if d in jours:
                c_jour = jours[d]
                niv = _niveau_gravite(c_jour, seuils)
                gravite.append({"date": d.isoformat(), "niveau": niv, "cout_eur": c_jour})
            else:
                gravite.append({"date": d.isoformat(), "niveau": None, "cout_eur": None})
            d += timedelta(days=1)

        # Pire / meilleur mois
        par_mois_cout: dict[int, int] = defaultdict(int)
        par_mois_min: dict[int, int] = defaultdict(int)
        for dt, c_val in jours.items():
            par_mois_cout[dt.month] += c_val
        for r in lignes_metriques:
            if r.line_id == lid and debut_annee <= r.date <= aujourdhui:
                par_mois_min[r.date.month] += r.minutes_voyageurs

        pire_mois = None
        meilleur_mois = None
        if par_mois_cout:
            mois_avec_cout = [(m, c) for m, c in par_mois_cout.items() if c > 0]
            if mois_avec_cout:
                pm = max(mois_avec_cout, key=lambda x: (x[1], -x[0]))
                pire_mois = {"mois": pm[0], "cout_eur": pm[1], "minutes": par_mois_min.get(pm[0], 0)}
                bm = min(mois_avec_cout, key=lambda x: (x[1], x[0]))
                if bm[0] != pm[0]:
                    meilleur_mois = {"mois": bm[0], "cout_eur": bm[1], "minutes": par_mois_min.get(bm[0], 0)}

        # Causes (disruptions)
        cats = perturbations_par_ligne.get(lid, [])
        causes_rep = repartition_causes(cats)
        causes = [
            {"libelle": r["categorie"], "pourcentage": r["pct"], "n": r["n"]}
            for r in causes_rep["repartition"]
        ]

        # Top 3 directions (realtime)
        dirs_list = directions_par_ligne.get(lid, [])
        dir_compte = Counter(dirs_list)
        top_dirs = dir_compte.most_common(3)
        directions = []
        if top_dirs:
            max_dir_inc = top_dirs[0][1]
            for nom, n in top_dirs:
                # Niveau 0-4 basé sur la fréquence relative
                if max_dir_inc > 0:
                    ratio = n / max_dir_inc
                    niv = 4 if ratio > 0.9 else 3 if ratio > 0.6 else 2 if ratio > 0.3 else 1
                else:
                    niv = 0
                directions.append({"libelle": nom, "incidents": n, "niveau": niv})

        resultats.append({
            "id": lid,
            "cout": cout,
            "gravite_quotidienne": gravite,
            "pire_mois": pire_mois,
            "meilleur_mois": meilleur_mois,
            "causes": causes,
            "directions": directions,
        })

    return {
        "meta": {
            "genere_a": genere_a.isoformat(timespec="seconds"),
            "annee": annee,
            "au": aujourdhui.isoformat(),
            "smic_horaire": smic_horaire,
            "periodes": {"semaine": du_semaine.isoformat(), "mois": du_mois.isoformat(), "annee": debut_annee.isoformat()},
            "debut_donnees": _iso(debut_donnees),
        },
        "lignes": resultats,
    }


# ── Requêtes et écriture des fichiers ──────────────────────────

def _ecrire(dossier: Path, nom: str, contenu: dict) -> None:
    """Écriture atomique : un visiteur ne reçoit jamais un fichier à moitié écrit."""
    dossier.mkdir(parents=True, exist_ok=True)
    tmp = dossier / f"{nom}.tmp"
    tmp.write_text(json.dumps(contenu, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, dossier / nom)


async def generer_bilans(db: AsyncSession | None = None, dossier: Path = DOSSIER_BILANS) -> None:
    async def _run(session: AsyncSession) -> None:
        settings = get_settings()
        smic = settings.smic_horaire

        def ecrire(nom: str, contenu: dict) -> None:
            # Rythme de recalcul affiché en pied de page, lu dans la config
            contenu["meta"]["recalcul_minutes"] = settings.bilans_interval_minutes
            _ecrire(dossier, nom, contenu)
        genere_a = datetime.now(PARIS_TZ)
        aujourdhui = journee_de(genere_a)

        # Jours d'avant les données fiables : en base, mais hors de tout cumul et de toute comparaison
        premier = (await session.execute(select(func.min(DailyMetric.date)))).scalar()
        debut_donnees = premier_jour_affiche(premier) if premier is not None else None

        # Une seule lecture : 2 × la plus longue période pour /statistiques, 2 années pleines pour /annee N-1
        borne = premier_jour_affiche(min(aujourdhui - timedelta(days=2 * max(PERIODES)), date(aujourdhui.year - 2, 1, 1)))
        rows = (await session.execute(
            select(DailyMetric).where(DailyMetric.date >= borne, DailyMetric.date <= aujourdhui)
        )).scalars().all()

        debut_utc = debut_journee(borne)
        perturbations = [
            (journee_paris(heure), categoriser_cause(cause))
            for cause, heure in (await session.execute(
                select(Incident.cause, Incident.heure_debut).where(
                    Incident.source == "disruption", Incident.heure_debut >= debut_utc,
                )
            )).all()
        ]

        # Hall of Shame : perturbations par ligne + directions (realtime)
        perturbations_par_ligne_data = (await session.execute(
            select(Incident.line_id, Incident.lignes_impactees, Incident.cause, Incident.heure_debut).where(
                Incident.source == "disruption", Incident.heure_debut >= debut_utc,
            )
        )).all()
        perturbations_par_ligne: dict[str, list[str]] = defaultdict(list)
        for line_id, lignes_imp, cause, heure in perturbations_par_ligne_data:
            j = journee_paris(heure)
            if date(aujourdhui.year, 1, 1) <= j <= aujourdhui:
                cat = categoriser_cause(cause)
                for lid in (lignes_imp or [line_id]):
                    perturbations_par_ligne[lid].append(cat)

        directions_data = (await session.execute(
            select(Incident.line_id, Incident.direction).where(
                Incident.source == "realtime",
                Incident.heure_debut >= debut_journee(premier_jour_affiche(date(aujourdhui.year, 1, 1))),
                Incident.direction.isnot(None),
                Incident.direction != "",
            )
        )).all()
        directions_par_ligne: dict[str, list[str]] = defaultdict(list)
        for line_id, direction in directions_data:
            directions_par_ligne[line_id].append(direction)

        ecrire("hall-of-shame.json", construire_hall_of_shame(
            aujourdhui, rows, dict(perturbations_par_ligne),
            dict(directions_par_ligne), smic, genere_a, debut_donnees,
        ))

        for p in PERIODES:
            du = aujourdhui - timedelta(days=p - 1)
            categories = [c for j, c in perturbations if du <= j <= aujourdhui]
            ecrire(f"statistiques-{p}.json", construire_statistiques(
                p, aujourdhui, rows, categories, debut_donnees, smic, genere_a,
            ))

        annees = [aujourdhui.year]
        if debut_donnees is not None and debut_donnees <= date(aujourdhui.year - 1, 12, 31):
            annees.append(aujourdhui.year - 1)
        for annee in annees:
            par_mois: dict[int, list[str]] = {}
            for j, c in perturbations:
                if j.year == annee:
                    par_mois.setdefault(j.month, []).append(c)
            ecrire(f"annee-{annee}.json", construire_annee(
                annee, aujourdhui, rows, par_mois, debut_donnees, smic, genere_a,
            ))

        logger.info("Bilans générés (%d lignes daily_metrics, %d perturbations, hall-of-shame inclus)", len(rows), len(perturbations))

    try:
        if db is not None:
            await _run(db)
        else:
            async with AsyncSessionLocal() as session:
                await _run(session)
    except Exception:
        # Les fichiers précédents restent servis ; le scheduler continue
        logger.exception("Échec de la génération des bilans")
