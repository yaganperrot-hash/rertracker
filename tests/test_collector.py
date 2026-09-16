"""Tests unitaires pour backend/collector.py"""
import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import backend.collector as collector
from backend.collector import (
    MODES_PHYSIQUES,
    QUOTA_ALERTE,
    _journaliser_quota,
    _suivre_quota,
    collecte_autorisee,
    PRIM_BASE_URL,
    _parse_dt,
    _extract_line_id,
    LIGNES_CIBLES,
    collect_disruptions,
    collect_rt_delays,
    analyser_train,
    attentes_mesurees,
    couverture_releve,
    fusionner_arrets,
    trains_du_flux,
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


class TestQuotaEtPauseNocturne:
    """Quota PRIM de 1 000 req/jour : pas de relevé la nuit, reste lu dans les en-têtes."""

    def test_pas_de_releve_la_nuit(self):
        # 03:00 à Paris (CEST = UTC+2)
        assert collecte_autorisee(datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)) is False

    def test_releves_de_6h_a_minuit(self):
        assert collecte_autorisee(datetime(2026, 9, 15, 4, 0, tzinfo=timezone.utc)) is True    # 06:00 Paris
        assert collecte_autorisee(datetime(2026, 9, 15, 21, 59, tzinfo=timezone.utc)) is True  # 23:59 Paris

    def test_quota_lu_dans_les_en_tetes(self, monkeypatch):
        monkeypatch.setattr(collector, "quota_restant", None)
        _suivre_quota(httpx.Response(200, headers={"x-ratelimit-remaining-day": "417"}))
        assert collector.quota_restant == 417

    def test_reponse_sans_en_tete_ignoree(self, monkeypatch):
        monkeypatch.setattr(collector, "quota_restant", 417)
        _suivre_quota(AsyncMock())
        _suivre_quota(httpx.Response(200))
        assert collector.quota_restant == 417

    def test_avertissement_sous_le_seuil(self, monkeypatch, caplog):
        monkeypatch.setattr(collector, "quota_restant_et", None)
        monkeypatch.setattr(collector, "quota_restant", QUOTA_ALERTE - 1)
        with caplog.at_level(logging.INFO, logger="backend.collector"):
            _journaliser_quota()
        assert [r.levelno for r in caplog.records] == [logging.WARNING]

    def test_info_au_dessus_du_seuil(self, monkeypatch, caplog):
        monkeypatch.setattr(collector, "quota_restant_et", None)
        monkeypatch.setattr(collector, "quota_restant", QUOTA_ALERTE)
        with caplog.at_level(logging.INFO, logger="backend.collector"):
            _journaliser_quota()
        assert [r.levelno for r in caplog.records] == [logging.INFO]


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


PARIS_TZ = __import__("zoneinfo").ZoneInfo("Europe/Paris")
T0 = datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc)   # 8 h à Paris
NOMS = {"1": "Gare Un", "2": "Gare Deux", "3": "Gare Trois"}


def _iso(minutes: int) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _appel(numero, prevu, retard=0, statut=None, terminus=False):
    """Arrêt SIRI : départ prévu à T0 + prevu, estimé avec `retard` minutes (arrivée seule au terminus)."""
    c = {"StopPointRef": {"value": f"STIF:StopArea:SP:{numero}:"}}
    statut = statut or ("DELAYED" if retard else "ON_TIME")
    c["AimedArrivalTime"], c["ArrivalStatus"] = _iso(prevu), statut
    if statut != "CANCELLED":
        c["ExpectedArrivalTime"] = _iso(prevu + retard)
    if not terminus:
        c["AimedDepartureTime"], c["DepartureStatus"] = _iso(prevu), statut
        if statut != "CANCELLED":
            c["ExpectedDepartureTime"] = _iso(prevu + retard)
    return c


def _train(uuid_suffixe, appels, sens="Aller", mission="QYRO"):
    return {
        "DatedVehicleJourneyRef": {"value": f"SNCF_MAGENTA_PRD:VehicleJourney::00000000-0000-0000-0000-{uuid_suffixe:0>12}:LOC"},
        "DirectionRef": {"value": sens},
        "JourneyNote": [{"value": mission}],
        "DestinationName": [{"value": "Gare Trois"}],
        "EstimatedCalls": {"EstimatedCall": appels},
    }


def _flux(*trains):
    return {"Siri": {"ServiceDelivery": {"EstimatedTimetableDelivery": [
        {"EstimatedJourneyVersionFrame": [{"EstimatedVehicleJourney": list(trains)}]}]}}}


