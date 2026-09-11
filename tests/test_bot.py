"""Tests du récap quotidien : formatage des durées, montant, enregistrement dans le projet."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.bot import (
    _accord_perdu, _compose_tweet, _fmt_duree, enregistrer_publication, post_daily_recap,
)


@pytest.mark.parametrize("minutes, attendu", [
    (0, "0 minute"),
    (1, "1 minute"),
    (87, "87 minutes"),
    (119, "119 minutes"),
    (120, "2 h"),
    (872, "14 h 32 min"),
    (2880, "2 jours"),
    (267_000, "185 jours 10 h"),
    (1_051_200, "2 ans"),
    (2_847_340, "5 ans 152 jours"),
    (525_600 * 3 + 1440, "3 ans 1 jour"),
])
def test_fmt_duree(minutes, attendu):
    assert _fmt_duree(minutes) == attendu


def test_accord_perdu():
    assert _accord_perdu(2879) == "perdues"
    assert _accord_perdu(2880) == "perdus"


def test_tweet_utilise_duree_lisible():
    tweet = _compose_tweet(42, 2_847_340, ["RER_B"], date(2026, 9, 10))
    assert "⏱ 5 ans 152 jours de vie perdus collectivement" in tweet


def test_tweet_affiche_le_montant_fourni():
    tweet = _compose_tweet(3, 1000, ["RER_A"], date(2026, 9, 10), euros=205)
    assert "💶 205 € de temps de travail volé" in tweet


def test_publication_enregistree_par_date(tmp_path):
    dossier = tmp_path / "publications"
    chemin = enregistrer_publication("Bilan", date(2026, 9, 11), dossier)
    assert chemin == dossier / "2026-09-11.txt"
    assert chemin.read_text(encoding="utf-8") == "Bilan\n"
    # Relancé le même jour : remplacé, pas dupliqué
    enregistrer_publication("Bilan corrigé", date(2026, 9, 11), dossier)
    assert chemin.read_text(encoding="utf-8") == "Bilan corrigé\n"
    assert list(dossier.iterdir()) == [chemin]


class _Session:
    """Session base factice : renvoie les lignes daily_metrics données."""
    def __init__(self, rows):
        self.rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        res = MagicMock()
        res.scalars.return_value.all.return_value = self.rows
        return res


async def test_sans_cles_x_publication_enregistree_sans_tweet(tmp_path):
    rows = [
        SimpleNamespace(nb_incidents=5, minutes_voyageurs=97, line_id="RER_A", est_jour_perturbe=True),
        SimpleNamespace(nb_incidents=2, minutes_voyageurs=97, line_id="RER_B", est_jour_perturbe=True),
    ]
    settings = SimpleNamespace(smic_horaire=12.31, twitter_api_key="", twitter_api_secret="",
                               twitter_access_token="", twitter_access_secret="")
    with patch("backend.bot.AsyncSessionLocal", return_value=_Session(rows)), \
         patch("backend.bot.get_settings", return_value=settings), \
         patch("backend.bot.tweepy.Client") as client:
        await post_daily_recap(dossier=tmp_path)

    fichiers = list(tmp_path.iterdir())
    assert len(fichiers) == 1
    texte = fichiers[0].read_text(encoding="utf-8")
    # 19 € + 19 € arrondis par ligne (arrondir la somme donnerait 39 €)
    assert "💶 38 € de temps de travail volé" in texte
    assert "🔴 7 incidents — RER A en tête" in texte
    client.assert_not_called()


async def test_aucun_incident_aucune_publication(tmp_path):
    settings = SimpleNamespace(smic_horaire=12.31, twitter_api_key="", twitter_api_secret="",
                               twitter_access_token="", twitter_access_secret="")
    with patch("backend.bot.AsyncSessionLocal", return_value=_Session([])), \
         patch("backend.bot.get_settings", return_value=settings):
        await post_daily_recap(dossier=tmp_path)
    assert list(tmp_path.iterdir()) == []
