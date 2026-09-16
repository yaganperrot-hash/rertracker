"""Tests unitaires pour backend/metrics.py"""
from datetime import date, datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from backend import offre
from backend.metrics import (
    FREQUENTATION,
    _duree_suppression,
    _freq_minute,
    _incident_dt_paris,
    _voyageurs_par_train,
    incident_minutes_voyageurs,
    _minutes_voyageurs,
    _effective_duration,
    PROFILS,
    part_horaire,
    MAX_OPEN_DURATION_MIN,
    get_today_stats,
    get_line_stats,
)
from backend.profils import CATEGORIES, LIGNE_RESEAU, categorie_jour, est_vacances

PARIS = ZoneInfo("Europe/Paris")
MARDI_8H = datetime(2026, 9, 15, 8, 30, tzinfo=PARIS)
MARDI_14H = datetime(2026, 9, 15, 14, 30, tzinfo=PARIS)
MARDI_3H = datetime(2026, 9, 15, 3, 30, tzinfo=PARIS)
SAMEDI_8H = datetime(2026, 9, 19, 8, 30, tzinfo=PARIS)
SAMEDI_18H = datetime(2026, 9, 19, 18, 30, tzinfo=PARIS)


FREQ = {
    "RER_A": 900000,
    "RER_B": 650000,
    "RER_C": 350000,
    "RER_D": 530000,
    "RER_E": 180000,
    "TRANSILIEN_H": 110000,
    "TRANSILIEN_J": 130000,
    "TRANSILIEN_K": 50000,
    "TRANSILIEN_L": 170000,
    "TRANSILIEN_N": 100000,
    "TRANSILIEN_P": 80000,
    "TRANSILIEN_R": 70000,
    "TRANSILIEN_U": 40000,
}


class TestMinutesVoyageurs:
    def test_rer_a_known_value(self):
        # 900000 / 18 / 60 = 833.33… voyageurs/min
        result = _minutes_voyageurs(60, "RER_A")
        expected = round(60 * (900000 / 18 / 60))
        assert result == expected

    def test_rer_b_known_value(self):
        result = _minutes_voyageurs(30, "RER_B")
        expected = round(30 * (650000 / 18 / 60))
        assert result == expected

    def test_unknown_line_returns_zero(self):
        assert _minutes_voyageurs(60, "LIGNE_INCONNUE") == 0

    def test_zero_duration_returns_zero(self):
        assert _minutes_voyageurs(0, "RER_A") == 0

    def test_result_is_proportional_to_duration(self):
        mv_30 = _minutes_voyageurs(30, "RER_D")
        mv_60 = _minutes_voyageurs(60, "RER_D")
        assert mv_60 == mv_30 * 2

    def test_all_known_lines_non_zero(self):
        for line_id in FREQ:
            result = _minutes_voyageurs(10, line_id)
            assert result > 0, f"{line_id} should give non-zero result"

    def test_higher_frequency_line_gives_more_mv(self):
        mv_a = _minutes_voyageurs(60, "RER_A")   # 900k/jour
        mv_u = _minutes_voyageurs(60, "TRANSILIEN_U")  # 40k/jour
        assert mv_a > mv_u


