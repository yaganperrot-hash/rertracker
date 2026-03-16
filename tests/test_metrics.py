"""Tests unitaires pour backend/metrics.py"""
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.metrics import _minutes_voyageurs, get_today_stats, get_line_stats


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
    async def test_date_field_is_today(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_today_stats(mock_db)

        assert result["date"] == date.today().isoformat()


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
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_line_stats("RER_C", 30, mock_db)

        assert len(result["daily"]) == 1
        day = result["daily"][0]
        assert day["date"] == "2024-03-15"
        assert day["nb_incidents"] == 2
        assert day["duree_totale_min"] == 30
        assert day["minutes_voyageurs"] == 12000
        assert day["est_jour_perturbe"] is True
