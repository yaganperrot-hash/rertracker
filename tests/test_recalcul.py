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


# Bug 46 : un train n'est supprimé que tant qu'un de ses arrêts fusionnés l'est
from datetime import datetime  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from backend.collector import suppression_levee, train_supprime  # noqa: E402
from backend.recalcul import lever_suppressions  # noqa: E402


def test_train_supprime_tant_qu_un_arret_l_est():
    assert train_supprime([{"s": False}, {"s": True}]) is True
    assert train_supprime([{"s": False}, {"s": None}]) is False
    assert train_supprime(None) is False


def test_suppression_levee_reprend_le_pire_retard_des_arrets():
    arrets = [{"g": "Gare du Nord", "p": P1, "r": 2, "s": False}, {"g": "Châtelet", "p": P2, "r": 5, "s": False},
              {"g": "Gare de Lyon", "p": P3, "r": None, "s": None}]
    assert suppression_levee(arrets) == {
        "is_cancelled": False, "type_incident": "DELAY_REALTIME", "duree_minutes": 5,
        "cause": "Retard de 5 min à Châtelet", "gare": "Châtelet", "heure_theorique": datetime.fromisoformat(P2)}


def test_suppression_levee_sans_retard_mesure():
    assert suppression_levee([{"g": "Châtelet", "p": P2, "r": None, "s": False}])["duree_minutes"] == 0


async def test_lever_suppressions_ne_touche_que_les_suppressions_levees():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.sql.dml import Update

    levee = MagicMock(id=1, arrets=[{"g": "Châtelet", "p": P2, "r": 4, "s": False}])
    toujours = MagicMock(id=2, arrets=[{"g": "Châtelet", "p": P2, "r": None, "s": True}])
    vide = MagicMock(id=3, arrets=[])
    executes = []

    async def execute(stmt, *args, **kwargs):
        executes.append(stmt)
        r = MagicMock()
        r.scalars.return_value.all.return_value = [levee, toujours, vide]
        return r

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    with patch("backend.recalcul.AsyncSessionLocal", return_value=session):
        assert await lever_suppressions() == 1
    updates = [e for e in executes if isinstance(e, Update)]
    params = updates[0].compile(dialect=postgresql.dialect()).params
    assert params["is_cancelled"] is False and params["duree_minutes"] == 4 and params["id_1"] == 1