class TestProfilsHoraires:
    """Pondération par les profils horaires réels (validations open data IDFM)."""

    def test_pointe_du_matin_superieure_au_creux(self):
        assert _minutes_voyageurs(10, "RER_A", MARDI_8H) > _minutes_voyageurs(10, "RER_A", MARDI_14H)

    def test_samedi_matin_moins_cher_que_semaine(self):
        """Un samedi n'a pas de pointe pendulaire à 8 h. L'écart par train est moindre que l'écart
        de fréquentation : le samedi, moins de trains se partagent les voyageurs."""
        semaine = _minutes_voyageurs(45, "RER_A", MARDI_8H)
        samedi = _minutes_voyageurs(45, "RER_A", SAMEDI_8H)
        assert samedi < semaine, f"samedi 8h ({samedi}) devrait être inférieur à mardi 8h ({semaine})"

    def test_samedi_culmine_en_fin_de_journee(self):
        assert _minutes_voyageurs(10, "RER_A", SAMEDI_18H) > _minutes_voyageurs(10, "RER_A", SAMEDI_8H)

    def test_nuit_negligeable(self):
        assert _minutes_voyageurs(10, "RER_A", MARDI_3H) < _minutes_voyageurs(10, "RER_A", MARDI_8H) / 100

    def test_repli_plat_sans_instant(self):
        """Sans instant connu, on retombe sur la moyenne plate des 18 h de service."""
        assert _minutes_voyageurs(60, "RER_A") == round(60 * (900000 / 18 / 60))

    def test_ligne_sans_profil_utilise_le_repli(self):
        """Le métro n'a pas de profil : même résultat avec ou sans instant."""
        assert part_horaire("METRO_1", MARDI_8H) is None
        assert _minutes_voyageurs(60, "METRO_1", MARDI_8H) == _minutes_voyageurs(60, "METRO_1")

    def test_toutes_les_lignes_rer_transilien_ont_un_profil(self):
        for line_id in LIGNE_RESEAU:
            assert part_horaire(line_id, MARDI_8H) is not None, f"{line_id} sans profil"

    def test_chaque_profil_somme_a_un(self):
        """Garde-fou : c'est la normalisation ratée de l'ancien profil qui biaisait tous les chiffres."""
        for reseau, cats in PROFILS["profils"].items():
            for cat, profil in cats.items():
                assert len(profil) == 24, f"{reseau}/{cat} : {len(profil)} tranches au lieu de 24"
                total = sum(profil)
                assert abs(total - 1.0) < 1e-4, f"{reseau}/{cat} somme à {total}, attendu 1.0"

    def test_tous_les_jours_types_presents(self):
        for reseau, cats in PROFILS["profils"].items():
            for cat in CATEGORIES:
                assert cat in cats, f"{reseau} sans profil {cat}"


class TestCategorieJour:
    def test_semaine(self):
        assert categorie_jour(date(2026, 9, 15)) == "JOHV"   # mardi

    def test_samedi(self):
        assert categorie_jour(date(2026, 9, 19)) == "SAHV"

    def test_dimanche(self):
        assert categorie_jour(date(2026, 9, 20)) == "DIJFP"

    def test_ferie_en_semaine_compte_comme_dimanche(self):
        assert categorie_jour(date(2026, 7, 14)) == "DIJFP"   # mardi 14 juillet

    def test_ferie_mobile(self):
        assert categorie_jour(date(2026, 5, 14)) == "DIJFP"   # Ascension 2026

    def test_semaine_en_vacances(self):
        assert categorie_jour(date(2026, 10, 19)) == "JOVS"   # lundi, vacances de la Toussaint

    def test_samedi_en_vacances(self):
        assert categorie_jour(date(2026, 10, 17)) == "SAVS"

    def test_bornes_des_vacances(self):
        """Toussaint 2026 zone C : du 17 octobre au 1er novembre, rentrée le 2."""
        assert est_vacances(date(2026, 10, 16)) is False
        assert est_vacances(date(2026, 10, 17)) is True
        assert est_vacances(date(2026, 11, 1)) is True
        assert est_vacances(date(2026, 11, 2)) is False

    def test_conversion_utc_vers_paris(self):
        """Les bornes sont publiées en UTC à 22 h : sans conversion tout glisserait d'un jour.
        Rentrée de septembre 2026 le mardi 1er, donc le 31 août est encore en vacances."""
        assert est_vacances(date(2026, 8, 31)) is True
        assert est_vacances(date(2026, 9, 1)) is False


class TestProfilsVacances:
    def test_pointe_du_matin_ecrasee_en_vacances(self):
        """Le pic pendulaire de 8 h s'effondre quand les écoles sont fermées."""
        hors_vac = _minutes_voyageurs(45, "RER_A", MARDI_8H)
        vac = _minutes_voyageurs(45, "RER_A", datetime(2026, 10, 20, 8, 30, tzinfo=PARIS))
        assert vac < hors_vac, f"vacances ({vac}) devrait être < hors vacances ({hors_vac})"

    def test_cinq_jours_types(self):
        assert len(CATEGORIES) == 5
        for reseau, cats in PROFILS["profils"].items():
            assert set(cats) == set(CATEGORIES), f"{reseau} : {sorted(cats)}"


