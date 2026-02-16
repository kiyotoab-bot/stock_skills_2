"""Tests for src/core/indicators.py -- calculate_value_score() and helpers."""

import pytest

from src.core.indicators import (
    calculate_value_score,
    calculate_shareholder_return,
    calculate_shareholder_return_history,
    _score_per,
    _score_pbr,
    _score_dividend,
    _score_roe,
    _score_growth,
)


# ===================================================================
# calculate_value_score: composite tests
# ===================================================================

class TestCalculateValueScore:
    """Tests for the composite value score (0-100)."""

    def test_ideal_values_high_score(self):
        """All indicators at ideal values should yield a high score (>= 70)."""
        stock = {
            "per": 5.0,       # very low PER
            "pbr": 0.3,       # very low PBR
            "dividend_yield": 0.09,  # 9% yield (high)
            "roe": 0.24,      # 24% ROE (high)
            "revenue_growth": 0.30,  # 30% growth (high)
        }
        score = calculate_value_score(stock)
        assert score >= 70, f"Expected >= 70 for ideal values, got {score}"

    def test_all_none_returns_zero(self):
        """All indicators None should yield 0."""
        stock = {
            "per": None,
            "pbr": None,
            "dividend_yield": None,
            "roe": None,
            "revenue_growth": None,
        }
        score = calculate_value_score(stock)
        assert score == 0.0

    def test_empty_dict_returns_zero(self):
        """Empty stock data should yield 0."""
        score = calculate_value_score({})
        assert score == 0.0

    def test_per_only_low_contributes_25_points(self):
        """Low PER only should contribute up to 25 points."""
        # PER = 1 is extremely low; per_max defaults to 15, so cutoff is 30
        # score = 25 * (1 - 1/30) = 25 * 0.9667 ~= 24.17
        stock = {"per": 1.0}
        score = calculate_value_score(stock)
        assert 20.0 <= score <= 25.0, f"Expected 20-25 for very low PER only, got {score}"

    def test_pbr_only_low_contributes_25_points(self):
        """Low PBR only should contribute up to 25 points."""
        # PBR = 0.1, pbr_max defaults to 1.0, cutoff is 2.0
        # score = 25 * (1 - 0.1/2.0) = 25 * 0.95 = 23.75
        stock = {"pbr": 0.1}
        score = calculate_value_score(stock)
        assert 20.0 <= score <= 25.0, f"Expected 20-25 for very low PBR only, got {score}"

    def test_high_dividend_contributes_20_points(self):
        """High dividend yield should contribute up to 20 points."""
        # div_min defaults to 0.03, cap = 0.09
        # yield = 0.09 -> ratio = 1.0 -> score = 20.0
        stock = {"dividend_yield": 0.09}
        score = calculate_value_score(stock)
        assert score == 20.0, f"Expected 20.0 for max dividend, got {score}"

    def test_high_roe_contributes_15_points(self):
        """High ROE should contribute up to 15 points."""
        # roe_min defaults to 0.08, cap = 0.24
        # roe = 0.24 -> ratio = 1.0 -> score = 15.0
        stock = {"roe": 0.24}
        score = calculate_value_score(stock)
        assert score == 15.0, f"Expected 15.0 for max ROE, got {score}"

    def test_high_growth_contributes_15_points(self):
        """High revenue growth should contribute up to 15 points."""
        # cap = 0.30, growth = 0.30 -> ratio = 1.0 -> score = 15.0
        stock = {"revenue_growth": 0.30}
        score = calculate_value_score(stock)
        assert score == 15.0, f"Expected 15.0 for max growth, got {score}"

    def test_score_capped_at_100(self):
        """Score should never exceed 100."""
        stock = {
            "per": 0.1,
            "pbr": 0.01,
            "dividend_yield": 1.0,
            "roe": 1.0,
            "revenue_growth": 1.0,
        }
        score = calculate_value_score(stock)
        assert score <= 100.0

    def test_yahoo_raw_keys(self):
        """Should accept yfinance raw keys (trailingPE, priceToBook, etc.)."""
        stock = {
            "trailingPE": 8.0,
            "priceToBook": 0.8,
            "dividendYield": 0.04,
            "returnOnEquity": 0.15,
            "revenueGrowth": 0.10,
        }
        score = calculate_value_score(stock)
        assert score > 0, "Should compute a non-zero score from Yahoo raw keys"

    def test_custom_thresholds(self):
        """Custom thresholds should change scoring."""
        stock = {"per": 10.0, "pbr": 0.8}
        # Default thresholds: per_max=15, pbr_max=1.0
        default_score = calculate_value_score(stock)
        # Stricter thresholds: per_max=5 -> PER 10 is much worse
        strict_score = calculate_value_score(stock, thresholds={"per_max": 5.0})
        assert strict_score < default_score

    def test_fixture_data_produces_nonzero_score(self, stock_info_data):
        """Fixture stock_info.json data should produce a meaningful score."""
        score = calculate_value_score(stock_info_data)
        assert score > 0, "Toyota fixture data should yield positive score"


