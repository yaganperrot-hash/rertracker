"""
bot.py — Récap quotidien à 19h30 : bilan du jour même (incidents, minutes-voyageurs, coût).
Enregistré dans publications/ (texte + carte PNG + carousel Instagram), récupérable sur /publications.
"""
import logging
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.metrics import cout_eur
from backend.models import DailyMetric

logger = logging.getLogger(__name__)

LINE_DISPLAY: dict[str, str] = {
    "RER_A": "RER A",        "RER_B": "RER B",        "RER_C": "RER C",
    "RER_D": "RER D",        "RER_E": "RER E",
    "TRANSILIEN_H": "H",     "TRANSILIEN_J": "J",     "TRANSILIEN_K": "K",
    "TRANSILIEN_L": "L",     "TRANSILIEN_N": "N",     "TRANSILIEN_P": "P",
    "TRANSILIEN_R": "R",     "TRANSILIEN_U": "U",
    "METRO_1": "M1",        "METRO_2": "M2",        "METRO_3": "M3",
    "METRO_3B": "M3bis",    "METRO_4": "M4",        "METRO_5": "M5",
    "METRO_6": "M6",        "METRO_7": "M7",        "METRO_7B": "M7bis",
    "METRO_8": "M8",        "METRO_9": "M9",        "METRO_10": "M10",
    "METRO_11": "M11",      "METRO_12": "M12",      "METRO_13": "M13",
    "METRO_14": "M14",
}

# Espace fine insécable pour les grands nombres
_NNBS = "\u202f"


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", _NNBS)


_H, _J, _A = 60, 1440, 525_600


def _fmt_duree(minutes: int) -> str:
    """Minutes → minutes / heures / jours / années (même logique que frontend/duree.js)."""
    m = max(0, int(minutes))
    if m < 2 * _H:
        return f"{m} minute{'s' if m >= 2 else ''}"
    if m < 2 * _J:
        h, r = divmod(m, _H)
        return f"{h} h {r} min" if r else f"{h} h"
    if m < 2 * _A:
        j, h = m // _J, (m % _J) // _H
        return f"{j} jours {h} h" if h and j < 7 else f"{j} jours"
    a, j = m // _A, (m % _A) // _J
    reste = f" {j} jour{'s' if j >= 2 else ''}" if j else ""
    return f"{_fmt(a)} ans{reste}"


def _accord_perdu(minutes: int) -> str:
    return "perdues" if minutes < 2 * _J else "perdus"


_JOURS = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]

def _compose_tweet(total_incidents: int, total_mv: int, lignes: list[str], d: date,
                   euros: int | None = None) -> str:
    """euros : coût arrondi par ligne puis sommé (règle du site) ; à défaut, arrondi du total."""
    smic = get_settings().smic_horaire
    if euros is None:
        euros = cout_eur(total_mv, smic)
    jour = _JOURS[d.weekday()]
    pire = LINE_DISPLAY.get(lignes[0], lignes[0]) if lignes else None

    lines = [
        f"🚨 {jour.capitalize()} {d.day:02d}/{d.month:02d}/{d.year} — Bilan RER & Transilien IDF",
        f"💶 {_fmt(euros)} € de temps de travail volé",
        f"⏱ {_fmt_duree(total_mv)} de vie {_accord_perdu(total_mv)} collectivement",
        f"🔴 {total_incidents} incident{'s' if total_incidents != 1 else ''}"
        + (f" — {pire} en tête" if pire else ""),
        f"Base SMIC {smic:.2f}€/h · idf-retard.fr".replace(".", ",", 1),
    ]

    return "\n".join(lines)


DOSSIER_PUBLICATIONS = Path(__file__).parent.parent / "publications"


def enregistrer_publication(texte: str, jour: date, dossier: Path = DOSSIER_PUBLICATIONS) -> Path:
    """Écrit le post dans dossier/AAAA-MM-JJ.txt (date de publication).

    Écriture atomique ; relancé le même jour, le fichier est remplacé, jamais dupliqué.
    """
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{jour.isoformat()}.txt"
    tmp = chemin.with_suffix(".txt.tmp")
    tmp.write_text(texte + "\n", encoding="utf-8")
    os.replace(tmp, chemin)
    return chemin


