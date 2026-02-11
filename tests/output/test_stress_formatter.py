"""Tests for src/output/stress_formatter.py."""

import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.output.stress_formatter import (
    format_concentration_report,
    format_full_stress_report,
    format_scenario_report,
    format_sensitivity_report,
)


# ---------------------------------------------------------------------------
# Fixtures (local to this module)
# ---------------------------------------------------------------------------

def _make_portfolio_summary():
    """Create a sample portfolio summary dict."""
    return {
        "total_value": 10_000_000,
        "stock_count": 3,
        "stocks": [
            {
                "symbol": "7203.T",
                "name": "Toyota",
                "weight": 0.40,
                "price": 2850,
                "sector": "Consumer Cyclical",
            },
            {
                "symbol": "AAPL",
                "name": "Apple",
                "weight": 0.35,
                "price": 195,
                "sector": "Technology",
            },
            {
                "symbol": "D05.SI",
                "name": "DBS",
                "weight": 0.25,
                "price": 35,
                "sector": "Financial Services",
            },
        ],
    }


def _make_concentration():
    """Create a sample concentration analysis dict."""
    return {
        "risk_level": "やや集中",
        "max_hhi": 0.3050,
        "max_hhi_axis": "sector",
        "concentration_multiplier": 1.15,
        "sector_hhi": 0.3050,
        "sector_breakdown": {"Consumer Cyclical": 0.40, "Technology": 0.35, "Financial Services": 0.25},
        "region_hhi": 0.2800,
        "region_breakdown": {"JP": 0.40, "US": 0.35, "SG": 0.25},
        "currency_hhi": 0.2900,
        "currency_breakdown": {"JPY": 0.40, "USD": 0.35, "SGD": 0.25},
    }


def _make_sensitivities():
    """Create sample sensitivity data."""
    return [
        {
            "symbol": "7203.T",
            "name": "Toyota",
            "fundamental_score": 0.75,
            "technical_score": 0.60,
            "quadrant": "堅実",
            "composite_shock": -0.08,
        },
        {
            "symbol": "AAPL",
            "name": "Apple",
            "fundamental_score": 0.80,
            "technical_score": 0.45,
            "quadrant": "回復期待",
            "composite_shock": -0.12,
        },
    ]


def _make_scenario_result():
    """Create a sample scenario analysis result dict."""
    return {
        "scenario_name": "米国リセッション",
        "trigger": "米国GDP成長率がマイナス転換",
        "portfolio_impact": -0.18,
        "portfolio_value_change": -1_800_000,
        "judgment": "認識",
        "causal_chain_summary": "米GDP下落 -> 企業収益悪化 -> 株価下落",
        "stock_impacts": [
            {
                "symbol": "7203.T",
                "name": "Toyota",
                "weight": 0.40,
                "direct_impact": -0.15,
                "currency_impact": 0.05,
                "total_impact": -0.10,
                "pf_contribution": -0.04,
            },
            {
                "symbol": "AAPL",
                "name": "Apple",
                "weight": 0.35,
                "direct_impact": -0.25,
                "currency_impact": 0.0,
                "total_impact": -0.25,
                "pf_contribution": -0.0875,
            },
        ],
        "offset_factors": ["円安効果による輸出企業の収益押し上げ"],
        "time_axis": "3-6ヶ月",
    }


# ---------------------------------------------------------------------------
# format_full_stress_report
# ---------------------------------------------------------------------------

class TestFormatFullStressReport:
    """Tests for format_full_stress_report()."""

    def test_returns_markdown_string(self):
        """Full stress report returns a non-empty Markdown string."""
        output = format_full_stress_report(
            portfolio_summary=_make_portfolio_summary(),
            concentration=_make_concentration(),
            sensitivities=_make_sensitivities(),
            scenario_result=_make_scenario_result(),
        )
        assert isinstance(output, str)
        assert len(output) > 0

    def test_contains_main_header(self):
        """Report includes the scenario name in the main header."""
        output = format_full_stress_report(
            portfolio_summary=_make_portfolio_summary(),
            concentration=_make_concentration(),
            sensitivities=_make_sensitivities(),
            scenario_result=_make_scenario_result(),
        )
        assert "# ストレステストレポート: 米国リセッション" in output

    def test_contains_step_headers(self):
        """Report includes all step section headers."""
        output = format_full_stress_report(
            portfolio_summary=_make_portfolio_summary(),
            concentration=_make_concentration(),
            sensitivities=_make_sensitivities(),
            scenario_result=_make_scenario_result(),
        )
        assert "### Step 1: ポートフォリオ概要" in output
        assert "### Step 2: 集中度分析" in output
        assert "### Step 3: ショック感応度" in output
        assert "### Step 4-5: シナリオ因果連鎖分析" in output
        assert "### Step 6: 定量結果" in output
        assert "### Step 7: 過去事例" in output
        assert "### Step 8: 総合判定" in output

    def test_contains_portfolio_summary_data(self):
        """Report includes portfolio summary values."""
        output = format_full_stress_report(
            portfolio_summary=_make_portfolio_summary(),
            concentration=_make_concentration(),
            sensitivities=_make_sensitivities(),
            scenario_result=_make_scenario_result(),
        )
        assert "10,000,000" in output
        assert "銘柄数" in output
        assert "3" in output

    def test_contains_judgment_and_recommendations(self):
        """Report includes judgment and recommended actions."""
        output = format_full_stress_report(
            portfolio_summary=_make_portfolio_summary(),
            concentration=_make_concentration(),
            sensitivities=_make_sensitivities(),
            scenario_result=_make_scenario_result(),
        )
        assert "認識" in output
        assert "推奨アクション" in output


