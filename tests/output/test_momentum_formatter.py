"""Tests for format_momentum_markdown() (KIK-506)."""

import pytest

from src.output.formatter import format_momentum_markdown


def _make_result(symbol="7203.T", name="Toyota", price=2500,
                 ma50_dev=0.15, vol_ratio=2.0, rsi=65.0,
                 high_change=-0.03, score=60.0, level="surging"):
    return {
        "symbol": symbol,
        "name": name,
        "price": price,
        "ma50_deviation": ma50_dev,
        "volume_ratio": vol_ratio,
        "rsi": rsi,
        "high_change_pct": high_change,
        "surge_score": score,
        "surge_level": level,
    }


class TestFormatMomentumMarkdown:
    def test_empty_results(self):
        result = format_momentum_markdown([])
        assert "見つかりませんでした" in result

    def test_with_results(self):
        results = [_make_result()]
        output = format_momentum_markdown(results)
        assert "7203.T" in output
        assert "順位" in output
        assert "50MA乖離" in output
        assert "レベル" in output

    def test_surge_level_icons(self):
        """Each surge level should have its icon."""
        levels = {
            "accelerating": "\U0001f7e2",  # green
            "surging": "\U0001f7e1",       # yellow
            "overheated": "\U0001f534",    # red
        }
        for level, icon in levels.items():
            results = [_make_result(level=level)]
            output = format_momentum_markdown(results)
            assert icon in output

    def test_multiple_results(self):
        results = [
            _make_result(symbol="A", level="overheated", score=85),
            _make_result(symbol="B", level="surging", score=65),
            _make_result(symbol="C", level="accelerating", score=45),
        ]
        output = format_momentum_markdown(results)
        assert "A" in output
        assert "B" in output
        assert "C" in output

    def test_legend_present(self):
        results = [_make_result()]
        output = format_momentum_markdown(results)
        assert "加速" in output
        assert "急騰" in output
        assert "過熱" in output