class TestAnalyseFluxEstimatedTimetable:
    """Collecte sur le flux SIRI Estimated Timetable (TASK-31)."""

    def test_trains_du_flux(self):
        assert len(trains_du_flux(_flux(_train(1, []), _train(2, [])))) == 2
        assert trains_du_flux({}) == []

    def test_train_a_l_heure_ignore(self):
        t = _train(1, [_appel(1, 0), _appel(2, 10), _appel(3, 20, terminus=True)])
        assert analyser_train(t, T0, NOMS.get) is None

    def test_pire_retard_et_arrets_dans_l_ordre(self):
        # Le flux ne trie pas les arrêts
        t = _train(1, [_appel(3, 20, retard=4, terminus=True), _appel(1, 0), _appel(2, 10, retard=6)])
        o = analyser_train(t, T0, NOMS.get)
        assert o["uid"] == "rt_vehicle_journey:IDFM:TN:SNCF:00000000-0000-0000-0000-000000000001_20260917"
        assert (o["supprime"], o["retard"], o["gare"], o["mission"]) == (False, 6, "Gare Deux", "QYRO")
        assert o["prevu"] == T0 + timedelta(minutes=10)
        assert [a["g"] for a in o["arrets"]] == ["Gare Un", "Gare Deux", "Gare Trois"]
        assert [a["r"] for a in o["arrets"]] == [0, 6, 4]

    def test_retard_sous_le_seuil_ignore(self):
        t = _train(1, [_appel(1, 0, retard=1), _appel(2, 10, retard=1, terminus=True)])
        assert analyser_train(t, T0, NOMS.get) is None

    def test_suppression_en_fin_de_parcours(self):
        t = _train(1, [_appel(1, 0), _appel(2, 10, statut="CANCELLED"), _appel(3, 20, statut="CANCELLED", terminus=True)])
        o = analyser_train(t, T0, NOMS.get)
        assert o["supprime"] is True
        assert o["gare"] == "Gare Deux"
        assert [a["s"] for a in o["arrets"]] == [False, True, True]

    def test_train_fantome(self):
        # Prévu il y a 166 min, « part maintenant » (cas du train ELBA le 2026-09-11)
        t = _train(1, [_appel(1, -166, retard=166, terminus=True)])
        assert analyser_train(t, T0, NOMS.get)["fantome"] is True

    def test_gros_retard_estime_dans_le_futur_garde(self):
        t = _train(1, [_appel(1, -60, retard=90, terminus=True)])
        o = analyser_train(t, T0, NOMS.get)
        assert (o["fantome"], o["retard"]) == (False, 90)

    def test_attente_mesuree_du_train_suivant(self):
        supprime = _train(1, [_appel(1, 0, statut="CANCELLED"), _appel(2, 10, statut="CANCELLED", terminus=True)])
        suivant = _train(2, [_appel(1, 12, retard=3), _appel(2, 22, terminus=True)])      # passe en 1 à +15
        autre_sens = _train(3, [_appel(1, 5)], sens="Retour")
        attentes = attentes_mesurees([supprime, suivant, autre_sens])
        ref = supprime["DatedVehicleJourneyRef"]["value"]
        assert attentes[(ref, "1")] == 15
        assert attentes[(ref, "2")] == 12
        o = analyser_train(supprime, T0, NOMS.get, attentes)
        assert [a["w"] for a in o["arrets"]] == [15, 12]

    def test_attente_absente_sans_train_suivant(self):
        supprime = _train(1, [_appel(1, 0, statut="CANCELLED", terminus=True)])
        assert attentes_mesurees([supprime]) == {}

    def test_couverture(self):
        couv = couverture_releve([_train(1, [_appel(1, 0), _appel(2, 10)]), _train(2, [_appel(1, 30)])])
        assert (couv["trains"], couv["passages"]) == (2, 3)
        assert couv["debut"] == T0 and couv["fin"] == T0 + timedelta(minutes=30)


class TestFusionArrets:
    def test_arret_sorti_de_la_fenetre_conserve(self):
        anciens = [{"g": "A", "p": "1", "r": 5, "s": False, "w": None}]
        nouveaux = [{"g": "B", "p": "2", "r": 3, "s": False, "w": None}]
        assert [a["g"] for a in fusionner_arrets(anciens, nouveaux)] == ["A", "B"]

    def test_derniere_mesure_l_emporte(self):
        anciens = [{"g": "A", "p": "1", "r": 5, "s": False, "w": None}]
        assert fusionner_arrets(anciens, [{"g": "A", "p": "1", "r": 7, "s": False, "w": None}])[0]["r"] == 7

    def test_mesure_absente_ne_efface_pas(self):
        anciens = [{"g": "A", "p": "1", "r": 5, "s": True, "w": 12}]
        fusion = fusionner_arrets(anciens, [{"g": "A", "p": "1", "r": None, "s": True, "w": None}])
        assert (fusion[0]["r"], fusion[0]["w"]) == (5, 12)