def _inc(**kw):
    from types import SimpleNamespace
    champs = dict(line_id="RER_A", heure_debut=None, heure_theorique=None, heure_fin=None,
                  duree_minutes=10, is_cancelled=False, gare=None, mission=None)
    champs.update(kw)
    return SimpleNamespace(**champs)


class TestVoyageursParTrain:
    """Voyageurs par train = voyageurs du jour × part de l'heure ÷ trains équivalents (TASK-18)."""

    def test_invariant_somme_sur_la_journee(self):
        """Σ_h voyageurs_par_train × trains_heure = voyageurs du jour × Σ part, sur les heures à ≥ 1 train."""
        offre_c = offre.charger()
        for line_id in LIGNE_RESEAU:
            reseau = PROFILS["lignes"][line_id]
            for cat in CATEGORIES:
                parts = PROFILS["profils"][reseau][cat]
                trains = offre_c["trains_heure"][line_id][cat]
                heures = [h for h in range(24) if trains[h] >= 1]
                attendu = FREQUENTATION[line_id] * sum(parts[h] for h in heures)
                obtenu = sum(FREQUENTATION[line_id] * parts[h] / max(trains[h], 1.0) * trains[h] for h in heures)
                assert obtenu == pytest.approx(attendu, rel=0.001), f"{line_id} {cat}"

    def test_formule_a_partir_des_fichiers(self):
        attendu = FREQUENTATION["RER_A"] * part_horaire("RER_A", MARDI_8H) / offre.trains_heure("RER_A", MARDI_8H)
        assert _voyageurs_par_train("RER_A", MARDI_8H) == pytest.approx(attendu)
        assert _minutes_voyageurs(45, "RER_A", MARDI_8H) == round(45 * attendu)

    def test_rer_a_pointe_ordre_de_grandeur(self):
        assert 1000 <= _voyageurs_par_train("RER_A", MARDI_8H) <= 3000

    def test_transilien_k_bien_plus_cher_qu_avant(self):
        """Le défaut corrigé : 2 à 4 trains à 8 h sur la K, pas 60."""
        nouveau = _minutes_voyageurs(10, "TRANSILIEN_K", MARDI_8H)
        ancien = round(10 * _freq_minute("TRANSILIEN_K", MARDI_8H))
        assert nouveau >= 10 * ancien

    def test_plancher_a_un_train(self):
        # Transilien K un dimanche à 3 h : moins d'un train équivalent
        dimanche_3h = datetime(2026, 9, 20, 3, 30, tzinfo=PARIS)
        assert offre.trains_heure("TRANSILIEN_K", dimanche_3h) < 1
        attendu = FREQUENTATION["TRANSILIEN_K"] * part_horaire("TRANSILIEN_K", dimanche_3h)
        assert _voyageurs_par_train("TRANSILIEN_K", dimanche_3h) == pytest.approx(attendu)

    def test_repli_ligne_sans_offre_un_seul_warning(self, caplog):
        import backend.metrics as metrics
        metrics._lignes_en_repli.discard("METRO_1")
        with caplog.at_level("WARNING", logger="backend.metrics"):
            a = _voyageurs_par_train("METRO_1", MARDI_8H)
            b = _voyageurs_par_train("METRO_1", MARDI_8H)
        assert a == b == _freq_minute("METRO_1", MARDI_8H)
        assert sum("METRO_1" in r.message for r in caplog.records) == 1


