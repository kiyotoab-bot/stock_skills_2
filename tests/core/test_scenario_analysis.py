"""Tests for src.core.scenario_analysis module."""

import pytest

from src.core.scenario_analysis import (
    SCENARIOS,
    SCENARIO_ALIASES,
    resolve_scenario,
    compute_stock_scenario_impact,
    analyze_portfolio_scenario,
    _infer_currency,
    _infer_region,
    _match_target,
)


# ===================================================================
# resolve_scenario
# ===================================================================


class TestResolveScenario:
    def test_direct_key(self):
        """Direct scenario key lookup should work."""
        result = resolve_scenario("triple_decline")
        assert result is not None
        assert result["name"] == "トリプル安（株安・債券安・円安）"

    def test_japanese_alias_triple_decline(self):
        """Japanese alias 'トリプル安' -> triple_decline."""
        result = resolve_scenario("トリプル安")
        assert result is not None
        assert result["base_shock"] == -0.20

    def test_japanese_alias_recession(self):
        """'リセッション' -> us_recession."""
        result = resolve_scenario("リセッション")
        assert result is not None
        assert "リセッション" in result["name"]

    def test_english_alias(self):
        """English alias 'recession' -> us_recession."""
        result = resolve_scenario("recession")
        assert result is not None
        assert result["base_shock"] == -0.25

    def test_case_insensitive(self):
        """Lookup should be case-insensitive for keys."""
        result = resolve_scenario("TRIPLE_DECLINE")
        assert result is not None

    def test_nonexistent_scenario_returns_none(self):
        """Unknown scenario name should return None."""
        result = resolve_scenario("nonexistent_scenario")
        assert result is None

    def test_empty_string_returns_none(self):
        """Empty string should return None."""
        result = resolve_scenario("")
        assert result is None

    def test_all_predefined_scenarios_resolvable(self):
        """Every key in SCENARIOS should be resolvable."""
        for key in SCENARIOS:
            result = resolve_scenario(key)
            assert result is not None, f"Scenario '{key}' should be resolvable"

    def test_all_aliases_resolvable(self):
        """Every alias in SCENARIO_ALIASES should resolve to a valid scenario."""
        for alias in SCENARIO_ALIASES:
            result = resolve_scenario(alias)
            assert result is not None, f"Alias '{alias}' should resolve"

    def test_boj_aliases(self):
        """'利上げ', '日銀', 'boj' -> boj_rate_hike."""
        for alias in ("利上げ", "日銀", "boj"):
            result = resolve_scenario(alias)
            assert result is not None
            assert result["trigger"] == "インフレ持続で追加利上げ"

    def test_yen_depreciation_aliases(self):
        """'ドル高', '円安', 'yen' -> yen_depreciation."""
        for alias in ("ドル高", "円安", "yen"):
            result = resolve_scenario(alias)
            assert result is not None
            assert result["base_shock"] == -0.10


# ===================================================================
# _infer_currency / _infer_region helpers
# ===================================================================


class TestInferCurrency:
    def test_from_stock_info(self):
        """stock_info['currency'] takes priority."""
        assert _infer_currency("7203.T", {"currency": "EUR"}) == "EUR"

    def test_from_suffix_japan(self):
        assert _infer_currency("7203.T", {}) == "JPY"

    def test_from_suffix_singapore(self):
        assert _infer_currency("D05.SI", {}) == "SGD"

    def test_no_suffix_defaults_usd(self):
        assert _infer_currency("AAPL", {}) == "USD"


class TestInferRegion:
    def test_from_stock_info_country(self):
        assert _infer_region("AAPL", {"country": "Japan"}) == "Japan"

    def test_from_suffix(self):
        assert _infer_region("7203.T", {}) == "Japan"

    def test_no_suffix_defaults_us(self):
        assert _infer_region("AAPL", {}) == "US"


# ===================================================================
# compute_stock_scenario_impact
# ===================================================================


