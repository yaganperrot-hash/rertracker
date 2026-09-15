"""Tests unitaires pour backend/relabel_transilien.py : option --statut (sans base)"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend import relabel_transilien
from backend.relabel_transilien import deja_applique, main


def session_factice(*reponses):
    """AsyncSessionLocal factice : chaque appel à scalar() renvoie la réponse suivante."""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=list(reponses))
    fabrique = MagicMock()
    fabrique.return_value.__aenter__ = AsyncMock(return_value=db)
    fabrique.return_value.__aexit__ = AsyncMock(return_value=False)
    return fabrique, db


class TestDejaApplique:
    async def _appel(self, *reponses):
        fabrique, db = session_factice(*reponses)
        with patch.object(relabel_transilien, "AsyncSessionLocal", fabrique):
            return await deja_applique(), db

    def test_table_temoin_absente(self):
        applique, db = asyncio.run(self._appel(None))
        assert applique is False
        assert db.scalar.await_count == 1  # aucune requête sur une table inexistante
        db.execute.assert_not_called()     # rien de créé ni modifié
        db.commit.assert_not_called()

    def test_migration_non_appliquee(self):
        applique, db = asyncio.run(self._appel("migrations_appliquees", None))
        assert applique is False
        db.commit.assert_not_called()

    def test_migration_appliquee(self):
        applique, _ = asyncio.run(self._appel("migrations_appliquees", 1))
        assert applique is True


class TestMain:
    def test_statut_ne_lance_pas_le_reetiquetage(self, monkeypatch, capsys):
        monkeypatch.setattr(relabel_transilien, "deja_applique", AsyncMock(return_value=True))
        reetiqueter = AsyncMock()
        monkeypatch.setattr(relabel_transilien, "reetiqueter", reetiqueter)
        main(["--statut"])
        reetiqueter.assert_not_called()
        assert "déjà appliqué" in capsys.readouterr().out

    def test_statut_non_applique(self, monkeypatch, capsys):
        monkeypatch.setattr(relabel_transilien, "deja_applique", AsyncMock(return_value=False))
        main(["--statut"])
        assert "pas encore appliqué" in capsys.readouterr().out

    def test_sans_option_lance_le_reetiquetage(self, monkeypatch):
        reetiqueter = AsyncMock()
        monkeypatch.setattr(relabel_transilien, "reetiqueter", reetiqueter)
        main([])
        reetiqueter.assert_awaited_once()

    def test_option_inconnue(self, monkeypatch):
        reetiqueter = AsyncMock()
        monkeypatch.setattr(relabel_transilien, "reetiqueter", reetiqueter)
        with pytest.raises(SystemExit):
            main(["--force"])
        reetiqueter.assert_not_called()
