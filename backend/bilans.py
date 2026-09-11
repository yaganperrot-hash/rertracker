"""
bilans.py — Bilans des pages /statistiques (7, 30, 90 jours glissants) et /annee.

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
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.causes import CATEGORIES, NON_PRECISE, categoriser_cause
from backend.collector import LIGNES_CIBLES
from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.metrics import PARIS_TZ
from backend.models import DailyMetric, Incident

logger = logging.getLogger(__name__)

LIGNES: list[str] = list(LIGNES_CIBLES.values())
PERIODES: tuple[int, ...] = (7, 30, 90)
SEUIL_CREUX = 0.6      # mois « creux » : coût < 60 % de la moyenne des mois complets
MIN_MOIS_CREUX = 3     # pas de creux calculé avec moins de 3 mois complets
DOSSIER_BILANS = Path(__file__).parent.parent / "frontend" / "data"

_RANG_LIGNE = {l: i for i, l in enumerate(LIGNES)}
_RANG_CATEGORIE = {c: i for i, c in enumerate(CATEGORIES)}


# ── Utilitaires ────────────────────────────────────────────────

def cout_eur(minutes_voyageurs: int, smic_horaire: float) -> int:
    """floor(minutes × smic / 60). Appliqué à UNE ligne de daily_metrics, jamais à une somme.

    Calcul en centimes entiers : pas d'erreur d'arrondi flottant (19,999… au lieu de 20).
    """
    return (minutes_voyageurs * round(smic_horaire * 100)) // 6000


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
    """Journée de rattachement à Paris : comme compute_daily_metrics, elle commence à 7 h."""
    return (dt.astimezone(PARIS_TZ) - timedelta(hours=7)).date()


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


# ── Requêtes et écriture des fichiers ──────────────────────────

def _ecrire(dossier: Path, nom: str, contenu: dict) -> None:
    """Écriture atomique : un visiteur ne reçoit jamais un fichier à moitié écrit."""
    dossier.mkdir(parents=True, exist_ok=True)
    tmp = dossier / f"{nom}.tmp"
    tmp.write_text(json.dumps(contenu, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, dossier / nom)


async def generer_bilans(db: AsyncSession | None = None, dossier: Path = DOSSIER_BILANS) -> None:
    async def _run(session: AsyncSession) -> None:
        smic = get_settings().smic_horaire
        genere_a = datetime.now(PARIS_TZ)
        aujourdhui = genere_a.date()

        debut_donnees = (await session.execute(select(func.min(DailyMetric.date)))).scalar()

        # Une seule lecture : 2 × 90 jours pour /statistiques, 2 années pleines pour /annee N-1
        borne = min(aujourdhui - timedelta(days=2 * max(PERIODES)), date(aujourdhui.year - 2, 1, 1))
        rows = (await session.execute(
            select(DailyMetric).where(DailyMetric.date >= borne, DailyMetric.date <= aujourdhui)
        )).scalars().all()

        debut_utc = datetime.combine(borne, time(0, 0), tzinfo=PARIS_TZ)
        perturbations = [
            (journee_paris(heure), categoriser_cause(cause))
            for cause, heure in (await session.execute(
                select(Incident.cause, Incident.heure_debut).where(
                    Incident.source == "disruption", Incident.heure_debut >= debut_utc,
                )
            )).all()
        ]

        for p in PERIODES:
            du = aujourdhui - timedelta(days=p - 1)
            categories = [c for j, c in perturbations if du <= j <= aujourdhui]
            _ecrire(dossier, f"statistiques-{p}.json", construire_statistiques(
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
            _ecrire(dossier, f"annee-{annee}.json", construire_annee(
                annee, aujourdhui, rows, par_mois, debut_donnees, smic, genere_a,
            ))

        logger.info("Bilans générés (%d lignes daily_metrics, %d perturbations)", len(rows), len(perturbations))

    try:
        if db is not None:
            await _run(db)
        else:
            async with AsyncSessionLocal() as session:
                await _run(session)
    except Exception:
        # Les fichiers précédents restent servis ; le scheduler continue
        logger.exception("Échec de la génération des bilans")