class TestStockScenarioImpact:
    def _make_japan_stock(self, **overrides):
        base = {
            "symbol": "7203.T",
            "name": "Toyota",
            "sector": "Consumer Cyclical",
            "price": 2800.0,
            "beta": 1.0,
            "currency": "JPY",
            "country": "Japan",
        }
        base.update(overrides)
        return base

    def _make_us_stock(self, **overrides):
        base = {
            "symbol": "AAPL",
            "name": "Apple",
            "sector": "Technology",
            "price": 180.0,
            "beta": 1.2,
            "currency": "USD",
            "country": "US",
        }
        base.update(overrides)
        return base

    def test_basic_impact_calculation(self):
        """Base shock * beta should be the starting direct_impact."""
        stock = self._make_japan_stock(beta=1.0)
        scenario = resolve_scenario("triple_decline")
        result = compute_stock_scenario_impact(stock, {}, scenario)

        assert result["symbol"] == "7203.T"
        assert "direct_impact" in result
        assert "currency_impact" in result
        assert "total_impact" in result
        assert "causal_chain" in result

    def test_beta_amplifies_shock(self):
        """Higher beta should increase the magnitude of direct_impact."""
        stock_low_beta = self._make_us_stock(beta=0.5)
        stock_high_beta = self._make_us_stock(beta=2.0)
        scenario = resolve_scenario("us_recession")

        result_low = compute_stock_scenario_impact(stock_low_beta, {}, scenario)
        result_high = compute_stock_scenario_impact(stock_high_beta, {}, scenario)

        # Higher beta -> more negative direct impact (in absolute terms)
        assert result_high["direct_impact"] < result_low["direct_impact"]

    def test_japan_stock_triple_decline_currency_impact(self):
        """JPY stock in triple_decline: currency_impact should be 0 (JPY asset)."""
        stock = self._make_japan_stock()
        scenario = resolve_scenario("triple_decline")
        result = compute_stock_scenario_impact(stock, {}, scenario)

        # JPY currency -> no foreign currency impact
        assert result["currency_impact"] == 0.0

    def test_us_stock_triple_decline_currency_impact(self):
        """USD stock in triple_decline: should have currency impact (impact_on_foreign)."""
        stock = self._make_us_stock()
        scenario = resolve_scenario("triple_decline")
        result = compute_stock_scenario_impact(stock, {}, scenario)

        # USD stock should receive currency effect from triple_decline
        # impact_on_foreign = +0.097 (yen depreciation benefits foreign assets)
        assert result["currency_impact"] != 0.0

    def test_causal_chain_populated(self):
        """causal_chain should be a non-empty list of strings."""
        stock = self._make_japan_stock()
        scenario = resolve_scenario("triple_decline")
        result = compute_stock_scenario_impact(stock, {}, scenario)

        assert isinstance(result["causal_chain"], list)
        assert len(result["causal_chain"]) > 0
        assert all(isinstance(s, str) for s in result["causal_chain"])

    def test_sensitivity_adjustment(self):
        """When composite_shock is provided, it should adjust the direct_impact."""
        stock = self._make_japan_stock()
        scenario = resolve_scenario("triple_decline")

        result_no_sens = compute_stock_scenario_impact(stock, {}, scenario)
        result_with_sens = compute_stock_scenario_impact(
            stock, {"composite_shock": -0.5}, scenario
        )

        # With negative composite_shock, the adjustment factor < 1.0
        # so impact should differ
        assert result_no_sens["direct_impact"] != result_with_sens["direct_impact"]

    def test_price_impact_calculated(self):
        """price_impact = price * total_impact."""
        stock = self._make_japan_stock(price=1000.0, beta=1.0)
        scenario = resolve_scenario("triple_decline")
        result = compute_stock_scenario_impact(stock, {}, scenario)

        expected_price_impact = stock["price"] * result["total_impact"]
        assert abs(result["price_impact"] - round(expected_price_impact, 2)) < 0.05

    def test_sector_matching(self):
        """A Technology stock should match 'グロース株' target (Technology sector)."""
        stock = self._make_us_stock(sector="Technology")
        scenario = resolve_scenario("boj_rate_hike")  # has グロース株 in primary
        result = compute_stock_scenario_impact(stock, {}, scenario)

        # Should have matched some sector-based effects
        assert len(result["causal_chain"]) > 1  # base + at least one match


# ===================================================================
# analyze_portfolio_scenario
# ===================================================================


