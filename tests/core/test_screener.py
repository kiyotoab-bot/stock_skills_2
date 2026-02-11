"""Tests for src.core.screener module."""

import pytest

from src.core.screener import QueryScreener, PullbackScreener


# ===================================================================
# QueryScreener._normalize_quote
# ===================================================================


class TestNormalizeQuote:
    def test_basic_field_mapping(self):
        """trailingPE -> per, priceToBook -> pbr, etc."""
        quote = {
            "symbol": "7203.T",
            "shortName": "Toyota Motor",
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
            "currency": "JPY",
            "regularMarketPrice": 2850.0,
            "marketCap": 30_000_000_000_000,
            "trailingPE": 10.5,
            "forwardPE": 9.8,
            "priceToBook": 0.95,
            "returnOnEquity": 0.12,
            "dividendYield": 0.035,
            "revenueGrowth": 0.08,
            "earningsGrowth": 0.15,
            "exchange": "JPX",
        }
        result = QueryScreener._normalize_quote(quote)

        assert result["symbol"] == "7203.T"
        assert result["name"] == "Toyota Motor"
        assert result["per"] == 10.5
        assert result["forward_per"] == 9.8
        assert result["pbr"] == 0.95
        assert result["roe"] == 0.12
        assert result["dividend_yield"] == 0.035
        assert result["price"] == 2850.0
        assert result["market_cap"] == 30_000_000_000_000
        assert result["sector"] == "Consumer Cyclical"
        assert result["exchange"] == "JPX"

    def test_dividend_yield_percentage_normalization(self):
        """If dividendYield > 1, it should be divided by 100 (percentage -> ratio)."""
        quote = {"dividendYield": 3.5}  # 3.5% as percentage
        result = QueryScreener._normalize_quote(quote)
        assert result["dividend_yield"] == pytest.approx(0.035)

    def test_dividend_yield_ratio_preserved(self):
        """If dividendYield <= 1, it should be kept as-is (already a ratio)."""
        quote = {"dividendYield": 0.035}
        result = QueryScreener._normalize_quote(quote)
        assert result["dividend_yield"] == 0.035

    def test_dividend_yield_none(self):
        """If dividendYield is None, dividend_yield should be None."""
        quote = {"dividendYield": None}
        result = QueryScreener._normalize_quote(quote)
        assert result["dividend_yield"] is None

    def test_dividend_yield_missing(self):
        """If dividendYield key is absent, dividend_yield should be None."""
        quote = {}
        result = QueryScreener._normalize_quote(quote)
        assert result["dividend_yield"] is None

    def test_roe_percentage_normalization(self):
        """returnOnEquity > 1 should be divided by 100."""
        quote = {"returnOnEquity": 12.5}  # 12.5% as percentage
        result = QueryScreener._normalize_quote(quote)
        assert result["roe"] == pytest.approx(0.125)

    def test_roe_ratio_preserved(self):
        """returnOnEquity <= 1 stays as-is."""
        quote = {"returnOnEquity": 0.15}
        result = QueryScreener._normalize_quote(quote)
        assert result["roe"] == 0.15

    def test_revenue_growth_percentage_normalization(self):
        """revenueGrowth with abs > 5 should be divided by 100."""
        quote = {"revenueGrowth": 15.0}  # 15% as percentage
        result = QueryScreener._normalize_quote(quote)
        assert result["revenue_growth"] == pytest.approx(0.15)

    def test_revenue_growth_ratio_preserved(self):
        """revenueGrowth with abs <= 5 stays as-is (could be 500% growth)."""
        quote = {"revenueGrowth": 0.08}
        result = QueryScreener._normalize_quote(quote)
        assert result["revenue_growth"] == 0.08

    def test_none_fields_handled(self):
        """All None fields should not cause errors and pass through as None."""
        quote = {
            "symbol": "TEST",
            "trailingPE": None,
            "priceToBook": None,
            "dividendYield": None,
            "returnOnEquity": None,
            "revenueGrowth": None,
            "earningsGrowth": None,
            "regularMarketPrice": None,
        }
        result = QueryScreener._normalize_quote(quote)

        assert result["symbol"] == "TEST"
        assert result["per"] is None
        assert result["pbr"] is None
        assert result["dividend_yield"] is None
        assert result["roe"] is None
        assert result["revenue_growth"] is None
        assert result["price"] is None

    def test_longname_fallback(self):
        """If shortName is missing, longName should be used."""
        quote = {"longName": "Toyota Motor Corporation", "shortName": None}
        result = QueryScreener._normalize_quote(quote)
        assert result["name"] == "Toyota Motor Corporation"

    def test_shortname_priority(self):
        """shortName takes priority over longName."""
        quote = {"shortName": "Toyota", "longName": "Toyota Motor Corporation"}
        result = QueryScreener._normalize_quote(quote)
        assert result["name"] == "Toyota"

    def test_empty_quote(self):
        """Empty dict should produce a result with None/empty values without error."""
        result = QueryScreener._normalize_quote({})
        assert result["symbol"] == ""
        assert result["name"] is None
        assert result["per"] is None
        assert result["pbr"] is None

    def test_negative_revenue_growth_normalization(self):
        """Negative revenueGrowth with abs > 5 should also be normalized."""
        quote = {"revenueGrowth": -10.0}  # -10% as percentage
        result = QueryScreener._normalize_quote(quote)
        assert result["revenue_growth"] == pytest.approx(-0.10)


# ===================================================================
# PullbackScreener.DEFAULT_CRITERIA
# ===================================================================


class TestPullbackScreenerDefaults:
    def test_default_criteria_values(self):
        """DEFAULT_CRITERIA should have the expected keys and values."""
        expected = {
            "max_per": 20,
            "min_roe": 0.08,
            "min_revenue_growth": 0.05,
        }
        assert PullbackScreener.DEFAULT_CRITERIA == expected

    def test_default_criteria_keys(self):
        """DEFAULT_CRITERIA should contain exactly the expected keys."""
        expected_keys = {"max_per", "min_roe", "min_revenue_growth"}
        assert set(PullbackScreener.DEFAULT_CRITERIA.keys()) == expected_keys

    def test_default_criteria_is_not_mutated_across_instances(self):
        """Accessing DEFAULT_CRITERIA from different instances should be the same."""
        # Create a mock yahoo_client
        class MockClient:
            pass

        s1 = PullbackScreener(MockClient())
        s2 = PullbackScreener(MockClient())
        assert s1.DEFAULT_CRITERIA is s2.DEFAULT_CRITERIA
