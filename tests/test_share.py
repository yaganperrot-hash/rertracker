"""Tests pour backend/share.py — génération des cartes de partage."""
import io
from datetime import date

import pytest
from PIL import Image

from backend.share import (
    LINE_COLORS,
    FORMATS,
    compute_card_data,
    render_card,
    effective_date,
    _fmt,
    _fmt_euros_compact,
    _jours_smic_label,
    _classement_label,
    _accroche,
    _date_label,
)


# ── Helpers de formatage ──

class TestFmt:
    def test_fmt_small(self):
        assert _fmt(42) == "42"

    def test_fmt_thousands(self):
        assert _fmt(142681) == "142\u202f681"

    def test_fmt_millions(self):
        assert _fmt(1204567) == "1\u202f204\u202f567"


class TestFmtEurosCompact:
    def test_below_million(self):
        assert "142" in _fmt_euros_compact(142681)
        assert "€" in _fmt_euros_compact(142681)

    def test_million(self):
        result = _fmt_euros_compact(1_200_000)
        assert "M€" in result

    def test_ten_millions(self):
        result = _fmt_euros_compact(12_000_000)
        assert "M€" in result


class TestJoursSmicLabel:
    def test_jours(self):
        assert "87 jours" == _jours_smic_label(87)

    def test_mois(self):
        result = _jours_smic_label(400)
        assert "mois" in result

    def test_ans(self):
        result = _jours_smic_label(1000)
        assert "ans" in result


class TestClassement:
    def test_premier(self):
        assert _classement_label(1, 13) == "1ʳᵉ pire ligne / 13"

    def test_quatrieme(self):
        assert _classement_label(4, 13) == "4ᵉ pire ligne / 13"


class TestAccroche:
    def test_rer(self):
        assert _accroche("RER_A") == "le RER A"

    def test_transilien(self):
        assert _accroche("TRANSILIEN_P") == "la Transilien P"


class TestDateLabel:
    def test_format(self):
        result = _date_label(date(2026, 10, 19))
        assert "LUNDI" in result
        assert "19" in result
        assert "OCT." in result
        assert "2026" in result


# ── compute_card_data ──

class TestComputeCardData:
    METRICS = [
        {"line_id": "RER_A", "minutes_voyageurs": 695432, "cout_eur": 142681},
        {"line_id": "RER_B", "minutes_voyageurs": 50000, "cout_eur": 10250},
        {"line_id": "RER_C", "minutes_voyageurs": 0, "cout_eur": 0},
    ]

    def test_basic(self):
        data = compute_card_data("RER_A", date(2026, 10, 19), self.METRICS)
        assert data["cout_eur"] == 142681
        assert data["rang"] == 1
        assert data["total_lignes"] == 3
        assert data["jours_smic"] > 0

    def test_zero_cost(self):
        data = compute_card_data("RER_C", date(2026, 10, 19), self.METRICS)
        assert data["cout_eur"] == 0
        assert data["jours_smic"] == 0

    def test_missing_line(self):
        data = compute_card_data("TRANSILIEN_H", date(2026, 10, 19), self.METRICS)
        assert data["cout_eur"] == 0
        assert data["rang"] is None


# ── render_card ──

class TestRenderCard:
    DATA = {
        "line_id": "RER_A",
        "date": date(2026, 10, 19),
        "cout_eur": 142681,
        "minutes_voyageurs": 695432,
        "jours_smic": 1655,
        "rang": 1,
        "total_lignes": 13,
    }

    @pytest.mark.parametrize("fmt,expected_w,expected_h", [
        ("square", 1080, 1080),
        ("story", 1080, 1920),
        ("og", 1200, 630),
    ])
    def test_format_dimensions(self, fmt, expected_w, expected_h):
        png = render_card(self.DATA, fmt)
        assert png[:8] == b'\x89PNG\r\n\x1a\n'  # valid PNG header
        img = Image.open(io.BytesIO(png))
        assert img.size == (expected_w, expected_h)
        assert img.mode == "RGB"

    def test_invalid_format_falls_back(self):
        png = render_card(self.DATA, "invalid")
        img = Image.open(io.BytesIO(png))
        assert img.size == (1080, 1080)  # defaults to square

    def test_zero_cost_renders(self):
        data = {**self.DATA, "cout_eur": 0, "jours_smic": 0, "rang": None}
        for fmt in ("square", "story", "og"):
            png = render_card(data, fmt)
            assert len(png) > 1000  # valid PNG with content

    @pytest.mark.parametrize("line_id", list(LINE_COLORS.keys()))
    def test_all_lines_render(self, line_id):
        data = {
            "line_id": line_id,
            "date": date(2026, 10, 19),
            "cout_eur": 50000,
            "minutes_voyageurs": 100000,
            "jours_smic": 580,
            "rang": 5,
            "total_lignes": 13,
        }
        png = render_card(data, "square")
        assert png[:8] == b'\x89PNG\r\n\x1a\n'

    def test_large_amount_auto_sizes(self):
        """Un montant très élevé ne doit pas planter (auto-sizing)."""
        data = {**self.DATA, "cout_eur": 999_999_999}
        png = render_card(data, "square")
        assert len(png) > 1000


# ── effective_date ──

class TestEffectiveDate:
    def test_returns_date(self):
        d = effective_date()
        assert isinstance(d, date)