# ===================================================================
# Boundary value tests for PER
# ===================================================================

class TestScorePerBoundary:
    """Boundary tests for _score_per()."""

    def test_per_zero(self):
        """PER == 0 should return 0 (per <= 0 guard)."""
        assert _score_per(0, 15.0) == 0.0

    def test_per_negative(self):
        """Negative PER should return 0."""
        assert _score_per(-5.0, 15.0) == 0.0

    def test_per_none(self):
        """None PER should return 0."""
        assert _score_per(None, 15.0) == 0.0

    def test_per_at_double_threshold(self):
        """PER at exactly 2x per_max should return 0."""
        assert _score_per(30.0, 15.0) == 0.0

    def test_per_above_double_threshold(self):
        """PER above 2x per_max should return 0."""
        assert _score_per(35.0, 15.0) == 0.0

    def test_per_very_small_positive(self):
        """Very small positive PER should yield close to 25."""
        score = _score_per(0.01, 15.0)
        assert 24.0 <= score <= 25.0


# ===================================================================
# Boundary value tests for PBR
# ===================================================================

class TestScorePbrBoundary:
    """Boundary tests for _score_pbr()."""

    def test_pbr_zero(self):
        """PBR == 0 should return 0."""
        assert _score_pbr(0, 1.0) == 0.0

    def test_pbr_negative(self):
        """Negative PBR should return 0."""
        assert _score_pbr(-1.0, 1.0) == 0.0

    def test_pbr_none(self):
        """None PBR should return 0."""
        assert _score_pbr(None, 1.0) == 0.0

    def test_pbr_at_double_threshold(self):
        """PBR at exactly 2x pbr_max should return 0."""
        assert _score_pbr(2.0, 1.0) == 0.0


# ===================================================================
# Dividend yield normalization tests
# ===================================================================

class TestDividendNormalization:
    """Test that dividendYield handles both % and ratio formats."""

    def test_dividend_as_ratio(self):
        """dividend_yield = 0.025 (2.5% as ratio) should score properly."""
        # div_min=0.03 by default, cap=0.09
        # 0.025 / 0.09 = 0.2778 -> score = 20 * 0.2778 = 5.56
        stock = {"dividend_yield": 0.025}
        score = calculate_value_score(stock)
        assert 5.0 <= score <= 6.0

    def test_dividend_as_percentage_if_prenormalized(self):
        """Pre-normalized value (e.g., 2.5% -> 0.025 by yahoo_client._normalize_ratio)
        should score correctly."""
        # yahoo_client normalizes: always value/100
        # So 2.5 (percentage) -> 0.025 (ratio). indicators.py receives 0.025.
        stock_ratio = {"dividend_yield": 0.025}
        score = calculate_value_score(stock_ratio)
        assert score > 0

    def test_dividend_zero(self):
        """dividend_yield == 0 should contribute 0 points."""
        stock = {"dividend_yield": 0.0}
        score = calculate_value_score(stock)
        assert score == 0.0

    def test_dividend_negative(self):
        """Negative dividend_yield should contribute 0 points."""
        assert _score_dividend(-0.01, 0.03) == 0.0


# ===================================================================
# Growth score edge cases
# ===================================================================

class TestScoreGrowth:
    """Tests for _score_growth()."""

    def test_growth_none(self):
        assert _score_growth(None) == 0.0

    def test_growth_negative(self):
        assert _score_growth(-0.10) == 0.0

    def test_growth_zero(self):
        assert _score_growth(0.0) == 0.0

    def test_growth_above_cap(self):
        """Growth > 30% cap should still max at 15 points."""
        assert _score_growth(0.50) == 15.0

    def test_growth_at_cap(self):
        assert _score_growth(0.30) == 15.0

    def test_growth_half_cap(self):
        """15% growth -> ratio=0.5 -> 7.5 points."""
        assert _score_growth(0.15) == 7.5


# ===================================================================
# ROE score edge cases
# ===================================================================

class TestScoreRoe:
    """Tests for _score_roe()."""

    def test_roe_none(self):
        assert _score_roe(None, 0.08) == 0.0

    def test_roe_zero(self):
        assert _score_roe(0.0, 0.08) == 0.0

    def test_roe_negative(self):
        assert _score_roe(-0.10, 0.08) == 0.0

    def test_roe_at_cap(self):
        """ROE at 3x roe_min should yield 15 points."""
        assert _score_roe(0.24, 0.08) == 15.0

    def test_roe_above_cap(self):
        """ROE above cap should still yield 15 points."""
        assert _score_roe(0.50, 0.08) == 15.0


