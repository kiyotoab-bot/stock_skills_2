"""Tests for src.output.review_formatter (KIK-441)."""

import pytest

from src.output.review_formatter import format_performance_review


def _make_data(trades=None, stats=None):
    """Helper to build a data dict for format_performance_review."""
    default_stats = {
        "total": 0, "wins": 0, "win_rate": None,
        "avg_return": None, "avg_hold_days": None, "total_pnl": None,
    }
    if stats:
        default_stats.update(stats)
    return {"trades": trades or [], "stats": default_stats}


class TestFormatPerformanceReview:
    def test_empty_trades_returns_no_records_message(self):
        """Empty trades should produce a 'no records' message."""
        data = _make_data()
        output = format_performance_review(data)
        assert "売買パフォーマンスレビュー" in output
        assert "売却記録" in output
        assert "--price" in output  # usage hint

    def test_title_includes_year(self):
        """Year filter should appear in the title."""
        data = _make_data()
        output = format_performance_review(data, year=2026)
        assert "2026年" in output

    def test_title_includes_symbol(self):
        """Symbol filter should appear in the title."""
        data = _make_data()
        output = format_performance_review(data, symbol="NVDA")
        assert "NVDA" in output

    def test_trade_row_displayed(self):
        """A trade with P&L should appear in the table."""
        trades = [{
            "symbol": "NVDA", "date": "2026-02-20", "shares": 5,
            "cost_price": 120.0, "sell_price": 138.0, "hold_days": 41,
            "realized_pnl": 90.0, "pnl_rate": 0.15, "currency": "USD",
        }]
        stats = {
            "total": 1, "wins": 1, "win_rate": 1.0,
            "avg_return": 0.15, "avg_hold_days": 41.0, "total_pnl": 90.0,
        }
        data = _make_data(trades=trades, stats=stats)
        output = format_performance_review(data)

        assert "NVDA" in output
        assert "2026-02-20" in output
        assert "41日" in output
        assert "+15.00%" in output

    def test_statistics_section_displayed(self):
        """Stats section should display win rate and total P&L."""
        trades = [{
            "symbol": "NVDA", "date": "2026-02-20", "shares": 5,
            "cost_price": 120.0, "sell_price": 138.0, "hold_days": 41,
            "realized_pnl": 90.0, "pnl_rate": 0.15, "currency": "USD",
        }]
        stats = {
            "total": 1, "wins": 1, "win_rate": 1.0,
            "avg_return": 0.15, "avg_hold_days": 41.0, "total_pnl": 90.0,
        }
        data = _make_data(trades=trades, stats=stats)
        output = format_performance_review(data)

        assert "100.0%" in output  # win rate
        assert "1件" in output    # total

    def test_jpy_currency_formatting(self):
        """JPY amounts should use ¥ symbol."""
        trades = [{
            "symbol": "7203.T", "date": "2026-02-20", "shares": 100,
            "cost_price": 2800.0, "sell_price": 3200.0, "hold_days": 30,
            "realized_pnl": 40000.0, "pnl_rate": 0.1429, "currency": "JPY",
        }]
        stats = {
            "total": 1, "wins": 1, "win_rate": 1.0,
            "avg_return": 0.1429, "avg_hold_days": 30.0, "total_pnl": 40000.0,
        }
        data = _make_data(trades=trades, stats=stats)
        output = format_performance_review(data)
        assert "¥" in output

    def test_negative_pnl_displayed(self):
        """Negative P&L should be displayed without + sign."""
        trades = [{
            "symbol": "NVDA", "date": "2026-02-20", "shares": 5,
            "cost_price": 150.0, "sell_price": 120.0, "hold_days": 20,
            "realized_pnl": -150.0, "pnl_rate": -0.20, "currency": "USD",
        }]
        stats = {
            "total": 1, "wins": 0, "win_rate": 0.0,
            "avg_return": -0.20, "avg_hold_days": 20.0, "total_pnl": -150.0,
        }
        data = _make_data(trades=trades, stats=stats)
        output = format_performance_review(data)
        assert "-20.00%" in output
        assert "0.0%" in output  # win rate

    def test_returns_string(self):
        """format_performance_review should always return a string."""
        data = _make_data()
        result = format_performance_review(data)
        assert isinstance(result, str)
