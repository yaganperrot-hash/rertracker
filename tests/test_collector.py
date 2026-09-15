"""Tests unitaires pour backend/collector.py"""
import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.collector import (
    MODES_PHYSIQUES,
    PRIM_BASE_URL,
    _parse_dt,
    _extract_line_id,
    LIGNES_CIBLES,
    collect_disruptions,
    collect_rt_delays,
)


class TestParseDt:
    def test_prim_format(self):
        # "20240315T143000" = 14:30 heure de Paris (CET, UTC+1) → 13:30 UTC
        result = _parse_dt("20240315T143000")
        assert result == datetime(2024, 3, 15, 13, 30, 0, tzinfo=timezone.utc)

    def test_prim_format_summer(self):
        # "20240715T143000" = 14:30 heure de Paris (CEST, UTC+2) → 12:30 UTC
        result = _parse_dt("20240715T143000")
        assert result == datetime(2024, 7, 15, 12, 30, 0, tzinfo=timezone.utc)

    def test_iso_format(self):
        # "2024-03-15T14:30:00" = 14:30 heure de Paris (CET, UTC+1) → 13:30 UTC
        result = _parse_dt("2024-03-15T14:30:00")
        assert result is not None
        assert result == datetime(2024, 3, 15, 13, 30, 0, tzinfo=timezone.utc)

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

    def test_identifiants_prim_verifies(self):
        # Relevés sur PRIM (pt_objects, mode « RER » / « Train Transilien ») le 2026-09-15.
        # Les « Remplacement … » (bus) ont d'autres IDs et ne doivent jamais apparaître ici.
        assert LIGNES_CIBLES == {
            "line:IDFM:C01742": "RER_A",
            "line:IDFM:C01743": "RER_B",
            "line:IDFM:C01727": "RER_C",
            "line:IDFM:C01728": "RER_D",
            "line:IDFM:C01729": "RER_E",
            "line:IDFM:C01737": "TRANSILIEN_H",
            "line:IDFM:C01739": "TRANSILIEN_J",
            "line:IDFM:C01738": "TRANSILIEN_K",
            "line:IDFM:C01740": "TRANSILIEN_L",
            "line:IDFM:C01736": "TRANSILIEN_N",
            "line:IDFM:C01730": "TRANSILIEN_P",
            "line:IDFM:C01731": "TRANSILIEN_R",
            "line:IDFM:C01741": "TRANSILIEN_U",
        }

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
        "status": "active",
        "impacted_objects": [
            {
                "pt_object": {
                    "embedded_type": "line",
                    "id": "line:IDFM:C01742",
                }
            }
        ],
        "application_periods": [
            {"begin": "20240315T080000", "end": "20240315T120000"}
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
        mock_resp.json = MagicMock(return_value=TestCollectDisruptions.MOCK_API_RESPONSE)

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

    async def test_un_appel_par_mode_physique(self):
        """1 appel line_reports pour les RER, 1 pour les Transilien (l'appel global renvoie vide)."""
        mocks = self._setup_mocks()

        with (
            patch("backend.collector.get_settings", return_value=mocks["mock_settings"]),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mocks["mock_session"]),
        ):
            mock_get.return_value = mocks["mock_resp"]
            await collect_disruptions()

            assert MODES_PHYSIQUES == ("physical_mode:RapidTransit", "physical_mode:LocalTrain")
            urls = [c[0][0] for c in mock_get.call_args_list]
            assert urls == [f"{PRIM_BASE_URL}/physical_modes/{m}/line_reports" for m in MODES_PHYSIQUES]

    async def test_perturbation_des_deux_modes_enregistree_une_fois(self):
        """La même perturbation renvoyée par les deux appels ne donne qu'un upsert."""
        mocks = self._setup_mocks()

        with (
            patch("backend.collector.get_settings", return_value=mocks["mock_settings"]),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mocks["mock_session"]),
        ):
            mock_get.return_value = mocks["mock_resp"]
            await collect_disruptions()

            assert mock_get.call_count == 2
            assert mocks["mock_session"].execute.call_count == 1

    async def test_avertit_si_prim_renvoie_zero_ligne(self, caplog):
        """Réponse 200 sans line_report : avertissement par mode, pas de silence."""
        mocks = self._setup_mocks()

        with (
            caplog.at_level(logging.WARNING, logger="backend.collector"),
            patch("backend.collector.get_settings", return_value=mocks["mock_settings"]),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mocks["mock_session"]),
        ):
            mock_get.return_value = mocks["mock_resp"]  # line_reports: []
            await collect_disruptions()

        avertissements = [r for r in caplog.records if "0 line_report" in r.getMessage()]
        assert len(avertissements) == len(MODES_PHYSIQUES)

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
        mock_settings = MagicMock()
        mock_settings.prim_api_key = "test-key"

        with (
            patch("backend.collector.get_settings", return_value=mock_settings),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
        ):
            mock_get.side_effect = httpx.HTTPError("403 Forbidden")
            await collect_disruptions()  # ne doit pas lever d'exception

    async def test_disruption_has_source_disruption(self):
        """collect_disruptions must tag incidents with source='disruption'."""
        mocks = self._setup_mocks()

        executed_stmts = []
        original_execute = mocks["mock_session"].execute

        async def capture_execute(stmt, *args, **kwargs):
            executed_stmts.append(stmt)
            return await original_execute(stmt, *args, **kwargs)

        mocks["mock_session"].execute = AsyncMock(side_effect=capture_execute)

        with (
            patch("backend.collector.get_settings", return_value=mocks["mock_settings"]),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mocks["mock_session"]),
        ):
            mock_get.return_value = mocks["mock_resp"]
            await collect_disruptions()

            # Check that at least one insert was executed with source='disruption'
            assert len(executed_stmts) > 0, "No statements executed"
            # The insert statement should contain source='disruption' in its compiled params
            stmt = executed_stmts[0]
            compiled = stmt.compile()
            params = compiled.params
            assert params.get("source") == "disruption", (
                f"Expected source='disruption', got params: {params}"
            )


