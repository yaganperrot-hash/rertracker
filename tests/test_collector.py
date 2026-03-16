"""Tests unitaires pour backend/collector.py"""
from datetime import datetime, timezone

import pytest

from backend.collector import _parse_dt, _extract_line_id, LIGNES_CIBLES


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