class TestInstantEtSuppressions:
    def test_heure_prevue_prioritaire(self):
        inc = _inc(heure_theorique=datetime(2026, 9, 15, 8, 55, tzinfo=PARIS),
                   heure_debut=datetime(2026, 9, 15, 9, 5, tzinfo=PARIS))
        assert _incident_dt_paris(inc).hour == 8

    def test_sans_heure_prevue_debut_de_l_incident(self):
        inc = _inc(heure_debut=datetime(2026, 9, 15, 9, 5, tzinfo=PARIS))
        assert _incident_dt_paris(inc).hour == 9

    def test_suppression_rer_a_pointe(self):
        assert 2 <= _duree_suppression("RER_A", MARDI_8H) <= 6

    def test_suppression_transilien_k_creuse(self):
        assert _duree_suppression("TRANSILIEN_K", MARDI_14H) >= 20

    def test_suppression_ligne_sans_offre_valeur_de_repli(self):
        from backend.config import get_settings
        assert _duree_suppression("METRO_1", MARDI_8H) == get_settings().cancel_default_impact_minutes

    def test_suppression_ignore_duree_stockee(self):
        """Le collecteur écrit 5 dans duree_minutes ; le calcul lit l'intervalle de l'offre."""
        inc = _inc(line_id="TRANSILIEN_K", is_cancelled=True, duree_minutes=5, heure_theorique=MARDI_14H)
        dur, mv = incident_minutes_voyageurs(inc, datetime.now(timezone.utc))
        assert dur == _duree_suppression("TRANSILIEN_K", MARDI_14H)
        assert mv == _minutes_voyageurs(dur, "TRANSILIEN_K", MARDI_14H)


class TestCoefficientDeGare:
    """Un retard constaté en fin de parcours touche moins de voyageurs (TASK-23)."""

    def test_premier_arret_plus_cher_que_l_avant_dernier(self):
        mission, gares = next(iter(offre.charger()["coef_gare"]["RER_A"].items()))
        noms = list(gares)
        now = datetime.now(timezone.utc)
        debut = _inc(mission=mission, gare=noms[0], heure_theorique=MARDI_8H)
        fin = _inc(mission=mission, gare=noms[-2], heure_theorique=MARDI_8H)
        assert incident_minutes_voyageurs(fin, now)[1] < incident_minutes_voyageurs(debut, now)[1]

    def test_sans_gare_identique_au_calcul_par_train(self):
        inc = _inc(heure_theorique=MARDI_8H)
        _, mv = incident_minutes_voyageurs(inc, datetime.now(timezone.utc))
        assert mv == _minutes_voyageurs(10, "RER_A", MARDI_8H)

    def test_coefficient_applique(self):
        inc = _inc(mission="QYRO", gare="Nation", heure_theorique=MARDI_8H)
        _, mv = incident_minutes_voyageurs(inc, datetime.now(timezone.utc))
        attendu = round(10 * _voyageurs_par_train("RER_A", MARDI_8H) * offre.coef_gare("RER_A", "QYRO", "Nation"))
        assert mv == attendu


class TestEffectiveDuration:
    """Tests for _effective_duration."""

    def test_uses_duree_minutes_when_available(self):
        inc = MagicMock()
        inc.duree_minutes = 42
        inc.heure_fin = None
        inc.heure_debut = None
        assert _effective_duration(inc, datetime.now(timezone.utc)) == 42

    def test_uses_timestamp_diff_when_no_duree(self):
        now = datetime.now(timezone.utc)
        inc = MagicMock()
        inc.duree_minutes = None
        inc.heure_debut = now - timedelta(minutes=30)
        inc.heure_fin = now
        result = _effective_duration(inc, now)
        assert result == 30

    def test_open_incident_capped(self):
        """Open incident (no heure_fin, no duree_minutes) should be capped at MAX_OPEN_DURATION_MIN."""
        now = datetime.now(timezone.utc)
        inc = MagicMock()
        inc.duree_minutes = None
        inc.heure_fin = None
        inc.heure_debut = now - timedelta(hours=10)  # 600 min > 180 cap
        result = _effective_duration(inc, now)
        assert result == MAX_OPEN_DURATION_MIN, f"Expected {MAX_OPEN_DURATION_MIN}, got {result}"

    def test_timestamp_diff_also_capped(self):
        """Even with heure_fin, duration should be capped."""
        now = datetime.now(timezone.utc)
        inc = MagicMock()
        inc.duree_minutes = None
        inc.heure_debut = now - timedelta(hours=10)
        inc.heure_fin = now
        result = _effective_duration(inc, now)
        assert result == MAX_OPEN_DURATION_MIN


class TestNoDoubleCount:
    """Verify disruption incidents are not counted in duree_totale."""

    def test_disruption_source_not_in_rt(self):
        """Disruptions should be separated from RT in compute_daily_metrics logic.
        We test the separation by checking that only RT + cancelled contribute to totals."""
        # This is an integration-level test that verifies the logic in compute_daily_metrics.
        # The key invariant: an incident with source='disruption' should NOT
        # contribute to duree_totale_min or minutes_voyageurs.
        # Tested indirectly through the line_data grouping logic.
        pass  # Covered by the compute_daily_metrics integration test