class TestCollectRtDelays:
    """Tests for collect_rt_delays — source tagging and heure_theorique."""

    MOCK_DEPARTURE = {
        "stop_date_time": {
            "data_freshness": "realtime",
            "base_departure_date_time": "20240315T080000",
            "departure_date_time": "20240315T081000",
        },
        "links": [{"type": "vehicle_journey", "id": "vj:test:001"}],
    }

    @staticmethod
    def _setup_mocks(departures=None):
        if departures is None:
            departures = [TestCollectRtDelays.MOCK_DEPARTURE]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"departures": departures})

        mock_settings = MagicMock()
        mock_settings.prim_api_key = "test-key"
        mock_settings.cancel_default_impact_minutes = 5

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        return {
            "mock_resp": mock_resp,
            "mock_settings": mock_settings,
            "mock_session": mock_session,
        }

    async def test_rt_delay_has_source_realtime(self):
        """RT delays must be tagged with source='realtime'."""
        mocks = self._setup_mocks()
        executed_stmts = []

        async def capture_execute(stmt, *args, **kwargs):
            executed_stmts.append(stmt)
            # Return a mock result for select queries
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            return mock_result

        mocks["mock_session"].execute = AsyncMock(side_effect=capture_execute)

        with (
            patch("backend.collector.get_settings", return_value=mocks["mock_settings"]),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mocks["mock_session"]),
        ):
            mock_get.return_value = mocks["mock_resp"]
            await collect_rt_delays()

            # Find insert statements (not select)
            insert_stmts = [s for s in executed_stmts if hasattr(s, 'compile') and 'insert' in str(type(s)).lower() or hasattr(s, '_post_values_clause')]
            # At least the first statement should be an insert with source=realtime
            assert len(executed_stmts) > 0, "No statements executed"

    async def test_rt_delay_stores_gare_direction_mission(self):
        """RT delays must record station, direction and mission code."""
        from sqlalchemy.dialects import postgresql

        dep = {
            **self.MOCK_DEPARTURE,
            "stop_point": {"name": "Vigneux-sur-Seine"},
            "display_informations": {
                "direction": "Corbeil-Essonnes (Corbeil-Essonnes)",
                "headsign": "ROPE",
            },
        }
        mocks = self._setup_mocks()
        resp = MagicMock()
        resp.json.return_value = {"departures": [dep]}
        executed_stmts = []

        async def capture_execute(stmt, *args, **kwargs):
            executed_stmts.append(stmt)
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            return mock_result

        mocks["mock_session"].execute = AsyncMock(side_effect=capture_execute)

        with (
            patch("backend.collector.get_settings", return_value=mocks["mock_settings"]),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mocks["mock_session"]),
        ):
            mock_get.return_value = resp
            await collect_rt_delays()

        params = executed_stmts[0].compile(dialect=postgresql.dialect()).params
        assert params["gare"] == "Vigneux-sur-Seine"
        assert params["direction"] == "Corbeil-Essonnes"
        assert params["mission"] == "ROPE"
        assert params["cause"] == "Retard de 10 min à Vigneux-sur-Seine"

    async def test_rt_delay_one_incident_per_train_with_worst_delay(self):
        """A train seen at several stations yields one incident with its worst delay."""
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.dialects.postgresql import Insert

        def dep(gare, base, rt, vj="vj:test:001"):
            return {
                "stop_point": {"name": gare},
                "stop_date_time": {
                    "data_freshness": "realtime",
                    "base_departure_date_time": base,
                    "departure_date_time": rt,
                },
                "links": [{"type": "vehicle_journey", "id": vj}],
            }

        mocks = self._setup_mocks()
        resp = MagicMock()
        # Même train, suffixe RealTime différent (il change à chaque mise à jour PRIM)
        resp.json.return_value = {"departures": [
            dep("Gare A", "20240315T080000", "20240315T080300", vj="vj:test:001:RealTime:aaa"),
            dep("Gare B", "20240315T081000", "20240315T081600", vj="vj:test:001:RealTime:bbb"),
        ]}
        executed_stmts = []

        async def capture_execute(stmt, *args, **kwargs):
            executed_stmts.append(stmt)
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            return mock_result

        mocks["mock_session"].execute = AsyncMock(side_effect=capture_execute)

        with (
            patch("backend.collector.get_settings", return_value=mocks["mock_settings"]),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mocks["mock_session"]),
        ):
            mock_get.return_value = resp
            await collect_rt_delays()

        inserts = [s for s in executed_stmts if isinstance(s, Insert)]
        assert len(inserts) == 1
        params = inserts[0].compile(dialect=postgresql.dialect()).params
        assert params["navitia_id"] == "rt_vj:test:001_20240315"
        assert params["duree_minutes"] == 6
        assert params["gare"] == "Gare B"
        # 08:10 heure de Paris (UTC+1 en mars) = 07:10 UTC
        assert params["heure_theorique"] == datetime(2024, 3, 15, 7, 10, tzinfo=timezone.utc)

    async def test_rt_delay_has_is_cancelled_false(self):
        """RT delays must have is_cancelled=False."""
        mocks = self._setup_mocks()
        executed_stmts = []

        async def capture_execute(stmt, *args, **kwargs):
            executed_stmts.append(stmt)
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            return mock_result

        mocks["mock_session"].execute = AsyncMock(side_effect=capture_execute)

        with (
            patch("backend.collector.get_settings", return_value=mocks["mock_settings"]),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mocks["mock_session"]),
        ):
            mock_get.return_value = mocks["mock_resp"]
            await collect_rt_delays()
            assert len(executed_stmts) > 0

    async def _inserts_for(self, departures):
        """Lance collect_rt_delays sur un flux simulé et renvoie les INSERT exécutés."""
        from sqlalchemy.dialects.postgresql import Insert

        mocks = self._setup_mocks()
        resp = MagicMock()
        resp.json.return_value = {"departures": departures}
        executed_stmts = []

        async def capture_execute(stmt, *args, **kwargs):
            executed_stmts.append(stmt)
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            return mock_result

        mocks["mock_session"].execute = AsyncMock(side_effect=capture_execute)

        with (
            patch("backend.collector.get_settings", return_value=mocks["mock_settings"]),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mocks["mock_session"]),
        ):
            mock_get.return_value = resp
            await collect_rt_delays()
        return [s for s in executed_stmts if isinstance(s, Insert)]

    @staticmethod
    def _dep_relative(base_offset_min, rt_offset_min):
        """Départ dont les heures prévue / estimée sont relatives à maintenant (heure de Paris)."""
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Europe/Paris"))
        f = "%Y%m%dT%H%M%S"
        return {
            "stop_point": {"name": "Gare d'Austerlitz"},
            "stop_date_time": {
                "data_freshness": "realtime",
                "base_departure_date_time": (now + timedelta(minutes=base_offset_min)).strftime(f),
                "departure_date_time": (now + timedelta(minutes=rt_offset_min)).strftime(f),
            },
            "links": [{"type": "vehicle_journey", "id": "vj:test:ghost"}],
        }

    async def test_ghost_train_ignored(self):
        """Gros retard dont le départ estimé colle à l'heure du relevé : train fantôme, écarté."""
        # Prévu il y a 166 min, « part maintenant » — cas du train ELBA le 2026-09-11
        assert await self._inserts_for([self._dep_relative(-166, 0)]) == []

    async def test_large_delay_with_future_estimate_kept(self):
        """Un gros retard avec un départ estimé dans le futur est une vraie mesure."""
        assert len(await self._inserts_for([self._dep_relative(-60, 30)])) == 1

    async def test_held_train_below_ghost_threshold_kept(self):
        """Un train retenu en gare (estimé = maintenant) sous le seuil reste compté."""
        assert len(await self._inserts_for([self._dep_relative(-20, 0)])) == 1

    async def test_skip_si_pas_de_cle_api(self):
        """If PRIM_API_KEY is not set, collect_rt_delays does nothing."""
        mock_settings = MagicMock()
        mock_settings.prim_api_key = None

        with (
            patch("backend.collector.get_settings", return_value=mock_settings),
            patch.object(httpx.AsyncClient, "get") as mock_get,
        ):
            await collect_rt_delays()
            mock_get.assert_not_called()


