"""Tests unitaires pour backend/recalcul.py : réparation de l'état « supprimé » (sans base)"""
from backend.recalcul import premier_arret_supprime

P1, P2, P3 = "2026-09-18T05:15:40+00:00", "2026-09-18T05:20:00+00:00", "2026-09-18T05:24:00+00:00"


def test_premier_arret_supprime_dans_l_ordre_du_train():
    arrets = [{"g": "Gare du Nord", "p": P1, "s": False}, {"g": "Châtelet", "p": P2, "s": True},
              {"g": "Gare de Lyon", "p": P3, "s": True}]
    assert premier_arret_supprime(arrets)["g"] == "Châtelet"


def test_arret_hors_fenetre_non_releve_ne_compte_pas():
    # s = None : arrêt non mesuré (hors fenêtre), pas une suppression
    assert premier_arret_supprime([{"g": "Melun", "p": P1, "s": None}, {"g": "Cesson", "p": P2, "s": False}]) is None


def test_arrets_absents_ou_json_null():
    assert premier_arret_supprime(None) is None
    assert premier_arret_supprime([]) is None
