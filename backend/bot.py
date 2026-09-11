"""
bot.py — Post quotidien sur X (Twitter) à 20h00.
Résumé des incidents et minutes-voyageurs perdues de la veille.
"""
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import tweepy
from sqlalchemy import select

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.models import DailyMetric

logger = logging.getLogger(__name__)

LINE_DISPLAY: dict[str, str] = {
    "RER_A": "RER A",        "RER_B": "RER B",        "RER_C": "RER C",
    "RER_D": "RER D",        "RER_E": "RER E",
    "TRANSILIEN_H": "H",     "TRANSILIEN_J": "J",     "TRANSILIEN_K": "K",
    "TRANSILIEN_L": "L",     "TRANSILIEN_N": "N",     "TRANSILIEN_P": "P",
    "TRANSILIEN_R": "R",     "TRANSILIEN_U": "U",
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

def _compose_tweet(total_incidents: int, total_mv: int, lignes: list[str], d: date) -> str:
    smic = get_settings().smic_horaire
    euros = int(total_mv * smic / 60)
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


async def post_daily_recap() -> None:
    """Poster le récap quotidien sur X. Planifié à 20h00 par le scheduler dans main.py."""
    settings = get_settings()

    if not all([
        settings.twitter_api_key,
        settings.twitter_api_secret,
        settings.twitter_access_token,
        settings.twitter_access_secret,
    ]):
        logger.warning("Clés Twitter/X non configurées — post quotidien ignoré")
        return

    yesterday = datetime.now(ZoneInfo("Europe/Paris")).date() - timedelta(days=1)

    async with AsyncSessionLocal() as db:
        # Une seule requête — agrégats calculés en Python depuis les lignes
        stmt = (
            select(DailyMetric)
            .where(DailyMetric.date == yesterday)
            .order_by(DailyMetric.minutes_voyageurs.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()

    total_inc = sum(r.nb_incidents for r in rows)
    total_mv  = sum(r.minutes_voyageurs for r in rows)
    lignes    = [r.line_id for r in rows if r.est_jour_perturbe]

    if total_inc == 0:
        logger.info("Aucun incident enregistré hier (%s) — tweet ignoré", yesterday)
        return

    tweet_text = _compose_tweet(total_inc, total_mv, lignes, yesterday)
    logger.info("Envoi du tweet quotidien :\n%s", tweet_text)

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
