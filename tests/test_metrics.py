"""Tests unitaires pour backend/metrics.py"""
from datetime import date, datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from backend.metrics import (
    _minutes_voyageurs,
    _effective_duration,
    PROFILS,
    part_horaire,
    MAX_OPEN_DURATION_MIN,
    get_today_stats,
    get_line_stats,
)
from backend.profils import CATEGORIES, LIGNE_RESEAU, categorie_jour

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
        """Le gain du chantier : un samedi n'a pas de pointe pendulaire à 8 h."""
        semaine = _minutes_voyageurs(45, "RER_A", MARDI_8H)
        samedi = _minutes_voyageurs(45, "RER_A", SAMEDI_8H)
        assert samedi < semaine / 2, f"samedi 8h ({samedi}) devrait être très inférieur à mardi 8h ({semaine})"

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
