"""Tests for check_long_term_suitability() in health_check.py (KIK-371)."""

from src.core.health_check import check_long_term_suitability


class TestCheckLongTermSuitability:
    """Tests for the long-term suitability classification."""

    def test_ideal_long_term_stock(self):
        """All criteria met -> 長期向き."""
        detail = {
            "symbol": "7203.T",
            "roe": 0.18,
            "eps_growth": 0.15,
            "dividend_yield": 0.03,
            "per": 15.0,
            "sector": "Consumer Cyclical",
        }
        result = check_long_term_suitability(detail)
        assert result["label"] == "長期向き"
        assert result["roe_status"] == "high"
        assert result["eps_growth_status"] == "growing"
        assert result["dividend_status"] == "high"
        assert result["per_risk"] == "safe"

    def test_overvalued_per_is_short_term(self):
        """PER > 40 -> 短期向き even with good fundamentals."""
        detail = {
            "symbol": "GROWTH.T",
            "roe": 0.20,
            "eps_growth": 0.20,
            "dividend_yield": 0.03,
            "per": 50.0,
            "sector": "Technology",
        }
        result = check_long_term_suitability(detail)
        assert result["label"] == "短期向き"
        assert result["per_risk"] == "overvalued"

    def test_low_roe_is_short_term(self):
        """ROE < 10% -> 短期向き."""
        detail = {
            "symbol": "LOW.T",
            "roe": 0.05,
            "eps_growth": 0.15,
            "dividend_yield": 0.03,
            "per": 12.0,
            "sector": "Industrials",
        }
        result = check_long_term_suitability(detail)
        assert result["label"] == "短期向き"
        assert result["roe_status"] == "low"

    def test_medium_roe_needs_review(self):
        """ROE 10-15% with other good metrics -> 要検討."""
        detail = {
            "symbol": "MID.T",
            "roe": 0.12,
            "eps_growth": 0.12,
            "dividend_yield": 0.03,
            "per": 15.0,
            "sector": "Technology",
        }
        result = check_long_term_suitability(detail)
        assert result["label"] == "要検討"

    def test_declining_eps_needs_review(self):
        """Declining EPS with high ROE -> 要検討."""
        detail = {
            "symbol": "DEC.T",
            "roe": 0.18,
            "eps_growth": -0.05,
            "dividend_yield": 0.03,
            "per": 12.0,
            "sector": "Technology",
        }
        result = check_long_term_suitability(detail)
        assert result["label"] == "要検討"
        assert result["eps_growth_status"] == "declining"

    def test_low_dividend_needs_review(self):
        """Low dividend with other good metrics -> 要検討."""
        detail = {
            "symbol": "LOWDIV.T",
            "roe": 0.18,
            "eps_growth": 0.15,
            "dividend_yield": 0.005,
            "per": 15.0,
            "sector": "Technology",
        }
        result = check_long_term_suitability(detail)
        assert result["label"] == "要検討"
        assert result["dividend_status"] == "medium"

    def test_etf_returns_excluded(self):
        """ETF -> 対象外."""
        detail = {"quoteType": "ETF", "symbol": "1306.T"}
        result = check_long_term_suitability(detail)
        assert result["label"] == "対象外"
        assert result["summary"] == "ETF"

    def test_cash_returns_excluded(self):
        """Cash position -> 対象外."""
        detail = {"symbol": "JPY.CASH"}
        result = check_long_term_suitability(detail)
        assert result["label"] == "対象外"
        assert result["summary"] == "-"

    def test_all_none_values_needs_review(self):
        """All metrics None -> 要検討 (unknown != low/overvalued)."""
        detail = {
            "symbol": "NODATA.T",
            "roe": None,
            "eps_growth": None,
            "dividend_yield": None,
            "per": None,
            "sector": "Technology",
        }
        result = check_long_term_suitability(detail)
        assert result["label"] == "要検討"
        assert result["roe_status"] == "unknown"
        assert result["eps_growth_status"] == "unknown"
        assert result["dividend_status"] == "unknown"
        assert result["per_risk"] == "unknown"
        assert "データ不足" in result["summary"]

    # --- Boundary value tests ---

    def test_roe_exactly_15_is_high(self):
        detail = {
            "symbol": "X.T", "roe": 0.15, "eps_growth": 0.10,
            "dividend_yield": 0.02, "per": 25.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["roe_status"] == "high"
        assert result["label"] == "長期向き"

    def test_roe_just_below_15_is_medium(self):
        detail = {
            "symbol": "X.T", "roe": 0.149, "eps_growth": 0.10,
            "dividend_yield": 0.02, "per": 25.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["roe_status"] == "medium"
        assert result["label"] == "要検討"

    def test_roe_exactly_10_is_medium(self):
        detail = {
            "symbol": "X.T", "roe": 0.10, "eps_growth": 0.10,
            "dividend_yield": 0.02, "per": 25.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["roe_status"] == "medium"

    def test_roe_just_below_10_is_low(self):
        detail = {
            "symbol": "X.T", "roe": 0.099, "eps_growth": 0.10,
            "dividend_yield": 0.02, "per": 25.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["roe_status"] == "low"
        assert result["label"] == "短期向き"

    def test_eps_exactly_10_is_growing(self):
        detail = {
            "symbol": "X.T", "roe": 0.15, "eps_growth": 0.10,
            "dividend_yield": 0.02, "per": 20.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["eps_growth_status"] == "growing"

    def test_eps_zero_is_flat(self):
        detail = {
            "symbol": "X.T", "roe": 0.15, "eps_growth": 0.0,
            "dividend_yield": 0.02, "per": 20.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["eps_growth_status"] == "flat"

    def test_eps_negative_is_declining(self):
        detail = {
            "symbol": "X.T", "roe": 0.15, "eps_growth": -0.01,
            "dividend_yield": 0.02, "per": 20.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["eps_growth_status"] == "declining"

    def test_per_exactly_25_is_safe(self):
        detail = {
            "symbol": "X.T", "roe": 0.15, "eps_growth": 0.10,
            "dividend_yield": 0.02, "per": 25.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["per_risk"] == "safe"

    def test_per_26_is_moderate(self):
        detail = {
            "symbol": "X.T", "roe": 0.15, "eps_growth": 0.10,
            "dividend_yield": 0.02, "per": 26.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["per_risk"] == "moderate"

    def test_per_exactly_40_is_moderate(self):
        detail = {
            "symbol": "X.T", "roe": 0.15, "eps_growth": 0.10,
            "dividend_yield": 0.02, "per": 40.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["per_risk"] == "moderate"

    def test_per_41_is_overvalued(self):
        detail = {
            "symbol": "X.T", "roe": 0.15, "eps_growth": 0.10,
            "dividend_yield": 0.02, "per": 41.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["per_risk"] == "overvalued"
        assert result["label"] == "短期向き"

    def test_dividend_exactly_2pct_is_high(self):
        detail = {
            "symbol": "X.T", "roe": 0.15, "eps_growth": 0.10,
            "dividend_yield": 0.02, "per": 20.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["dividend_status"] == "high"

    def test_dividend_zero_is_low(self):
        detail = {
            "symbol": "X.T", "roe": 0.15, "eps_growth": 0.10,
            "dividend_yield": 0.0, "per": 20.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["dividend_status"] == "low"

    def test_result_keys(self):
        detail = {
            "symbol": "X.T", "roe": 0.15, "eps_growth": 0.10,
            "dividend_yield": 0.02, "per": 20.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        expected_keys = {
            "label", "roe_status", "eps_growth_status",
            "dividend_status", "per_risk", "score", "summary",
        }
        assert set(result.keys()) == expected_keys

    def test_summary_contains_key_traits(self):
        detail = {
            "symbol": "X.T", "roe": 0.18, "eps_growth": 0.15,
            "dividend_yield": 0.03, "per": 15.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert "高ROE" in result["summary"]
        assert "EPS成長" in result["summary"]
        assert "高配当" in result["summary"]

    def test_summary_shows_negative_traits(self):
        detail = {
            "symbol": "X.T", "roe": 0.05, "eps_growth": -0.10,
            "dividend_yield": 0.0, "per": 50.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert "低ROE" in result["summary"]
        assert "EPS減少" in result["summary"]
        assert "割高PER" in result["summary"]

    def test_moderate_per_allows_long_term(self):
        """PER between 25 and 40 should not block 長期向き."""
        detail = {
            "symbol": "X.T", "roe": 0.18, "eps_growth": 0.15,
            "dividend_yield": 0.03, "per": 35.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["label"] == "長期向き"
        assert result["per_risk"] == "moderate"

    # --- inf/nan guard tests ---

    def test_inf_roe_treated_as_unknown(self):
        """Infinite ROE should be treated as None -> unknown."""
        detail = {
            "symbol": "X.T", "roe": float("inf"), "eps_growth": 0.15,
            "dividend_yield": 0.03, "per": 15.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["roe_status"] == "unknown"
        assert result["label"] == "要検討"

    def test_nan_per_treated_as_unknown(self):
        """NaN PER should be treated as None -> unknown and prevent 長期向き."""
        detail = {
            "symbol": "X.T", "roe": 0.18, "eps_growth": 0.15,
            "dividend_yield": 0.03, "per": float("nan"), "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["per_risk"] == "unknown"
        # Even with all other metrics favorable, unknown PER prevents 長期向き
        assert result["label"] == "要検討"

    def test_neg_inf_eps_growth_treated_as_unknown(self):
        """Negative infinity EPS growth -> unknown."""
        detail = {
            "symbol": "X.T", "roe": 0.18, "eps_growth": float("-inf"),
            "dividend_yield": 0.03, "per": 15.0, "sector": "Tech",
        }
        result = check_long_term_suitability(detail)
        assert result["eps_growth_status"] == "unknown"


# ===================================================================
# Shareholder return integration tests (KIK-403)
# ===================================================================


class TestCheckLongTermSuitabilityWithShareholderReturn:
    """Tests for shareholder return integration in check_long_term_suitability (KIK-403)."""

    def test_total_return_rate_used_when_provided(self):
        """Total return rate should be used instead of dividend_yield."""
        detail = {
            "symbol": "HIGH.T",
            "roe": 0.18,
            "eps_growth": 0.15,
            "dividend_yield": 0.005,  # Low dividend alone
            "per": 15.0,
            "sector": "Technology",
        }
        # Without shareholder return: dividend_status = "medium" (0.5%)
        result_without = check_long_term_suitability(detail)
        assert result_without["dividend_status"] == "medium"

        # With shareholder return: total_return_rate = 5% (>2%)
        sh_return = {"total_return_rate": 0.05}
        result_with = check_long_term_suitability(detail, shareholder_return_data=sh_return)
        assert result_with["dividend_status"] == "high"

    def test_none_shareholder_return_falls_back_to_dividend(self):
        """When shareholder_return_data is None, dividend_yield is used."""
        detail = {
            "symbol": "X.T",
            "roe": 0.18,
            "eps_growth": 0.15,
            "dividend_yield": 0.03,
            "per": 15.0,
            "sector": "Technology",
        }
        result = check_long_term_suitability(detail, shareholder_return_data=None)
        assert result["dividend_status"] == "high"

    def test_no_total_return_rate_key_falls_back(self):
        """When shareholder_return_data has no total_return_rate, fall back."""
        detail = {
            "symbol": "X.T",
            "roe": 0.18,
            "eps_growth": 0.15,
            "dividend_yield": 0.03,
            "per": 15.0,
            "sector": "Technology",
        }
        sh_return = {"total_return_rate": None}
        result = check_long_term_suitability(detail, shareholder_return_data=sh_return)
        assert result["dividend_status"] == "high"  # falls back to 3%

    def test_summary_shows_high_return_label(self):
        """Summary should show '高還元' when total return is used."""
        detail = {
            "symbol": "X.T",
            "roe": 0.18,
            "eps_growth": 0.15,
            "dividend_yield": 0.005,
            "per": 15.0,
            "sector": "Technology",
        }
        sh_return = {"total_return_rate": 0.05}
        result = check_long_term_suitability(detail, shareholder_return_data=sh_return)
        assert "高還元" in result["summary"]

    def test_summary_shows_high_dividend_without_return_data(self):
        """Summary should show '高配当' when no shareholder_return_data."""
        detail = {
            "symbol": "X.T",
            "roe": 0.18,
            "eps_growth": 0.15,
            "dividend_yield": 0.03,
            "per": 15.0,
            "sector": "Technology",
        }
        result = check_long_term_suitability(detail)
        assert "高配当" in result["summary"]

    def test_backward_compatible_no_arg(self):
        """Existing callers without shareholder_return_data should still work."""
        detail = {
            "symbol": "7203.T",
            "roe": 0.18,
            "eps_growth": 0.15,
            "dividend_yield": 0.03,
            "per": 15.0,
            "sector": "Consumer Cyclical",
        }
        result = check_long_term_suitability(detail)
        assert result["label"] == "長期向き"

    def test_low_buyback_with_high_dividend_still_high(self):
        """Total return 2.5% (mostly dividend) -> high."""
        detail = {
            "symbol": "X.T",
            "roe": 0.18,
            "eps_growth": 0.15,
            "dividend_yield": 0.02,
            "per": 15.0,
            "sector": "Technology",
        }
        sh_return = {"total_return_rate": 0.025}
        result = check_long_term_suitability(detail, shareholder_return_data=sh_return)
        assert result["dividend_status"] == "high"