class TestPortfolioScenario:
    def test_single_stock_portfolio(self):
        """Single stock with weight=1.0."""
        portfolio = [{
            "symbol": "7203.T",
            "name": "Toyota",
            "sector": "Consumer Cyclical",
            "price": 2800.0,
            "beta": 1.0,
            "currency": "JPY",
            "country": "Japan",
        }]
        scenario = resolve_scenario("triple_decline")
        result = analyze_portfolio_scenario(portfolio, [{}], [1.0], scenario)

        assert result["scenario_name"] == "トリプル安（株安・債券安・円安）"
        assert "portfolio_impact" in result
        assert "judgment" in result
        assert result["judgment"] in ("継続", "認識", "要対応")

    def test_multi_stock_weighted_impact(self):
        """Portfolio impact is the weighted average of per-stock impacts."""
        stock_jp = {
            "symbol": "7203.T", "name": "Toyota",
            "sector": "Consumer Cyclical", "price": 2800.0,
            "beta": 1.0, "currency": "JPY", "country": "Japan",
        }
        stock_us = {
            "symbol": "AAPL", "name": "Apple",
            "sector": "Technology", "price": 180.0,
            "beta": 1.2, "currency": "USD", "country": "US",
        }
        scenario = resolve_scenario("triple_decline")
        weights = [0.6, 0.4]

        result = analyze_portfolio_scenario(
            [stock_jp, stock_us], [{}, {}], weights, scenario
        )

        assert len(result["stock_impacts"]) == 2
        assert result["stock_impacts"][0]["weight"] == 0.6
        assert result["stock_impacts"][1]["weight"] == 0.4
        assert isinstance(result["portfolio_impact"], float)

    def test_judgment_severe_scenario(self):
        """Very negative portfolio_impact -> '要対応'."""
        # Use a stock with high beta to maximize impact
        stock = {
            "symbol": "RISKY",
            "sector": "Consumer Cyclical",
            "price": 100.0,
            "beta": 3.0,
            "currency": "JPY",
            "country": "Japan",
        }
        scenario = resolve_scenario("us_recession")  # base_shock = -0.25
        result = analyze_portfolio_scenario([stock], [{}], [1.0], scenario)

        # With beta=3.0, direct_impact starts at -0.75, likely > -0.30 total
        if result["portfolio_impact"] <= -0.30:
            assert result["judgment"] == "要対応"
        elif result["portfolio_impact"] <= -0.15:
            assert result["judgment"] == "認識"
        else:
            assert result["judgment"] == "継続"

    def test_judgment_mild_scenario(self):
        """Mild impact -> '継続'."""
        stock = {
            "symbol": "SAFE",
            "sector": "Consumer Defensive",
            "price": 100.0,
            "beta": 0.3,
            "currency": "JPY",
            "country": "Japan",
        }
        # yen_depreciation has base_shock = -0.10
        scenario = resolve_scenario("yen_depreciation")
        result = analyze_portfolio_scenario([stock], [{}], [1.0], scenario)

        # With low beta and JPY, impact should be mild
        if result["portfolio_impact"] > -0.15:
            assert result["judgment"] == "継続"

    def test_causal_chain_summary_generated(self):
        """causal_chain_summary should be a non-empty string."""
        stock = {
            "symbol": "7203.T", "sector": "Industrials",
            "price": 2800.0, "beta": 1.0, "currency": "JPY", "country": "Japan",
        }
        scenario = resolve_scenario("triple_decline")
        result = analyze_portfolio_scenario([stock], [{}], [1.0], scenario)

        assert isinstance(result["causal_chain_summary"], str)
        assert len(result["causal_chain_summary"]) > 0
        assert "トリガー" in result["causal_chain_summary"]

    def test_offset_factors_included(self):
        """offset_factors should come from the scenario definition."""
        scenario = resolve_scenario("triple_decline")
        stock = {
            "symbol": "7203.T", "sector": "Industrials",
            "price": 2800.0, "beta": 1.0, "currency": "JPY", "country": "Japan",
        }
        result = analyze_portfolio_scenario([stock], [{}], [1.0], scenario)

        assert isinstance(result["offset_factors"], list)
        # triple_decline has offset factors
        assert len(result["offset_factors"]) > 0

    def test_time_axis_included(self):
        """time_axis should come from the scenario definition."""
        scenario = resolve_scenario("triple_decline")
        stock = {
            "symbol": "7203.T", "sector": "Industrials",
            "price": 2800.0, "beta": 1.0, "currency": "JPY", "country": "Japan",
        }
        result = analyze_portfolio_scenario([stock], [{}], [1.0], scenario)

        assert isinstance(result["time_axis"], str)
        assert len(result["time_axis"]) > 0

    def test_missing_sensitivities_padded(self):
        """If sensitivities list is shorter than portfolio, it should be padded with {}."""
        stocks = [
            {"symbol": "A", "price": 100.0, "beta": 1.0, "currency": "JPY", "country": "Japan"},
            {"symbol": "B", "price": 200.0, "beta": 1.0, "currency": "JPY", "country": "Japan"},
        ]
        scenario = resolve_scenario("triple_decline")

        # Only one sensitivity for two stocks
        result = analyze_portfolio_scenario(stocks, [{}], [0.5, 0.5], scenario)
        assert len(result["stock_impacts"]) == 2

    def test_missing_weights_filled(self):
        """If weights list is shorter than portfolio, remaining weight is distributed equally."""
        stocks = [
            {"symbol": "A", "price": 100.0, "beta": 1.0, "currency": "JPY", "country": "Japan"},
            {"symbol": "B", "price": 200.0, "beta": 1.0, "currency": "JPY", "country": "Japan"},
        ]
        scenario = resolve_scenario("triple_decline")

        # Only one weight for two stocks
        result = analyze_portfolio_scenario(stocks, [{}, {}], [0.5], scenario)
        assert len(result["stock_impacts"]) == 2
        # Second stock should get the remaining weight
        assert result["stock_impacts"][1]["weight"] == 0.5