# ===================================================================
# Anomaly value scoring (values sanitized to None upstream)
# ===================================================================

class TestAnomalyValueScoring:
    """Test that anomalous values (sanitized to None upstream) score correctly."""

    def test_none_dividend_yield_scores_zero(self):
        stock = {"dividend_yield": None, "per": 10.0, "pbr": 0.8}
        stock_no_div = {"per": 10.0, "pbr": 0.8}
        assert calculate_value_score(stock) == calculate_value_score(stock_no_div)

    def test_none_pbr_scores_zero(self):
        assert calculate_value_score({"pbr": None}) == 0.0

    def test_none_per_scores_zero(self):
        assert calculate_value_score({"per": None}) == 0.0

    def test_none_roe_scores_zero(self):
        assert calculate_value_score({"roe": None}) == 0.0

    def test_extreme_dividend_unsanitized_would_max(self):
        """Documents the problem KIK-350 fixes upstream: 78% div gets max score."""
        score = calculate_value_score({"dividend_yield": 0.78})
        assert score == 20.0  # max dividend score without upstream guard

    def test_all_none_from_anomalies(self):
        stock = {"per": None, "pbr": None, "dividend_yield": None, "roe": None, "revenue_growth": None}
        assert calculate_value_score(stock) == 0.0


# ===================================================================
# calculate_shareholder_return (KIK-375)
# ===================================================================

class TestCalculateShareholderReturn:
    """Tests for calculate_shareholder_return()."""

    def test_normal_case(self):
        """Normal Toyota-like data returns correct rates."""
        stock = {
            "dividend_paid": -800_000_000_000,
            "stock_repurchase": -500_000_000_000,
            "market_cap": 42_000_000_000_000,
            "dividend_yield": 0.028,
        }
        result = calculate_shareholder_return(stock)
        assert result["dividend_paid"] == 800_000_000_000
        assert result["stock_repurchase"] == 500_000_000_000
        assert result["total_return_amount"] == 1_300_000_000_000
        assert result["total_return_rate"] == pytest.approx(
            1_300_000_000_000 / 42_000_000_000_000
        )
        assert result["buyback_yield"] == pytest.approx(
            500_000_000_000 / 42_000_000_000_000
        )
        assert result["dividend_yield"] == 0.028

    def test_all_none(self):
        """All None inputs return all None outputs."""
        result = calculate_shareholder_return({})
        assert result["dividend_paid"] is None
        assert result["stock_repurchase"] is None
        assert result["total_return_amount"] is None
        assert result["total_return_rate"] is None
        assert result["buyback_yield"] is None
        assert result["dividend_yield"] is None

    def test_dividend_only(self):
        """Only dividend data available."""
        stock = {
            "dividend_paid": -100_000_000,
            "market_cap": 10_000_000_000,
        }
        result = calculate_shareholder_return(stock)
        assert result["dividend_paid"] == 100_000_000
        assert result["stock_repurchase"] is None
        assert result["total_return_amount"] == 100_000_000
        assert result["total_return_rate"] == pytest.approx(0.01)
        assert result["buyback_yield"] is None

    def test_buyback_only(self):
        """Only buyback data available."""
        stock = {
            "stock_repurchase": -200_000_000,
            "market_cap": 10_000_000_000,
        }
        result = calculate_shareholder_return(stock)
        assert result["dividend_paid"] is None
        assert result["stock_repurchase"] == 200_000_000
        assert result["total_return_amount"] == 200_000_000
        assert result["total_return_rate"] == pytest.approx(0.02)

    def test_market_cap_zero(self):
        """market_cap == 0 returns None for rates but amounts are calculated."""
        stock = {
            "dividend_paid": -100,
            "stock_repurchase": -200,
            "market_cap": 0,
        }
        result = calculate_shareholder_return(stock)
        assert result["total_return_amount"] == 300
        assert result["total_return_rate"] is None
        assert result["buyback_yield"] is None

    def test_market_cap_none(self):
        """market_cap == None returns None for rates."""
        stock = {
            "dividend_paid": -100,
            "stock_repurchase": -200,
            "market_cap": None,
        }
        result = calculate_shareholder_return(stock)
        assert result["total_return_amount"] == 300
        assert result["total_return_rate"] is None

    def test_positive_values(self):
        """Positive values (edge case) are abs'd correctly."""
        stock = {
            "dividend_paid": 100,
            "stock_repurchase": 200,
            "market_cap": 10_000,
        }
        result = calculate_shareholder_return(stock)
        assert result["dividend_paid"] == 100
        assert result["stock_repurchase"] == 200
        assert result["total_return_amount"] == 300
        assert result["total_return_rate"] == pytest.approx(0.03)

    def test_fixture_data(self, stock_detail_data):
        """Works with the fixture data."""
        result = calculate_shareholder_return(stock_detail_data)
        assert result["dividend_paid"] == 800_000_000_000
        assert result["stock_repurchase"] == 500_000_000_000
        assert result["total_return_rate"] is not None
        assert result["total_return_rate"] > 0


