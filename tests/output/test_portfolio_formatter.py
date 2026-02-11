"""Tests for src/output/portfolio_formatter.py."""

import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.output.portfolio_formatter import (
    format_position_list,
    format_snapshot,
    format_structure_analysis,
    format_trade_result,
)


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def snapshot_data():
    """Sample snapshot dict with two positions."""
    return {
        "timestamp": "2025-06-15T10:30:00",
        "positions": [
            {
                "symbol": "7203.T",
                "memo": "Toyota",
                "shares": 100,
                "cost_price": 2500.0,
                "current_price": 2850.0,
                "market_value_jpy": 285000.0,
                "pnl_jpy": 35000.0,
                "pnl_pct": 0.14,
                "currency": "JPY",
            },
            {
                "symbol": "AAPL",
                "memo": "Apple",
                "shares": 10,
                "cost_price": 180.0,
                "current_price": 195.0,
                "market_value_jpy": 292500.0,
                "pnl_jpy": 22500.0,
                "pnl_pct": 0.0833,
                "currency": "USD",
            },
        ],
        "total_market_value_jpy": 577500.0,
        "total_cost_jpy": 520000.0,
        "total_pnl_jpy": 57500.0,
        "total_pnl_pct": 0.1106,
        "fx_rates": {"USD/JPY": 150.0},
    }


@pytest.fixture
def empty_snapshot():
    """Snapshot with no positions."""
    return {
        "timestamp": "2025-06-15T10:30:00",
        "positions": [],
    }


@pytest.fixture
def portfolio_list():
    """Sample portfolio position list for format_position_list()."""
    return [
        {
            "symbol": "7203.T",
            "shares": 100,
            "cost_price": 2500.0,
            "cost_currency": "JPY",
            "purchase_date": "2025-01-10",
            "memo": "Toyota",
        },
        {
            "symbol": "AAPL",
            "shares": 10,
            "cost_price": 180.0,
            "cost_currency": "USD",
            "purchase_date": "2025-02-15",
            "memo": "Apple",
        },
    ]


@pytest.fixture
def structure_analysis():
    """Sample structure analysis dict for format_structure_analysis()."""
    return {
        "region_hhi": 0.3200,
        "region_breakdown": {"JP": 0.50, "US": 0.30, "SG": 0.20},
        "sector_hhi": 0.2800,
        "sector_breakdown": {"Consumer Cyclical": 0.40, "Technology": 0.35, "Financial Services": 0.25},
        "currency_hhi": 0.3400,
        "currency_breakdown": {"JPY": 0.50, "USD": 0.30, "SGD": 0.20},
        "max_hhi": 0.3400,
        "max_hhi_axis": "currency",
        "concentration_multiplier": 1.17,
        "risk_level": "やや集中",
    }


# ---------------------------------------------------------------------------
# format_snapshot
# ---------------------------------------------------------------------------

class TestFormatSnapshot:
    """Tests for format_snapshot()."""

    def test_contains_position_table(self, snapshot_data):
        """Snapshot contains a Markdown table with position data."""
        output = format_snapshot(snapshot_data)

        # Table headers
        assert "| 銘柄 |" in output
        assert "| メモ |" in output
        assert "| 株数 |" in output
        assert "| 取得単価 |" in output
        assert "| 現在価格 |" in output
        assert "| 評価額 |" in output
        assert "| 損益 |" in output
        assert "| 損益率 |" in output

        # Symbol data
        assert "7203.T" in output
        assert "AAPL" in output

    def test_contains_summary(self, snapshot_data):
        """Snapshot contains the summary section."""
        output = format_snapshot(snapshot_data)

        assert "### サマリー" in output
        assert "総評価額" in output
        assert "総投資額" in output
        assert "総損益" in output

    def test_contains_header_with_timestamp(self, snapshot_data):
        """Snapshot header includes the formatted timestamp."""
        output = format_snapshot(snapshot_data)
        # timestamp "2025-06-15T10:30:00" -> "2025/06/15 10:30"
        assert "2025/06/15 10:30" in output

    def test_contains_fx_rates(self, snapshot_data):
        """Snapshot includes FX rates section."""
        output = format_snapshot(snapshot_data)
        assert "為替レート" in output
        assert "USD/JPY" in output
        assert "150.00" in output

    def test_empty_positions_returns_no_holdings_message(self, empty_snapshot):
        """Empty positions produce a 'no holdings' message."""
        output = format_snapshot(empty_snapshot)
        assert "保有銘柄がありません" in output

    def test_empty_positions_does_not_contain_summary(self, empty_snapshot):
        """Empty positions should not include the summary section."""
        output = format_snapshot(empty_snapshot)
        assert "### サマリー" not in output


# ---------------------------------------------------------------------------
# format_position_list
# ---------------------------------------------------------------------------