class TestCollectRtDelays:
    """collect_rt_delays : appels, quota et écriture en base, sur un flux simulé."""

    async def _executer(self, flux, anciens=()):
        from sqlalchemy.dialects.postgresql import Insert

        resp = httpx.Response(200, json=flux, headers={"x-ratelimit-remaining-day": "640"},
                              request=httpx.Request("GET", collector.PRIM_ET_URL))
        executes = []

        async def execute(stmt, *args, **kwargs):
            executes.append(stmt)
            r = MagicMock()
            r.all.return_value = list(anciens)
            return r

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=execute)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        settings = MagicMock(prim_api_key="cle", cancel_default_impact_minutes=5)

        with (
            patch("backend.collector.get_settings", return_value=settings),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=resp) as get,
            patch("backend.collector.AsyncSessionLocal", return_value=session),
            patch("backend.offre.nom_arret", side_effect=NOMS.get),
        ):
            await collect_rt_delays()
        return get, [s for s in executes if isinstance(s, Insert)]

    async def test_un_appel_estimated_timetable_par_ligne(self, monkeypatch):
        monkeypatch.setattr(collector, "quota_restant_et", None)
        get, _ = await self._executer(_flux())
        assert get.await_count == len(LIGNES_CIBLES)
        urls = {c.args[0] for c in get.await_args_list}
        assert urls == {collector.PRIM_ET_URL}
        refs = {c.kwargs["params"]["LineRef"] for c in get.await_args_list}
        assert "STIF:Line::C01742:" in refs
        assert collector.quota_restant_et == 640

    async def test_retard_enregistre_avec_ses_arrets(self):
        from sqlalchemy.dialects import postgresql

        t = _train(1, [_appel(1, 0), _appel(2, 10, retard=6, terminus=True)])
        _, inserts = await self._executer(_flux(t))
        # Le même flux est servi pour les 13 lignes : un seul train, donc une seule écriture par uid
        params = inserts[-1].compile(dialect=postgresql.dialect()).params
        assert params["duree_minutes"] == 6
        assert params["is_cancelled"] is False
        assert params["gare"] == "Gare Deux"
        assert params["source"] == "realtime"
        assert [a["r"] for a in params["arrets"]] == [0, 6]

    async def test_suppression_enregistree(self):
        from sqlalchemy.dialects import postgresql

        t = _train(1, [_appel(1, 0, statut="CANCELLED"), _appel(2, 10, statut="CANCELLED", terminus=True)])
        _, inserts = await self._executer(_flux(t))
        params = inserts[-1].compile(dialect=postgresql.dialect()).params
        assert params["is_cancelled"] is True
        assert params["type_incident"] == "CANCELLED"
        assert params["cause"] == "Train supprimé à partir de Gare Un"

    async def test_arrets_fusionnes_avec_la_base(self):
        from sqlalchemy.dialects import postgresql

        t = _train(1, [_appel(2, 10, retard=6, terminus=True)])
        uid = "rt_vehicle_journey:IDFM:TN:SNCF:00000000-0000-0000-0000-000000000001_20260917"
        ancien = [{"g": "Gare Un", "p": T0.isoformat(), "r": 3, "s": False, "w": None}]
        _, inserts = await self._executer(_flux(t), anciens=[(uid, ancien)])
        params = inserts[-1].compile(dialect=postgresql.dialect()).params
        assert [a["g"] for a in params["arrets"]] == ["Gare Un", "Gare Deux"]

    async def test_skip_si_pas_de_cle_api(self):
        settings = MagicMock(prim_api_key=None)
        with (
            patch("backend.collector.get_settings", return_value=settings),
            patch.object(httpx.AsyncClient, "get") as get,
        ):
            await collect_rt_delays()
            get.assert_not_called()

    async def test_erreur_http_sans_ecriture(self):
        resp = httpx.Response(500, request=httpx.Request("GET", collector.PRIM_ET_URL))
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        with (
            patch("backend.collector.get_settings", return_value=MagicMock(prim_api_key="cle")),
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=resp),
            patch("backend.collector.AsyncSessionLocal", return_value=session),
        ):
            await collect_rt_delays()
        session.execute.assert_not_called()
