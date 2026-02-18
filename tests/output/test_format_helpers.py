"""Tests for shared format helpers (KIK-394)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.output._format_helpers import fmt_pct, fmt_float, fmt_pct_sign, fmt_float_sign, hhi_bar, build_label


class TestFmtPct:
    def test_normal(self):
        assert fmt_pct(0.035) == "3.50%"

    def test_none(self):
        assert fmt_pct(None) == "-"

    def test_zero(self):
        assert fmt_pct(0.0) == "0.00%"

    def test_negative(self):
        assert fmt_pct(-0.12) == "-12.00%"


class TestFmtFloat:
    def test_normal(self):
        assert fmt_float(3.14159) == "3.14"

    def test_none(self):
        assert fmt_float(None) == "-"

    def test_custom_decimals(self):
        assert fmt_float(3.14159, decimals=4) == "3.1416"


class TestFmtPctSign:
    def test_positive(self):
        assert fmt_pct_sign(0.12) == "+12.00%"

    def test_negative(self):
        assert fmt_pct_sign(-0.05) == "-5.00%"

    def test_none(self):
        assert fmt_pct_sign(None) == "-"

    def test_zero(self):
        assert fmt_pct_sign(0.0) == "+0.00%"


class TestFmtFloatSign:
    def test_positive(self):
        assert fmt_float_sign(1.5) == "+1.50"

    def test_negative(self):
        assert fmt_float_sign(-2.3) == "-2.30"

    def test_none(self):
        assert fmt_float_sign(None) == "-"

    def test_custom_decimals(self):
        assert fmt_float_sign(1.5, decimals=1) == "+1.5"


class TestBuildLabel:
    """Tests for build_label() (KIK-418/419)."""

    def test_basic_label(self):
        row = {"symbol": "7203.T", "name": "Toyota Motor"}
        assert build_label(row) == "7203.T Toyota Motor"

    def test_no_name(self):
        row = {"symbol": "7203.T", "name": None}
        assert build_label(row) == "7203.T"

    def test_with_markers(self):
        row = {"symbol": "7203.T", "name": "Toyota", "_note_markers": "\u26a0\ufe0f"}
        result = build_label(row)
        assert "7203.T Toyota" in result
        assert "\u26a0\ufe0f" in result

    def test_empty_markers(self):
        row = {"symbol": "7203.T", "name": "Toyota", "_note_markers": ""}
        assert build_label(row) == "7203.T Toyota"

    def test_multiple_markers(self):
        row = {"symbol": "AAPL", "name": "Apple", "_note_markers": "\u26a0\ufe0f\U0001f4dd"}
        result = build_label(row)
        assert "\u26a0\ufe0f" in result
        assert "\U0001f4dd" in result

    def test_missing_symbol(self):
        row = {}
        assert build_label(row) == "-"


class TestHhiBar:
    def test_zero(self):
        assert hhi_bar(0.0) == "[..........]"

    def test_full(self):
        assert hhi_bar(1.0) == "[##########]"

    def test_half(self):
        assert hhi_bar(0.5) == "[#####.....]"

    def test_custom_width(self):
        assert hhi_bar(0.5, width=4) == "[##..]"
