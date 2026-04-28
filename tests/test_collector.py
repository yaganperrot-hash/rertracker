"""Tests unitaires pour backend/collector.py"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.collector import (
    PRIM_BASE_URL,
    _parse_dt,
    _extract_line_id,
    LIGNES_CIBLES,
    collect_disruptions,
)


class TestParseDt:
    def test_prim_format(self):
        result = _parse_dt("20240315T143000")
        assert result == datetime(2024, 3, 15, 14, 30, 0, tzinfo=timezone.utc)

    def test_iso_format(self):
        result = _parse_dt("2024-03-15T14:30:00")
        assert result is not None
        assert result.year == 2024
        assert result.month == 3
        assert result.day == 15

    def test_none_input(self):
        assert _parse_dt(None) is None

    def test_empty_string(self):
        assert _parse_dt("") is None

    def test_invalid_string(self):
        assert _parse_dt("not-a-date") is None

    def test_result_is_utc(self):
        result = _parse_dt("20240101T000000")
        assert result.tzinfo == timezone.utc


class TestExtractLineId:
    def _make_impacted(self, navitia_line_id: str) -> list:
        return [
            {
                "pt_object": {
                    "embedded_type": "line",
                    "id": navitia_line_id,
                }
            }
        ]

    def test_known_line_rer_a(self):
        result = _extract_line_id(self._make_impacted("line:IDFM:C01742"))
        assert result == "RER_A"

    def test_known_line_rer_b(self):
        result = _extract_line_id(self._make_impacted("line:IDFM:C01743"))
        assert result == "RER_B"

    def test_known_line_transilien_h(self):
        result = _extract_line_id(self._make_impacted("line:IDFM:C01737"))
        assert result == "TRANSILIEN_H"

    def test_unknown_line_returns_none(self):
        result = _extract_line_id(self._make_impacted("line:IDFM:UNKNOWN"))
        assert result is None

    def test_empty_list_returns_none(self):
        assert _extract_line_id([]) is None

    def test_non_line_embedded_type_ignored(self):
        impacted = [
            {
                "pt_object": {
                    "embedded_type": "stop_area",
                    "id": "line:IDFM:C01742",
                }
            }
        ]
        assert _extract_line_id(impacted) is None

    def test_all_lignes_cibles_covered(self):
        for navitia_id, expected in LIGNES_CIBLES.items():
            result = _extract_line_id(self._make_impacted(navitia_id))
            assert result == expected, f"{navitia_id} should map to {expected}"


class TestCollectDisruptions:
    """Tests pour collect_disruptions — mocks httpx et base de données"""

    MOCK_DISRUPTION = {
        "id": "disruption:test-001",
        "impacted_objects": [
            {
                "pt_object": {
                    "embedded_type": "line",
                    "id": "line:IDFM:C01742",
                }
            }
        ],
        "application_periods": [
            {"begin": "20240315T063000", "end": "20240315T120000"}
        ],
        "messages": [{"text": "Incident test RER A"}],
        "severity": {"effect": "DISRUPTION"},
    }

    MOCK_API_RESPONSE = {
        "disruptions": [MOCK_DISRUPTION],
        "line_reports": [],
    }

    @staticmethod
    def _setup_mocks() -> dict:
        """Configure et retourne tous les mocks nécessaires."""
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = AsyncMock(return_value=TestCollectDisruptions.MOCK_API_RESPONSE)

        mock_settings = MagicMock()
        mock_settings.prim_api_key = "test-prim-key"

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        return {
            "mock_resp": mock_resp,
            "mock_settings": mock_settings,
            "mock_session": mock_session,
        }

    async def test_appelle_line_reports_et_non_disruptions(self):
        """L'URL appelée doit contenir /line_reports, pas /disruptions/."""
        mocks = self._setup_mocks()

        with (
            patch("backend.collector.get_settings", return_value=mocks["mock_settings"]),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mocks["mock_session"]),
        ):
            mock_get.return_value = mocks["mock_resp"]
            await collect_disruptions()

            url_appelee = mock_get.call_args[0][0]
            assert "/line_reports" in url_appelee, (
                f"L'URL doit contenir /line_reports, reçue : {url_appelee}"
            )
            assert "/disruptions/" not in url_appelee, (
                f"L'URL ne doit PAS contenir /disruptions/, reçue : {url_appelee}"
            )

    async def test_params_contient_disable_geojson(self):
        """Les paramètres de la requête doivent inclure disable_geojson=true."""
        mocks = self._setup_mocks()

        with (
            patch("backend.collector.get_settings", return_value=mocks["mock_settings"]),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mocks["mock_session"]),
        ):
            mock_get.return_value = mocks["mock_resp"]
            await collect_disruptions()

            params = mock_get.call_args[1].get("params", {})
            assert params.get("disable_geojson") == "true", (
                f"disable_geojson doit être 'true', reçu : {params}"
            )

    async def test_pr_base_url_correct(self):
        """PRIM_BASE_URL doit pointer vers /marketplace/v2/navitia."""
        assert "marketplace/v2/navitia" in PRIM_BASE_URL
        assert PRIM_BASE_URL.endswith("navitia")

    async def test_parse_disruptions_depuis_reponse(self):
        """Les disruptions sont extraites de la clé racine 'disruptions'."""
        mocks = self._setup_mocks()

        with (
            patch("backend.collector.get_settings", return_value=mocks["mock_settings"]),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mocks["mock_session"]),
        ):
            mock_get.return_value = mocks["mock_resp"]
            await collect_disruptions()

            # Vérifie que la session a exécuté un upsert (donc parsing OK)
            assert mocks["mock_session"].execute.called, (
                "Aucun execute() appelé → le parsing des disruptions a échoué"
            )
            assert mocks["mock_session"].commit.called

    async def test_skip_si_pas_de_cle_api(self):
        """Si PRIM_API_KEY n'est pas défini, collect_disruptions ne fait rien."""
        mock_settings = MagicMock()
        mock_settings.prim_api_key = None

        with (
            patch("backend.collector.get_settings", return_value=mock_settings),
            patch.object(httpx.AsyncClient, "get") as mock_get,
        ):
            await collect_disruptions()
            mock_get.assert_not_called()

    async def test_ignore_si_api_retourne_erreur(self):
        """Une erreur HTTP ne doit pas planter le collecteur."""
        mock_resp = AsyncMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403 Forbidden", request=MagicMock(), response=MagicMock()
        )

        mock_settings = MagicMock()
        mock_settings.prim_api_key = "test-key"

        with (
            patch("backend.collector.get_settings", return_value=mock_settings),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
        ):
            mock_get.return_value = mock_resp
            await collect_disruptions()  # ne doit pas lever d'exception
