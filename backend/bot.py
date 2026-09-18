"""
bot.py — Récap quotidien à 20h00 : bilan du jour même (incidents, minutes-voyageurs, coût).
Toujours enregistré dans publications/AAAA-MM-JJ.txt ; posté aussi sur X (Twitter) si les clés
sont configurées.
"""
import logging
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import tweepy
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
        return f"{j} jours {h} h" if h else f"{j} jours"
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
        f"Base SMIC {smic:.2f}€/h · retardsidf.fr".replace(".", ",", 1),
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


async def post_daily_recap(dossier: Path = DOSSIER_PUBLICATIONS) -> None:
    """Récap quotidien, planifié à 20h00 par le scheduler dans main.py.

    Toujours enregistré dans le projet (publications/) ; posté en plus sur X quand les
    clés sont configurées.
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

    if not all([
        settings.twitter_api_key,
        settings.twitter_api_secret,
        settings.twitter_access_token,
        settings.twitter_access_secret,
    ]):
        logger.info("Clés Twitter/X non configurées — publication enregistrée seulement dans le projet")
        return

    try:
        client = tweepy.Client(
            consumer_key=settings.twitter_api_key,
            consumer_secret=settings.twitter_api_secret,
            access_token=settings.twitter_access_token,
            access_token_secret=settings.twitter_access_secret,
        )
        response = client.create_tweet(text=tweet_text)
        logger.info("Tweet posté avec succès — ID : %s", response.data["id"])
    except tweepy.TweepyException as exc:
        logger.error("Erreur tweepy lors de l'envoi du tweet : %s", exc)