# ---------------------------------------------------------------------------
# format_concentration_report
# ---------------------------------------------------------------------------

class TestFormatConcentrationReport:
    """Tests for format_concentration_report()."""

    def test_contains_heading(self):
        """Concentration report has the correct heading."""
        output = format_concentration_report(_make_concentration())
        assert "### Step 2: 集中度分析" in output

    def test_contains_sector_section(self):
        """Report includes sector breakdown."""
        output = format_concentration_report(_make_concentration())
        assert "#### セクター配分" in output
        assert "Consumer Cyclical" in output

    def test_contains_region_section(self):
        """Report includes region breakdown."""
        output = format_concentration_report(_make_concentration())
        assert "#### 地域配分" in output

    def test_contains_currency_section(self):
        """Report includes currency breakdown."""
        output = format_concentration_report(_make_concentration())
        assert "#### 通貨配分" in output

    def test_contains_hhi_values(self):
        """Report includes HHI numeric values."""
        output = format_concentration_report(_make_concentration())
        # sector_hhi = 0.3050 -> "0.3050"
        assert "0.3050" in output


# ---------------------------------------------------------------------------
# format_sensitivity_report
# ---------------------------------------------------------------------------

class TestFormatSensitivityReport:
    """Tests for format_sensitivity_report()."""

    def test_contains_heading(self):
        """Sensitivity report has the correct heading."""
        output = format_sensitivity_report(_make_sensitivities())
        assert "### Step 3: ショック感応度" in output

    def test_contains_table_headers(self):
        """Report includes the expected table headers."""
        output = format_sensitivity_report(_make_sensitivities())
        assert "| 銘柄 |" in output
        assert "| ファンダ |" in output
        assert "| テクニカル |" in output
        assert "| 象限 |" in output

    def test_contains_quadrant_matrix(self):
        """Report includes the 4-quadrant matrix."""
        output = format_sensitivity_report(_make_sensitivities())
        assert "#### 4象限マトリクス" in output
        assert "ファンダ弱" in output
        assert "ファンダ強" in output

    def test_empty_sensitivities(self):
        """Empty sensitivities list produces an appropriate message."""
        output = format_sensitivity_report([])
        assert "感応度データがありません" in output


# ---------------------------------------------------------------------------
# format_scenario_report
# ---------------------------------------------------------------------------

class TestFormatScenarioReport:
    """Tests for format_scenario_report()."""

    def test_contains_heading_with_scenario_name(self):
        """Scenario report heading includes the scenario name."""
        output = format_scenario_report(_make_scenario_result())
        assert "米国リセッション" in output

    def test_contains_trigger(self):
        """Report includes the trigger description."""
        output = format_scenario_report(_make_scenario_result())
        assert "米国GDP成長率がマイナス転換" in output

    def test_contains_causal_chain(self):
        """Report includes the causal chain section."""
        output = format_scenario_report(_make_scenario_result())
        assert "#### 因果連鎖" in output

    def test_contains_stock_impacts_table(self):
        """Report includes the per-stock impact table."""
        output = format_scenario_report(_make_scenario_result())
        assert "#### 銘柄別影響" in output
        assert "7203.T" in output
        assert "AAPL" in output

    def test_contains_quantitative_results(self):
        """Report includes the quantitative result section (Step 6)."""
        output = format_scenario_report(_make_scenario_result())
        assert "### Step 6: 定量結果" in output
        assert "PF影響率" in output
        assert "判定" in output
