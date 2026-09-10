"""Tests du formatage des durées dans le tweet quotidien."""
from datetime import date

import pytest

from backend.bot import _accord_perdu, _compose_tweet, _fmt_duree


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