# ===================================================================
# calculate_shareholder_return_history (KIK-380)
# ===================================================================

class TestCalculateShareholderReturnHistory:
    """Tests for calculate_shareholder_return_history()."""

    def test_normal_3_years(self):
        """3-year history with matching lengths."""
        stock = {
            "dividend_paid_history": [-800e9, -750e9, -700e9],
            "stock_repurchase_history": [-500e9, -300e9, -200e9],
            "cashflow_fiscal_years": [2024, 2023, 2022],
            "market_cap": 42e12,
        }
        result = calculate_shareholder_return_history(stock)
        assert len(result) == 3
        assert result[0]["fiscal_year"] == 2024
        assert result[0]["dividend_paid"] == 800e9
        assert result[0]["stock_repurchase"] == 500e9
        assert result[0]["total_return_amount"] == 1300e9
        assert result[0]["total_return_rate"] == pytest.approx(1300e9 / 42e12)
        assert result[2]["fiscal_year"] == 2022
        assert result[2]["total_return_amount"] == 900e9

    def test_empty_history(self):
        """No history data returns empty list."""
        stock = {"market_cap": 42e12}
        result = calculate_shareholder_return_history(stock)
        assert result == []

    def test_dividend_only_history(self):
        """Only dividend history available."""
        stock = {
            "dividend_paid_history": [-100e6, -90e6],
            "cashflow_fiscal_years": [2024, 2023],
            "market_cap": 10e9,
        }
        result = calculate_shareholder_return_history(stock)
        assert len(result) == 2
        assert result[0]["dividend_paid"] == 100e6
        assert result[0]["stock_repurchase"] is None
        assert result[0]["total_return_amount"] == 100e6

    def test_repurchase_only_history(self):
        """Only repurchase history available."""
        stock = {
            "stock_repurchase_history": [-200e6, -150e6],
            "cashflow_fiscal_years": [2024, 2023],
            "market_cap": 10e9,
        }
        result = calculate_shareholder_return_history(stock)
        assert len(result) == 2
        assert result[0]["dividend_paid"] is None
        assert result[0]["stock_repurchase"] == 200e6
        assert result[0]["total_return_amount"] == 200e6

    def test_mismatched_lengths(self):
        """Different length histories use max length."""
        stock = {
            "dividend_paid_history": [-100e6, -90e6, -80e6],
            "stock_repurchase_history": [-50e6],
            "cashflow_fiscal_years": [2024, 2023, 2022],
            "market_cap": 10e9,
        }
        result = calculate_shareholder_return_history(stock)
        assert len(result) == 3
        assert result[0]["stock_repurchase"] == 50e6
        assert result[1]["stock_repurchase"] is None
        assert result[2]["stock_repurchase"] is None

    def test_no_market_cap(self):
        """No market_cap means rates are None but amounts are calculated."""
        stock = {
            "dividend_paid_history": [-100e6],
            "stock_repurchase_history": [-50e6],
            "cashflow_fiscal_years": [2024],
        }
        result = calculate_shareholder_return_history(stock)
        assert len(result) == 1
        assert result[0]["total_return_amount"] == 150e6
        assert result[0]["total_return_rate"] is None

    def test_no_fiscal_years(self):
        """Missing fiscal years set fiscal_year to None."""
        stock = {
            "dividend_paid_history": [-100e6, -90e6],
            "market_cap": 10e9,
        }
        result = calculate_shareholder_return_history(stock)
        assert len(result) == 2
        assert result[0]["fiscal_year"] is None
        assert result[1]["fiscal_year"] is None

    def test_positive_values_abs(self):
        """Positive values are abs'd (though normally negative in cashflow)."""
        stock = {
            "dividend_paid_history": [100e6, 90e6],
            "stock_repurchase_history": [50e6, 30e6],
            "cashflow_fiscal_years": [2024, 2023],
            "market_cap": 10e9,
        }
        result = calculate_shareholder_return_history(stock)
        assert result[0]["dividend_paid"] == 100e6
        assert result[0]["stock_repurchase"] == 50e6