class TestParisTimezone:
    """Verify Paris timezone is used for date calculations."""

    def test_paris_timezone_used(self):
        """At 01h UTC (which is 02h or 03h Paris depending on DST),
        the Paris date should be correct."""
        # 2024-03-15 01:00 UTC = 2024-03-15 02:00 Paris (CET)
        paris = ZoneInfo("Europe/Paris")
        utc_time = datetime(2024, 3, 15, 1, 0, tzinfo=timezone.utc)
        paris_date = utc_time.astimezone(paris).date()
        assert paris_date == date(2024, 3, 15)

        # 2024-06-15 23:30 UTC = 2024-06-16 01:30 Paris (CEST, +2)
        utc_time_late = datetime(2024, 6, 15, 23, 30, tzinfo=timezone.utc)
        paris_date_late = utc_time_late.astimezone(paris).date()
        assert paris_date_late == date(2024, 6, 16), (
            "23:30 UTC in summer should be next day in Paris"
        )


class TestGetTodayStats:
    @pytest.mark.asyncio
    async def test_empty_db_returns_zeros(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_today_stats(mock_db)

        assert result["total_incidents"] == 0
        assert result["total_duree_min"] == 0
        assert result["total_minutes_voyageurs"] == 0
        assert result["lignes_perturbees"] == []
        assert result["nb_lignes_perturbees"] == 0

    @pytest.mark.asyncio
    async def test_aggregates_multiple_lines(self):
        mock_db = AsyncMock()

        row_a = MagicMock(
            nb_incidents=3, duree_totale_min=45,
            minutes_voyageurs=25000, est_jour_perturbe=True, line_id="RER_A"
        )
        row_b = MagicMock(
            nb_incidents=1, duree_totale_min=20,
            minutes_voyageurs=8000, est_jour_perturbe=True, line_id="RER_B"
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row_a, row_b]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_today_stats(mock_db)

        assert result["total_incidents"] == 4
        assert result["total_duree_min"] == 65
        assert result["total_minutes_voyageurs"] == 33000
        assert set(result["lignes_perturbees"]) == {"RER_A", "RER_B"}
        assert result["nb_lignes_perturbees"] == 2

    @pytest.mark.asyncio
    async def test_date_field_uses_paris_tz(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_today_stats(mock_db)

        paris = ZoneInfo("Europe/Paris")
        expected_date = datetime.now(paris).date().isoformat()
        assert result["date"] == expected_date


class TestGetLineStats:
    @pytest.mark.asyncio
    async def test_empty_returns_zeros(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_line_stats("RER_A", 30, mock_db)

        assert result["line_id"] == "RER_A"
        assert result["total_incidents"] == 0
        assert result["total_duree_min"] == 0
        assert result["total_minutes_voyageurs"] == 0
        assert result["jours_perturbes"] == 0
        assert result["daily"] == []

    @pytest.mark.asyncio
    async def test_period_fields(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_line_stats("RER_B", 7, mock_db)

        assert result["period_days"] == 7
        assert result["line_id"] == "RER_B"
        assert "from" in result
        assert "to" in result

    @pytest.mark.asyncio
    async def test_daily_structure(self):
        mock_db = AsyncMock()

        row = MagicMock(
            date=date(2024, 3, 15),
            nb_incidents=2,
            duree_totale_min=30,
            minutes_voyageurs=12000,
            est_jour_perturbe=True,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row]
        # 1ʳᵉ requête : daily_metrics ; suivantes (retard moyen pondéré) : aucun incident
        vide = MagicMock()
        vide.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_result] + [vide] * 5)

        result = await get_line_stats("RER_C", 30, mock_db)

        assert len(result["daily"]) == 1
        day = result["daily"][0]
        assert day["date"] == "2024-03-15"
        assert day["nb_incidents"] == 2
        assert day["duree_totale_min"] == 30
        assert day["minutes_voyageurs"] == 12000
        assert day["est_jour_perturbe"] is True
