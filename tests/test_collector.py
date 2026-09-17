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
    archiver_flux,
    arrets_sautes,
    couverture_releve,
    marquer_sautes,
    resume_releve,
    ecarts_train_suivant,
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


def _train(uuid_suffixe, appels, sens="Aller", mission="QYRO", ligne="C01742"):
    return {
        "LineRef": {"value": f"STIF:Line::{ligne}:"},
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
        o = analyser_train(t, T0 + timedelta(minutes=20), NOMS.get)   # tous les arrêts dans la fenêtre
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
        o = analyser_train(t, T0 + timedelta(minutes=10), NOMS.get)
        assert o["supprime"] is True
        assert o["gare"] == "Gare Deux"
        assert [a["s"] for a in o["arrets"]] == [False, True, True]

    def test_train_fantome(self):
        # Prévu il y a 166 min, « part maintenant » (cas du train ELBA le 2026-09-11)
        t = _train(1, [_appel(1, -166, retard=166, terminus=True)])
        assert analyser_train(t, T0, NOMS.get)["fantome"] is True

    def test_gros_retard_estime_dans_le_futur_garde(self):
        t = _train(1, [_appel(1, -60, retard=90, terminus=True)])   # estimé à +30
        o = analyser_train(t, T0 + timedelta(minutes=25), NOMS.get)
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

    def test_ecart_mesure_avec_le_train_suivant(self):
        """Voyageur à quai : premier AUTRE train du même sens qui dessert la montée puis la descente."""
        retarde = _train(1, [_appel(1, 10, retard=8), _appel(2, 20, retard=8), _appel(3, 30, retard=8, terminus=True)])
        omnibus = _train(2, [_appel(1, 16), _appel(2, 26), _appel(3, 36, terminus=True)])   # en 1 à +16
        direct = _train(4, [_appel(1, 14), _appel(3, 30, terminus=True)])                    # en 1 à +14, sans 2
        autre_sens = _train(3, [_appel(1, 11), _appel(2, 12)], sens="Retour")
        ecarts = ecarts_train_suivant([retarde, omnibus, direct, autre_sens], T0)
        ref = retarde["DatedVehicleJourneyRef"]["value"]
        assert ecarts[(ref, "1")] == {"2": 6, "3": 4}
        assert ecarts[(ref, "2")] == {"3": 6}
        assert ecarts[(ref, "3")] == {}
        # Écarts relevés sur tout l'horizon, même hors de la fenêtre de mesure des retards
        o = analyser_train(retarde, T0, NOMS.get, ecarts=ecarts, suivi=True)
        assert [a["a"] for a in o["arrets"]] == [{"Gare Deux": 6, "Gare Trois": 4}, {"Gare Trois": 6}, {}]

    def test_ecart_non_mesure_pour_un_arret_deja_prevu(self):
        """Heure prévue passée au relevé : un train passé entre-temps a pu sortir du flux → pas de mesure."""
        retarde = _train(1, [_appel(1, -5, retard=10), _appel(2, 20, retard=10), _appel(3, 30, terminus=True)])
        suivant = _train(2, [_appel(1, 3), _appel(2, 28), _appel(3, 38, terminus=True)])
        ref = retarde["DatedVehicleJourneyRef"]["value"]
        ecarts = ecarts_train_suivant([retarde, suivant], T0)
        assert (ref, "1") not in ecarts
        assert ecarts[(ref, "2")] == {"3": 8}
        assert analyser_train(retarde, T0, NOMS.get, ecarts=ecarts)["arrets"][0]["a"] is None

    def test_ecart_trains_suivants_a_la_meme_heure(self):
        """Deux trains suivants au même passage (cas du RER A, 17/09 à 9 h 33) : pas d'erreur de tri."""
        retarde = _train(1, [_appel(1, 10, retard=8), _appel(2, 20, retard=8, terminus=True)])
        a = _train(2, [_appel(1, 14), _appel(3, 30, terminus=True)])
        b = _train(4, [_appel(1, 14), _appel(2, 24, terminus=True)])
        ref = retarde["DatedVehicleJourneyRef"]["value"]
        assert ecarts_train_suivant([retarde, a, b], T0)[(ref, "1")] == {"2": 4}

    def test_ecart_vide_sans_autre_train(self):
        seul = _train(1, [_appel(1, 10, retard=8), _appel(2, 20, retard=8, terminus=True)])
        ref = seul["DatedVehicleJourneyRef"]["value"]
        assert ecarts_train_suivant([seul], T0)[(ref, "1")] == {}

    def test_ecart_ignore_les_arrets_supprimes(self):
        supprime = _train(1, [_appel(1, 10, statut="CANCELLED"), _appel(2, 20, statut="CANCELLED", terminus=True)])
        suivant = _train(2, [_appel(1, 15), _appel(2, 25, statut="CANCELLED", terminus=True)])
        retarde = _train(3, [_appel(1, 5, retard=12), _appel(2, 15, retard=12, terminus=True)])
        ecarts = ecarts_train_suivant([supprime, suivant, retarde], T0)
        assert (supprime["DatedVehicleJourneyRef"]["value"], "1") not in ecarts
        # Le suivant ne dessert plus 2 : aucun train pour aller de 1 à 2
        assert ecarts[(retarde["DatedVehicleJourneyRef"]["value"], "1")] == {}

    def test_couverture(self):
        couv = couverture_releve([_train(1, [_appel(1, 0), _appel(2, 10)]), _train(2, [_appel(1, 30)])])
        assert (couv["trains"], couv["passages"]) == (2, 3)
        assert couv["debut"] == T0 and couv["fin"] == T0 + timedelta(minutes=30)


class TestFenetreDeMesure:
    """Un retard ou une suppression n'est relevé qu'à moins de FENETRE_MESURE_MINUTES du passage estimé."""

    def test_valeur(self):
        assert collector.FENETRE_MESURE_MINUTES == 10

    def test_retard_annonce_longtemps_a_l_avance_ignore(self):
        t = _train(1, [_appel(1, 240, retard=12), _appel(2, 250, retard=12, terminus=True)])
        assert analyser_train(t, T0, NOMS.get) is None

    def test_retard_releve_a_dix_minutes_du_passage(self):
        t = _train(1, [_appel(1, 60, retard=5), _appel(2, 70, retard=5, terminus=True)])   # estimé à +65
        assert analyser_train(t, T0 + timedelta(minutes=54), NOMS.get) is None
        o = analyser_train(t, T0 + timedelta(minutes=55), NOMS.get)
        assert (o["retard"], o["gare"]) == (5, "Gare Un")
        assert [a["r"] for a in o["arrets"]] == [5, None]

    def test_fenetre_sur_l_heure_estimee(self):
        # Prévu à +5, estimé à +20 : hors fenêtre au relevé de T0 alors que l'heure prévue y est
        t = _train(1, [_appel(1, 5, retard=15, terminus=True)])
        assert analyser_train(t, T0, NOMS.get) is None
        assert analyser_train(t, T0 + timedelta(minutes=10), NOMS.get)["retard"] == 15

    def test_arret_passe_mesure(self):
        t = _train(1, [_appel(1, -3, retard=4), _appel(2, 30, retard=4, terminus=True)])
        o = analyser_train(t, T0, NOMS.get)
        assert [a["r"] for a in o["arrets"]] == [4, None]

    def test_suppression_lointaine_ignoree(self):
        t = _train(1, [_appel(1, 0), _appel(2, 40, statut="CANCELLED", terminus=True)])
        assert analyser_train(t, T0, NOMS.get) is None
        o = analyser_train(t, T0 + timedelta(minutes=30), NOMS.get)
        assert o["supprime"] is True and o["gare"] == "Gare Deux"

    def test_suppression_lointaine_non_marquee_sur_un_train_en_retard(self):
        t = _train(1, [_appel(1, 0, retard=3), _appel(2, 40, statut="CANCELLED", terminus=True)])
        o = analyser_train(t, T0, NOMS.get, attentes={(t["DatedVehicleJourneyRef"]["value"], "2"): 12})
        assert o["supprime"] is False and o["retard"] == 3
        assert [(a["s"], a["w"]) for a in o["arrets"]] == [(False, None), (False, None)]

    def test_suivi_rend_un_train_sans_retard(self):
        t = _train(1, [_appel(1, 0), _appel(2, 60, retard=8, terminus=True)])
        assert analyser_train(t, T0, NOMS.get) is None
        o = analyser_train(t, T0, NOMS.get, suivi=True)
        assert (o["supprime"], o["retard"], o["fantome"]) == (False, 0, False)
        assert [a["r"] for a in o["arrets"]] == [0, None]

    def test_retard_rattrape_jamais_compte(self):
        """Annoncé 6 min en retard 30 min avant, finalement à l'heure : aucune mesure de retard."""
        annonce = _train(1, [_appel(1, 30, retard=6, terminus=True)])
        a_l_heure = _train(1, [_appel(1, 30, terminus=True)])
        assert analyser_train(annonce, T0, NOMS.get) is None
        assert analyser_train(a_l_heure, T0 + timedelta(minutes=25), NOMS.get) is None


class TestFusionArrets:
    def test_arret_sorti_de_la_fenetre_conserve(self):
        anciens = [{"g": "A", "p": "1", "r": 5, "s": False, "w": None}]
        nouveaux = [{"g": "B", "p": "2", "r": 3, "s": False, "w": None}]
        assert [a["g"] for a in fusionner_arrets(anciens, nouveaux)] == ["A", "B"]

    def test_derniere_mesure_l_emporte(self):
        anciens = [{"g": "A", "p": "1", "r": 5, "s": False, "w": None}]
        assert fusionner_arrets(anciens, [{"g": "A", "p": "1", "r": 7, "s": False, "w": None}])[0]["r"] == 7

    def test_ecart_mesure_conserve(self):
        anciens = [{"g": "A", "p": "1", "r": 5, "s": False, "w": None, "a": {"B": 4}}]
        fusion = fusionner_arrets(anciens, [{"g": "A", "p": "1", "r": 6, "s": False, "w": None, "a": None}])
        assert (fusion[0]["r"], fusion[0]["a"]) == (6, {"B": 4})
        # Une nouvelle mesure, même vide, remplace l'ancienne
        fusion = fusionner_arrets(anciens, [{"g": "A", "p": "1", "r": 6, "s": False, "w": None, "a": {}}])
        assert fusion[0]["a"] == {}

    def test_mesure_absente_ne_efface_pas(self):
        anciens = [{"g": "A", "p": "1", "r": 5, "s": True, "w": 12}]
        fusion = fusionner_arrets(anciens, [{"g": "A", "p": "1", "r": None, "s": True, "w": None}])
        assert (fusion[0]["r"], fusion[0]["w"]) == (5, 12)


class TestArretsSautes:
    """Soupçon B (17/09) : arrêt retiré du flux alors que le train n'y est pas encore passé."""

    def test_cas_du_zani_de_7h58(self):
        # 8 h 09 : Les Ardoines (1) et BFM (4) mis à jour, Vitry (2) et Ivry (3) absents
        avant = _train(1, [_appel(1, 1, retard=3), _appel(2, 4, retard=3), _appel(3, 6, retard=3),
                           _appel(4, 9, retard=3, terminus=True)])
        apres = _train(1, [_appel(1, 1, retard=10), _appel(4, 9, retard=10, terminus=True)])
        ref = avant["DatedVehicleJourneyRef"]["value"]
        sautes = arrets_sautes(resume_releve([avant]), [apres])
        assert [(r, n) for r, n, _ in sautes] == [(ref, "2"), (ref, "3")]

    def test_arrets_passes_sortis_du_flux_ne_sont_pas_sautes(self):
        avant = _train(1, [_appel(1, 1), _appel(2, 4), _appel(3, 6, terminus=True)])
        apres = _train(1, [_appel(3, 6, terminus=True)])
        assert arrets_sautes(resume_releve([avant]), [apres]) == []

    def test_arret_deja_supprime_ou_train_sorti_du_flux(self):
        avant = _train(1, [_appel(1, 1), _appel(2, 4, statut="CANCELLED"), _appel(3, 6, terminus=True)])
        apres = _train(1, [_appel(1, 1), _appel(3, 6, terminus=True)])
        assert arrets_sautes(resume_releve([avant]), [apres]) == []
        assert arrets_sautes(resume_releve([avant]), []) == []

    def test_marquage_sur_les_arrets_connus(self):
        arrets = [{"g": "A", "p": "1", "r": 3}, {"g": "B", "p": "2", "r": 3}]
        assert marquer_sautes(arrets, [("B", "2"), ("Z", "9")]) == [{"g": "A", "p": "1", "r": 3},
                                                                    {"g": "B", "p": "2", "r": 3, "k": True}]

    def test_marque_perdue_si_l_arret_revient(self):
        anciens = [{"g": "B", "p": "2", "r": 3, "k": True}]
        assert "k" not in fusionner_arrets(anciens, [{"g": "B", "p": "2", "r": 4, "s": False, "w": None}])[0]


class TestArchiveFlux:
    def test_reponse_brute_gzippee_par_jour(self, tmp_path):
        import gzip
        chemin = archiver_flux("RER_C", b'{"Siri": {}}', T0, 3, racine=tmp_path)
        assert chemin == tmp_path / "2026-09-17" / "080000-RER_C.json.gz"
        assert gzip.decompress(chemin.read_bytes()) == b'{"Siri": {}}'

    def test_purge_au_dela_de_la_duree(self, tmp_path):
        for jour in ("2026-09-13", "2026-09-14", "2026-09-15"):
            (tmp_path / jour).mkdir()
        (tmp_path / "notes").mkdir()
        archiver_flux("RER_C", b"{}", T0, 3, racine=tmp_path)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-09-14", "2026-09-15", "2026-09-17", "notes"]

    def test_desactivee(self, tmp_path):
        assert archiver_flux("RER_C", b"{}", T0, 0, racine=tmp_path) is None
        assert archiver_flux("RER_C", b"{}", T0, MagicMock(), racine=tmp_path) is None
        assert list(tmp_path.iterdir()) == []

    def test_erreur_d_ecriture_sans_exception(self, tmp_path):
        fichier = tmp_path / "pas-un-dossier"
        fichier.write_text("x", encoding="utf-8")
        assert archiver_flux("RER_C", b"{}", T0, 3, racine=fichier) is None


class TestCollectRtDelays:
    """collect_rt_delays : appels, quota et écriture en base, sur un flux simulé."""

    async def _executer(self, flux, anciens=(), executes=None):
        from sqlalchemy.dialects.postgresql import Insert

        resp = httpx.Response(200, json=flux, headers={"x-ratelimit-remaining-day": "640"},
                              request=httpx.Request("GET", collector.PRIM_ET_URL))
        executes = [] if executes is None else executes

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

    async def test_un_seul_appel_pour_tout_le_reseau(self, monkeypatch):
        monkeypatch.setattr(collector, "quota_restant_et", None)
        get, _ = await self._executer(_flux())
        assert get.await_count == collector.REQUETES_ET_PAR_RELEVE == 1
        assert get.await_args.args[0] == collector.PRIM_ET_URL
        assert get.await_args.kwargs["params"] == {"LineRef": "ALL"}
        assert collector.quota_restant_et == 640

    async def test_trains_des_autres_lignes_ecartes(self):
        from sqlalchemy.dialects import postgresql

        rer_c = _train(1, [_appel(1, 0), _appel(2, 10, retard=6, terminus=True)], ligne="C01727")
        bus = _train(2, [_appel(1, 0), _appel(2, 10, retard=9, terminus=True)], ligne="C00001")
        _, inserts = await self._executer(_flux(rer_c, bus))
        assert len(inserts) == 1
        params = inserts[0].compile(dialect=postgresql.dialect()).params
        assert (params["line_id"], params["duree_minutes"]) == ("RER_C", 6)

    async def test_retard_enregistre_avec_ses_arrets(self):
        from sqlalchemy.dialects import postgresql

        t = _train(1, [_appel(1, 0), _appel(2, 10, retard=6, terminus=True)])
        _, inserts = await self._executer(_flux(t))
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

    async def test_echec_de_la_mesure_d_ecart_sans_perte_du_releve(self):
        from sqlalchemy.dialects import postgresql

        t = _train(1, [_appel(1, 0), _appel(2, 10, retard=6, terminus=True)])
        with patch.object(collector, "ecarts_train_suivant", side_effect=TypeError("boum")):
            _, inserts = await self._executer(_flux(t))
        params = inserts[-1].compile(dialect=postgresql.dialect()).params
        assert params["duree_minutes"] == 6
        assert all(a["a"] is None for a in params["arrets"])

    async def test_arret_saute_marque_au_releve_suivant(self, monkeypatch):
        from sqlalchemy.dialects import postgresql

        monkeypatch.setattr(collector, "_releves_precedents", {})
        avant = _train(1, [_appel(1, 1, retard=3), _appel(2, 4, retard=3), _appel(3, 9, retard=3, terminus=True)])
        apres = _train(1, [_appel(1, 1, retard=5), _appel(3, 9, retard=5, terminus=True)])
        await self._executer(_flux(avant))
        uid = "rt_vehicle_journey:IDFM:TN:SNCF:00000000-0000-0000-0000-000000000001_20260917"
        connus = [{"g": "Gare Un", "p": _iso(1).replace("Z", "+00:00"), "r": 3, "s": False, "w": None},
                  {"g": "Gare Deux", "p": _iso(4).replace("Z", "+00:00"), "r": 3, "s": False, "w": None}]
        _, inserts = await self._executer(_flux(apres), anciens=[(uid, connus)])
        params = inserts[-1].compile(dialect=postgresql.dialect()).params
        assert [(a["g"], a.get("k")) for a in params["arrets"]] == [("Gare Un", None), ("Gare Deux", True),
                                                                    ("Gare Trois", None)]

    async def test_chaque_ligne_archivee_avec_ses_seuls_trains(self):
        import json

        rer_a = _train(1, [_appel(1, 0)])
        bus = _train(2, [_appel(1, 0)], ligne="C00001")
        with patch.object(collector, "archiver_flux") as archive:
            await self._executer(_flux(rer_a, bus))
        assert archive.call_count == len(LIGNES_CIBLES)
        par_ligne = {c.args[0]: trains_du_flux(json.loads(c.args[1])) for c in archive.call_args_list}
        assert set(par_ligne) == set(LIGNES_CIBLES.values())
        assert par_ligne["RER_A"] == [rer_a]
        assert par_ligne["RER_B"] == []

    async def test_retard_rattrape_met_a_jour_le_train_en_base(self):
        """Train déjà en base, plus aucun retard dans la fenêtre : ses arrêts reçoivent la dernière mesure."""
        from sqlalchemy.sql.dml import Update
        from sqlalchemy.dialects import postgresql

        t = _train(1, [_appel(1, 0, retard=1), _appel(2, 10, terminus=True)])
        uid = "rt_vehicle_journey:IDFM:TN:SNCF:00000000-0000-0000-0000-000000000001_20260917"
        ancien = [{"g": "Gare Un", "p": T0.isoformat(), "r": 4, "s": False, "w": None}]
        executes = []
        _, inserts = await self._executer(_flux(t), anciens=[(uid, ancien)], executes=executes)
        assert inserts == []
        updates = [e for e in executes if isinstance(e, Update)]
        assert len(updates) == 1
        params = updates[0].compile(dialect=postgresql.dialect()).params
        assert [a["r"] for a in params["arrets"]] == [1, 0]

    async def test_train_sans_retard_absent_de_la_base_non_ecrit(self):
        from sqlalchemy.sql.dml import Update

        t = _train(1, [_appel(1, 0, retard=1), _appel(2, 10, terminus=True)])
        executes = []
        _, inserts = await self._executer(_flux(t), executes=executes)
        assert inserts == []
        assert not [e for e in executes if isinstance(e, Update)]

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


class TestFluxGlobal:
    def test_trains_par_ligne(self):
        rer_a, ligne_u, bus = _train(1, []), _train(2, [], ligne="C01741"), _train(3, [], ligne="C00001")
        sans_ligne = {k: v for k, v in _train(4, []).items() if k != "LineRef"}
        par_ligne = collector.trains_par_ligne([rer_a, ligne_u, bus, sans_ligne])
        assert dict(par_ligne) == {"RER_A": [rer_a], "TRANSILIEN_U": [ligne_u]}

    def test_flux_reduit_relisible(self):
        t = _train(1, [_appel(1, 0)])
        assert trains_du_flux(collector.flux_siri([t])) == [t]


class TestRedemarrage:
    """Un redémarrage ne refait pas un relevé écrit il y a moins d'un intervalle (quota PRIM)."""

    async def _recent(self, dernier):
        import backend.main as main
        with patch.object(main, "dernier_releve", AsyncMock(return_value=dernier)):
            return await main._releve_recent("realtime", 5)

    async def test_releve_recent_pas_refait(self):
        assert await self._recent(datetime.now(timezone.utc) - timedelta(minutes=2)) is True

    async def test_releve_ancien_refait(self):
        assert await self._recent(datetime.now(timezone.utc) - timedelta(minutes=6)) is False

    async def test_base_vide_releve_fait(self):
        assert await self._recent(None) is False

    async def test_erreur_de_lecture_releve_fait(self):
        import backend.main as main
        with patch.object(main, "dernier_releve", AsyncMock(side_effect=RuntimeError("base injoignable"))):
            assert await main._releve_recent("realtime", 5) is False