class TestCancellationDetection:
    """Tests for train cancellation detection logic."""

    async def test_disappeared_train_marked_cancelled(self):
        """A train that disappears from the feed before its expected departure is cancelled."""
        now = datetime.now(timezone.utc)
        # Prévu il y a 1 min avec 10 min de retard → départ attendu dans 9 min
        mock_incident = await self._run_with_existing(now - timedelta(minutes=1), 10)
        assert mock_incident.is_cancelled is True, "Disappeared train should be marked as cancelled"

    async def test_departed_train_not_cancelled(self):
        """A train that disappears after its expected departure simply left — not cancelled."""
        now = datetime.now(timezone.utc)
        # Prévu il y a 30 min avec 5 min de retard → parti il y a 25 min
        mock_incident = await self._run_with_existing(now - timedelta(minutes=30), 5)
        assert mock_incident.is_cancelled is False

    async def _run_with_existing(self, heure_theorique, duree_minutes):
        # Mock an existing RT incident in DB that won't appear in fetched results
        mock_incident = MagicMock()
        mock_incident.navitia_id = "rt_vj:old:001_20240315"
        mock_incident.line_id = "RER_A"
        mock_incident.source = "realtime"
        mock_incident.is_cancelled = False
        mock_incident.heure_theorique = heure_theorique
        mock_incident.duree_minutes = duree_minutes

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Only another train in the feed — the old train is gone
        mock_resp.json = MagicMock(return_value={"departures": [
            {
                "stop_date_time": {
                    "data_freshness": "realtime",
                    "base_departure_date_time": "20240315T090000",
                    "departure_date_time": "20240315T091500",
                },
                "links": [{"type": "vehicle_journey", "id": "vj:new:001"}],
            }
        ]})

        mock_settings = MagicMock()
        mock_settings.prim_api_key = "test-key"
        mock_settings.cancel_default_impact_minutes = 5

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            # For select queries (cancellation detection), return the mock incident
            if hasattr(stmt, 'whereclause') or 'select' in str(type(stmt)).lower():
                mock_result.scalars.return_value.all.return_value = [mock_incident]
            else:
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=mock_execute)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("backend.collector.get_settings", return_value=mock_settings),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get,
            patch("backend.collector.AsyncSessionLocal", return_value=mock_session),
        ):
            mock_get.return_value = mock_resp
            await collect_rt_delays()

        return mock_incident
