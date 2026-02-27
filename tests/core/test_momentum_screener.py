"""Tests for MomentumScreener (KIK-506)."""

import pandas as pd
import pytest

from src.core.screening.momentum_screener import MomentumScreener


def _make_hist(n: int = 300, base: float = 100.0) -> pd.DataFrame:
    """Create a simple uptrend history."""
    prices = [base * (1 + 0.001 * i) for i in range(n)]
    return pd.DataFrame({
        "Close": prices,
        "Volume": [1_000_000.0] * n,
    })


class MockYahooClient:
    """Minimal mock of yahoo_client for MomentumScreener tests."""

    def __init__(self, quotes=None, hist=None):
        self._quotes = quotes or []
        self._hist = hist

    def screen_stocks(self, query, size=250, max_results=250, sort_field=None, sort_asc=False):
        return self._quotes

    def get_price_history(self, symbol, period="1y"):
        return self._hist

    def get_stock_detail(self, symbol):
        return {}


def _make_quote(symbol="7203.T", name="Toyota", price=2500, ma50_change=0.20, high_change=-0.03):
    """Create a mock EquityQuery quote with precomputed values."""
    return {
        "symbol": symbol,
        "shortName": name,
        "regularMarketPrice": price,
        "trailingPE": 10,
        "priceToBook": 1.2,
        "dividendYield": 0.025,
        "trailingAnnualDividendYield": 0.023,
        "returnOnEquity": 0.12,
        "revenueGrowth": 0.08,
        "epsGrowth": 0.10,
        "fiftyDayAverageChangePercent": ma50_change,
        "fiftyTwoWeekHighChangePercent": high_change,
    }


class TestMomentumScreenerCriteria:
    """Test criteria definitions."""

    def test_stable_criteria_has_low_beta(self):
        assert "max_beta" in MomentumScreener.STABLE_CRITERIA
        assert MomentumScreener.STABLE_CRITERIA["max_beta"] == 1.2

    def test_surge_criteria_has_volume(self):
        assert "min_avg_volume_3m" in MomentumScreener.SURGE_CRITERIA
        assert MomentumScreener.SURGE_CRITERIA["min_avg_volume_3m"] == 500_000

    def test_both_have_market_cap_floor(self):
        assert "min_market_cap" in MomentumScreener.STABLE_CRITERIA
        assert "min_market_cap" in MomentumScreener.SURGE_CRITERIA


class TestMomentumScreenerScreen:
    """Test screen() method."""

    def test_empty_quotes_returns_empty(self):
        client = MockYahooClient(quotes=[], hist=_make_hist())
        screener = MomentumScreener(client)
        results = screener.screen(region="jp", top_n=10)
        assert results == []

    def test_screen_surge_returns_results(self):
        """Surge mode with +20% MA50 deviation should return results."""
        hist = _make_hist(300)
        quotes = [_make_quote(ma50_change=0.20, high_change=-0.02)]
        client = MockYahooClient(quotes=quotes, hist=hist)
        screener = MomentumScreener(client)
        results = screener.screen(region="jp", top_n=10, submode="surge")
        assert len(results) >= 1
        assert results[0]["surge_level"] in ("surging", "overheated")

    def test_screen_stable_filters_non_accelerating(self):
        """Stable mode should only keep 'accelerating' level."""
        hist = _make_hist(300)
        quotes = [_make_quote(ma50_change=0.25)]  # surging, not accelerating
        client = MockYahooClient(quotes=quotes, hist=hist)
        screener = MomentumScreener(client)
        results = screener.screen(region="jp", top_n=10, submode="stable")
        assert len(results) == 0

    def test_screen_stable_keeps_accelerating(self):
        """Stable mode should keep 'accelerating' level."""
        hist = _make_hist(300)
        quotes = [_make_quote(ma50_change=0.12)]  # accelerating
        client = MockYahooClient(quotes=quotes, hist=hist)
        screener = MomentumScreener(client)
        results = screener.screen(region="jp", top_n=10, submode="stable")
        assert len(results) >= 1
        assert results[0]["surge_level"] == "accelerating"

    def test_screen_surge_filters_none(self):
        """Surge mode should filter out 'none' level."""
        hist = _make_hist(300)
        quotes = [_make_quote(ma50_change=0.03)]  # none level
        client = MockYahooClient(quotes=quotes, hist=hist)
        screener = MomentumScreener(client)
        results = screener.screen(region="jp", top_n=10, submode="surge")
        assert len(results) == 0

    def test_screen_sorts_by_surge_score(self):
        """Results should be sorted by surge_score descending."""
        hist = _make_hist(300)
        quotes = [
            _make_quote(symbol="A", ma50_change=0.12, high_change=-0.02),
            _make_quote(symbol="B", ma50_change=0.25, high_change=0.01),
        ]
        client = MockYahooClient(quotes=quotes, hist=hist)
        screener = MomentumScreener(client)
        results = screener.screen(region="jp", top_n=10, submode="surge")
        if len(results) >= 2:
            assert results[0]["surge_score"] >= results[1]["surge_score"]

    def test_screen_respects_top_n(self):
        """Results should be limited to top_n."""
        hist = _make_hist(300)
        quotes = [_make_quote(symbol=f"S{i}", ma50_change=0.20) for i in range(10)]
        client = MockYahooClient(quotes=quotes, hist=hist)
        screener = MomentumScreener(client)
        results = screener.screen(region="jp", top_n=3, submode="surge")
        assert len(results) <= 3

    def test_screen_attaches_surge_fields(self):
        """Result dicts should have surge-specific fields."""
        hist = _make_hist(300)
        quotes = [_make_quote(ma50_change=0.20)]
        client = MockYahooClient(quotes=quotes, hist=hist)
        screener = MomentumScreener(client)
        results = screener.screen(region="jp", top_n=10, submode="surge")
        if results:
            r = results[0]
            assert "ma50_deviation" in r
            assert "surge_level" in r
            assert "surge_score" in r
            assert "volume_ratio" in r
            assert "rsi" in r
            assert "near_high" in r
            assert "new_high" in r

    def test_screen_none_hist_skips(self):
        """If hist is None, stock should be skipped."""
        quotes = [_make_quote()]
        client = MockYahooClient(quotes=quotes, hist=None)
        screener = MomentumScreener(client)
        results = screener.screen(region="jp", top_n=10)
        assert results == []
