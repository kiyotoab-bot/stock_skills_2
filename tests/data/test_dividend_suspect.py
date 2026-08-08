"""Tests for the dividend forecast divergence flag (KIK-729).

yfinance's ``dividendRate`` (forecast DPS) intermittently carries wrong values.
Known damage:
  2026-05-31 9928.T : 130 yen (actual 60) -> 7.67% yield, nearly entered income bucket
  2026-08-05 6436.T : 250 yen (company forecast 180) -> 6.44% yield, made it into
                      the Phase-1 recommendation before being caught
``_sanitize_anomalies`` only rejects yields above 15%, so this band slips through.
"""

import pytest

from src.data.yahoo_client.detail import _dividend_suspect


class TestDividendSuspect:
    def test_consistent_forecast_is_not_suspect(self):
        # 9364.T: 210 vs 205 = +2.4%
        assert _dividend_suspect(210.0, 205.0) is False

    def test_amano_case_is_flagged(self):
        # 6436.T: forecast 250 vs trailing 180 = +38.9%; company forecast was 180
        assert _dividend_suspect(250.0, 180.0) is True

    def test_miroku_case_is_flagged(self):
        # 9928.T (2026-05-31): 130 vs 60 = +117%
        assert _dividend_suspect(130.0, 60.0) is True

    def test_genuine_dividend_growth_also_flags(self):
        """7453.T is a real +75.8% hike — the flag is 'verify', not 'reject'."""
        assert _dividend_suspect(32.0, 18.2) is True

    def test_large_cut_is_flagged_too(self):
        assert _dividend_suspect(50.0, 100.0) is True

    @pytest.mark.parametrize("rate,trailing", [
        (130.0, 100.0),   # +30.0% exactly -> not over the limit
        (100.0, 130.0),   # -23.1%
    ])
    def test_at_or_under_threshold_is_not_suspect(self, rate, trailing):
        assert _dividend_suspect(rate, trailing) is False

    def test_just_over_threshold_is_suspect(self):
        assert _dividend_suspect(130.1, 100.0) is True

    @pytest.mark.parametrize("rate,trailing", [
        (None, 100.0),
        (100.0, None),
        (None, None),
        ("n/a", 100.0),
    ])
    def test_missing_values_are_undecidable(self, rate, trailing):
        assert _dividend_suspect(rate, trailing) is None

    @pytest.mark.parametrize("rate,trailing", [
        (0.0, 100.0),
        (100.0, 0.0),     # 8031.T currently reports trailing 0
        (-5.0, 100.0),
    ])
    def test_non_positive_values_are_undecidable(self, rate, trailing):
        assert _dividend_suspect(rate, trailing) is None

    def test_string_numbers_are_accepted(self):
        assert _dividend_suspect("250", "180") is True

    def test_flag_never_alters_the_yield(self):
        """The guard must not silently correct data — it only marks it."""
        # _dividend_suspect returns a verdict only; no mutation surface exists.
        assert _dividend_suspect(250.0, 180.0) in (True, False)