class TestFormatPositionList:
    """Tests for format_position_list()."""

    def test_contains_table_with_required_columns(self, portfolio_list):
        """Position list table has symbol, shares, and cost price columns."""
        output = format_position_list(portfolio_list)

        assert "| 銘柄 |" in output
        assert "| 株数 |" in output
        assert "| 取得単価 |" in output

        # Data values
        assert "7203.T" in output
        assert "AAPL" in output
        assert "100" in output
        assert "10" in output

    def test_contains_header(self, portfolio_list):
        """Position list contains the main header."""
        output = format_position_list(portfolio_list)
        assert "## 保有銘柄一覧" in output

    def test_contains_currency_and_date(self, portfolio_list):
        """Position list includes currency and purchase date columns."""
        output = format_position_list(portfolio_list)
        assert "| 通貨 |" in output
        assert "| 取得日 |" in output
        assert "JPY" in output
        assert "USD" in output
        assert "2025-01-10" in output

    def test_empty_list_returns_no_holdings_message(self):
        """Empty portfolio list produces a 'no holdings' message."""
        output = format_position_list([])
        assert "保有銘柄がありません" in output


# ---------------------------------------------------------------------------
# format_structure_analysis
# ---------------------------------------------------------------------------

class TestFormatStructureAnalysis:
    """Tests for format_structure_analysis()."""

    def test_contains_region_section(self, structure_analysis):
        """Structure analysis includes region breakdown."""
        output = format_structure_analysis(structure_analysis)
        assert "### 地域別配分" in output
        assert "JP" in output
        assert "US" in output

    def test_contains_sector_section(self, structure_analysis):
        """Structure analysis includes sector breakdown."""
        output = format_structure_analysis(structure_analysis)
        assert "### セクター別配分" in output
        assert "Consumer Cyclical" in output

    def test_contains_currency_section(self, structure_analysis):
        """Structure analysis includes currency breakdown."""
        output = format_structure_analysis(structure_analysis)
        assert "### 通貨別配分" in output
        assert "JPY" in output
        assert "USD" in output

    def test_contains_hhi_values(self, structure_analysis):
        """Structure analysis includes HHI values."""
        output = format_structure_analysis(structure_analysis)
        # region_hhi = 0.3200 -> "0.3200"
        assert "0.3200" in output
        # currency_hhi = 0.3400 -> "0.3400"
        assert "0.3400" in output

    def test_contains_hhi_bar(self, structure_analysis):
        """Structure analysis includes HHI bar visualization."""
        output = format_structure_analysis(structure_analysis)
        # _hhi_bar renders "[###.......]" style bars
        assert "[" in output
        assert "#" in output

    def test_contains_classification(self, structure_analysis):
        """Structure analysis includes HHI classification labels."""
        output = format_structure_analysis(structure_analysis)
        # HHI 0.32 -> "やや集中" (0.25 <= hhi < 0.50)
        assert "やや集中" in output

    def test_contains_overall_judgment(self, structure_analysis):
        """Structure analysis includes the overall judgment section."""
        output = format_structure_analysis(structure_analysis)
        assert "### 総合判定" in output
        assert "集中度倍率" in output
        assert "リスクレベル" in output
        assert "最大集中軸" in output


# ---------------------------------------------------------------------------
# format_trade_result
# ---------------------------------------------------------------------------

class TestFormatTradeResult:
    """Tests for format_trade_result()."""

    def test_buy_action_label(self):
        """Buy action produces '購入' label."""
        result = {
            "symbol": "7203.T",
            "shares": 100,
            "price": 2850.0,
            "currency": "JPY",
            "total_shares": 200,
            "avg_cost": 2700.0,
            "memo": "Toyota追加購入",
        }
        output = format_trade_result(result, "buy")
        assert "購入" in output
        assert "7203.T" in output
        assert "100" in output

    def test_sell_action_label(self):
        """Sell action produces '売却' label."""
        result = {
            "symbol": "AAPL",
            "shares": 5,
            "price": 200.0,
            "currency": "USD",
            "total_shares": 5,
            "avg_cost": 180.0,
        }
        output = format_trade_result(result, "sell")
        assert "売却" in output
        assert "AAPL" in output

    def test_contains_trade_header(self):
        """Trade result contains the main header."""
        result = {"symbol": "TEST", "shares": 10, "price": 100.0, "currency": "JPY"}
        output = format_trade_result(result, "buy")
        assert "## 売買記録" in output

    def test_contains_updated_holding_info(self):
        """Trade result shows updated holding and average cost."""
        result = {
            "symbol": "7203.T",
            "shares": 50,
            "price": 2900.0,
            "currency": "JPY",
            "total_shares": 150,
            "avg_cost": 2750.0,
        }
        output = format_trade_result(result, "buy")
        assert "更新後の保有" in output
        assert "150" in output
        assert "平均取得単価" in output

    def test_memo_included_when_present(self):
        """Memo is included in output when provided."""
        result = {
            "symbol": "7203.T",
            "shares": 100,
            "price": 2850.0,
            "currency": "JPY",
            "memo": "テスト購入",
        }
        output = format_trade_result(result, "buy")
        assert "テスト購入" in output

    def test_japanese_action_names(self):
        """Japanese action names are correctly normalized."""
        result = {"symbol": "TEST", "shares": 10, "currency": "JPY"}

        output_buy = format_trade_result(result, "購入")
        assert "購入" in output_buy

        output_sell = format_trade_result(result, "売却")
        assert "売却" in output_sell