async def generer_carte_png(jour: date, dossier: Path = DOSSIER_PUBLICATIONS) -> Path | None:
    """Ouvre carte.html dans Chromium headless, attend le rendu, screenshot 1080x1080 → PNG."""
    from playwright.async_api import async_playwright

    dossier.mkdir(parents=True, exist_ok=True)
    chemin_png = dossier / f"{jour.isoformat()}.png"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={"width": 1080, "height": 1080})
            await page.goto("http://localhost:8000/carte.html", wait_until="networkidle")
            # Attendre que carte.html signale la fin du rendu
            await page.wait_for_function(
                "document.body.dataset.pret === '1'",
                timeout=15_000,
            )
            await page.screenshot(path=str(chemin_png), type="png")
            await browser.close()

        logger.info("Carte PNG générée : %s", chemin_png)
        return chemin_png
    except Exception:
        logger.exception("Erreur lors de la génération de la carte PNG")
        return None


async def generer_carousel_png(jour: date, dossier: Path = DOSSIER_PUBLICATIONS) -> list[Path]:
    """Ouvre carousel.html, screenshot chaque .slide → publications/AAAA-MM-JJ/slide-N.png."""
    from playwright.async_api import async_playwright

    dossier_jour = dossier / jour.isoformat()
    dossier_jour.mkdir(parents=True, exist_ok=True)
    chemins: list[Path] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            # Hauteur large pour contenir les 5 slides empilées
            page = await browser.new_page(viewport={"width": 1080, "height": 5400})
            await page.goto("http://localhost:8000/carousel.html", wait_until="networkidle")
            await page.wait_for_function(
                "document.body.dataset.pret === '1'",
                timeout=15_000,
            )

            slides = await page.query_selector_all(".slide")
            for i, slide in enumerate(slides, 1):
                chemin = dossier_jour / f"slide-{i}.png"
                await slide.screenshot(path=str(chemin), type="png")
                chemins.append(chemin)
                logger.info("Slide %d générée : %s", i, chemin)

            await browser.close()
    except Exception:
        logger.exception("Erreur lors de la génération du carrousel PNG")

    return chemins


async def post_daily_recap(dossier: Path = DOSSIER_PUBLICATIONS) -> None:
    """Récap quotidien, planifié à 19h30 par le scheduler dans main.py.

    Enregistre texte + images dans publications/, récupérables sur /publications.
    """
    settings = get_settings()
    aujourdhui = datetime.now(ZoneInfo("Europe/Paris")).date()

    async with AsyncSessionLocal() as db:
        # Une seule requête — agrégats calculés en Python depuis les lignes
        stmt = (
            select(DailyMetric)
            .where(DailyMetric.date == aujourdhui)
            .order_by(DailyMetric.minutes_voyageurs.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()

    total_inc = sum(r.nb_incidents for r in rows)
    total_mv  = sum(r.minutes_voyageurs for r in rows)
    lignes    = [r.line_id for r in rows if r.est_jour_perturbe]
    # Arrondi par ligne puis sommé : même montant que l'accueil et les bilans
    euros     = sum(cout_eur(r.minutes_voyageurs, settings.smic_horaire) for r in rows)

    if total_inc == 0:
        logger.info("Aucun incident enregistré aujourd'hui (%s) — pas de publication", aujourdhui)
        return

    tweet_text = _compose_tweet(total_inc, total_mv, lignes, aujourdhui, euros=euros)
    chemin = enregistrer_publication(tweet_text, aujourdhui, dossier)
    logger.info("Publication du jour enregistrée : %s\n%s", chemin, tweet_text)

    # Générer la carte PNG (screenshot de carte.html)
    chemin_png = await generer_carte_png(aujourdhui, dossier)
    if chemin_png:
        logger.info("Carte PNG du jour : %s", chemin_png)

    # Générer le carrousel Instagram (5 slides PNG)
    slides = await generer_carousel_png(aujourdhui, dossier)
    if slides:
        logger.info("Carrousel Instagram : %d slides dans %s", len(slides), slides[0].parent)

    logger.info("Publication prête — texte + images disponibles sur /publications")
