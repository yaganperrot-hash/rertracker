"""
bot.py — Post quotidien sur X (Twitter) à 20h00.
Résumé des incidents et minutes-voyageurs perdues de la veille.
"""
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import tweepy
from sqlalchemy import select, func

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.models import DailyMetric

logger = logging.getLogger(__name__)

SMIC_HORAIRE = 11.88  # € brut 2025

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


_JOURS = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]

def _compose_tweet(total_incidents: int, total_mv: int, lignes: list[str], d: date) -> str:
    euros = int(total_mv * SMIC_HORAIRE / 60)
    jour = _JOURS[d.weekday()]
    date_str = f"{jour} {d.day:02d}/{d.month:02d}/{d.year}"

    top = [LINE_DISPLAY.get(l, l) for l in lignes[:4]]
    lignes_str = ", ".join(top)
    if len(lignes) > 4:
        lignes_str += f" et {len(lignes) - 4} autre{'s' if len(lignes) - 4 > 1 else ''}"

    pire = LINE_DISPLAY.get(lignes[0], lignes[0]) if lignes else None

    lines = [
        f"🚨 {jour.capitalize()} {d.day:02d}/{d.month:02d}/{d.year} — Bilan RER & Transilien IDF",
        f"💶 {_fmt(euros)} € de temps de travail volé",
        f"⏱ {_fmt(total_mv)} minutes de vie perdues",
        f"🔴 {total_incidents} incident{'s' if total_incidents != 1 else ''}"
        + (f" — {pire} en tête" if pire else ""),
        f"Base SMIC 11,88€/h · retardsidf.fr",
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
        # Agrégats du jour précédent
        stmt_agg = select(
            func.coalesce(func.sum(DailyMetric.nb_incidents), 0).label("total_inc"),
            func.coalesce(func.sum(DailyMetric.minutes_voyageurs), 0).label("total_mv"),
        ).where(DailyMetric.date == yesterday)
        row = (await db.execute(stmt_agg)).one()
        total_inc = int(row.total_inc)
        total_mv = int(row.total_mv)

        # Lignes perturbées triées par impact décroissant
        stmt_lignes = (
            select(DailyMetric.line_id)
            .where(DailyMetric.date == yesterday, DailyMetric.est_jour_perturbe.is_(True))
            .order_by(DailyMetric.minutes_voyageurs.desc())
        )
        lignes = list((await db.execute(stmt_lignes)).scalars().all())

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
