"""Tests for morning summary anomaly detection (KIK-717)."""

import pytest
from datetime import date, timedelta

from src.data.morning_summary import (
    detect_alerts,
    format_morning_summary,
    _calc_rsi,
    ALERT_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(symbol="TEST", cost_price=100.0, next_earnings=""):
    return {"symbol": symbol, "cost_price": cost_price, "next_earnings": next_earnings}


def _info(symbol="TEST", price=100.0):
    return {"symbol": symbol, "price": price}


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

class TestCalcRSI:
    def test_insufficient_data(self):
        assert _calc_rsi([1, 2, 3]) is None

    def test_all_gains(self):
        closes = list(range(1, 20))
        assert _calc_rsi(closes) == 100.0

    def test_normal_range(self):
        closes = [100 + i * 0.5 * ((-1) ** i) for i in range(20)]
        rsi = _calc_rsi(closes)
        assert rsi is not None
        assert 0 <= rsi <= 100

    def test_all_losses(self):
        closes = list(range(40, 1, -1))
        assert _calc_rsi(closes) == pytest.approx(0.0)

    def test_wilder_smoothing_matches_reference(self):
        """KIK-727: Wilder 平滑の参照実装と一致すること。

        旧実装（直近15本の単純平均 = Cutler's RSI）とは値が異なる。
        閾値 30/70 は Wilder 前提のため、こちらが正しい。
        """
        closes = [
            44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
            45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
            46.03, 46.41, 46.22, 45.64,
        ]

        def wilder_reference(values, period=14):
            deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]
            gains = [d if d > 0 else 0.0 for d in deltas]
            losses = [-d if d < 0 else 0.0 for d in deltas]
            avg_g = sum(gains[:period]) / period
            avg_l = sum(losses[:period]) / period
            for i in range(period, len(deltas)):
                avg_g = (avg_g * (period - 1) + gains[i]) / period
                avg_l = (avg_l * (period - 1) + losses[i]) / period
            return 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)

        assert _calc_rsi(closes) == pytest.approx(wilder_reference(closes), abs=1e-9)

    def test_uses_full_series_not_last_window(self):
        """系列全体を平滑するため、先頭を切り落とすと値が変わる。

        旧実装は直近 period+1 本しか見ておらず、この2つが同値になっていた。
        """
        long_series = [100 + i * 0.5 * ((-1) ** i) for i in range(60)]
        assert _calc_rsi(long_series) != pytest.approx(_calc_rsi(long_series[-15:]))


# ---------------------------------------------------------------------------
# detect_alerts
# ---------------------------------------------------------------------------

class TestDetectAlerts:
    def test_no_alerts_clean_pf(self):
        positions = [_pos("MSFT", 100)]
        infos = {"MSFT": _info("MSFT", 110)}
        histories = {"MSFT": [100 + i * 0.3 for i in range(20)]}
        alerts = detect_alerts(positions, infos, histories)
        # No exit-rule, RSI should be normal, no VIX, no earnings
        assert len([a for a in alerts if a["type"] in ("exit_rule", "hard_stop")]) == 0

    def test_exit_rule_triggered(self):
        positions = [_pos("CANON", 100)]
        infos = {"CANON": _info("CANON", 84)}  # -16%
        histories = {"CANON": [90] * 20}
        alerts = detect_alerts(positions, infos, histories)
        exit_alerts = [a for a in alerts if a["type"] == "exit_rule"]
        assert len(exit_alerts) == 1
        assert exit_alerts[0]["severity"] == "CRITICAL"

    def test_hard_stop_triggered(self):
        positions = [_pos("DEC", 100)]
        infos = {"DEC": _info("DEC", 79)}  # -21%
        histories = {"DEC": [80] * 20}
        alerts = detect_alerts(positions, infos, histories)
        hard = [a for a in alerts if a["type"] == "hard_stop"]
        assert len(hard) == 1

    def test_rsi_overbought(self):
        # Create ascending prices to push RSI high
        closes = [100 + i * 2 for i in range(20)]
        positions = [_pos("AMZN", 200)]
        infos = {"AMZN": _info("AMZN", 250)}
        alerts = detect_alerts(positions, infos, {"AMZN": closes})
        rsi_alerts = [a for a in alerts if a["type"] == "rsi_high"]
        assert len(rsi_alerts) >= 1

    def test_rsi_oversold(self):
        closes = [100 - i * 2 for i in range(20)]
        positions = [_pos("CANON", 100)]
        infos = {"CANON": _info("CANON", 60)}
        alerts = detect_alerts(positions, infos, {"CANON": closes})
        rsi_alerts = [a for a in alerts if a["type"] == "rsi_low"]
        assert len(rsi_alerts) >= 1

    def test_earnings_soon(self):
        earn_date = (date.today() + timedelta(days=3)).isoformat()
        positions = [_pos("MSFT", 400, next_earnings=earn_date)]
        infos = {"MSFT": _info("MSFT", 420)}
        alerts = detect_alerts(positions, infos, {})
        earn_alerts = [a for a in alerts if a["type"] == "earnings_soon"]
        assert len(earn_alerts) == 1
        assert earn_alerts[0]["value"] == 3

    def test_earnings_from_info_fallback(self):
        """KIK-727: portfolio.csv が空欄でも infos の next_earnings で発火する。

        実運用では CSV の next_earnings 列は11銘柄すべて空欄で、この
        アラートは一度も発火していなかった。get_stock_info が自動取得
        する値にフォールバックする。
        """
        earn_date = (date.today() + timedelta(days=1)).isoformat()
        positions = [_pos("6436.T", 3574)]  # CSV は空欄
        infos = {"6436.T": {"symbol": "6436.T", "price": 4039,
                            "next_earnings": earn_date}}
        alerts = detect_alerts(positions, infos, {})
        earn = [a for a in alerts if a["type"] == "earnings_soon"]
        assert len(earn) == 1
        assert earn[0]["value"] == 1

    def test_earnings_csv_takes_precedence_over_info(self):
        """CSV に明示値があればそちらを優先する。"""
        csv_date = (date.today() + timedelta(days=2)).isoformat()
        info_date = (date.today() + timedelta(days=5)).isoformat()
        positions = [_pos("MSFT", 400, next_earnings=csv_date)]
        infos = {"MSFT": {"symbol": "MSFT", "price": 420,
                          "next_earnings": info_date}}
        alerts = detect_alerts(positions, infos, {})
        earn = [a for a in alerts if a["type"] == "earnings_soon"]
        assert len(earn) == 1
        assert earn[0]["value"] == 2

    def test_exit_approaching_warn(self):
        """KIK-727: -10%〜-15% は WARN 層で拾う。"""
        positions = [_pos("X", 100)]
        infos = {"X": _info("X", 88)}  # -12%
        alerts = detect_alerts(positions, infos, {})
        warn = [a for a in alerts if a["type"] == "exit_approaching"]
        assert len(warn) == 1
        assert warn[0]["severity"] == "WARN"
        # exit-rule 到達前なので CRITICAL は出ない
        assert [a for a in alerts if a["severity"] == "CRITICAL"] == []

    def test_exit_approaching_not_fired_at_exit_rule(self):
        """-15% 到達時は CRITICAL のみで WARN は重複しない。"""
        positions = [_pos("X", 100)]
        infos = {"X": _info("X", 84)}  # -16%
        alerts = detect_alerts(positions, infos, {})
        assert [a for a in alerts if a["type"] == "exit_approaching"] == []
        assert [a for a in alerts if a["type"] == "exit_rule"] != []

    def test_severity_sort_order(self):
        """KIK-727: CRITICAL → WARN → INFO の順に並ぶ。"""
        positions = [_pos("CRIT", 100), _pos("WARNP", 100)]
        infos = {"CRIT": _info("CRIT", 79), "WARNP": _info("WARNP", 88)}
        histories = {"WARNP": [100 + i * 2 for i in range(20)]}  # rsi_high(INFO)
        alerts = detect_alerts(positions, infos, histories)
        sev = [a["severity"] for a in alerts]
        rank = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
        assert sev == sorted(sev, key=lambda s: rank[s])
        assert "WARN" in sev and "CRITICAL" in sev

    def test_earnings_far_no_alert(self):
        earn_date = (date.today() + timedelta(days=30)).isoformat()
        positions = [_pos("MSFT", 400, next_earnings=earn_date)]
        infos = {"MSFT": _info("MSFT", 420)}
        alerts = detect_alerts(positions, infos, {})
        earn_alerts = [a for a in alerts if a["type"] == "earnings_soon"]
        assert len(earn_alerts) == 0

    def test_vix_elevated(self):
        alerts = detect_alerts([], {}, {}, vix_price=27.5)
        vix_alerts = [a for a in alerts if a["type"] == "vix_high"]
        assert len(vix_alerts) == 1
        assert vix_alerts[0]["severity"] == "INFO"

    def test_vix_extreme(self):
        alerts = detect_alerts([], {}, {}, vix_price=35.0)
        vix_alerts = [a for a in alerts if a["type"] == "vix_high"]
        assert len(vix_alerts) == 1
        assert vix_alerts[0]["severity"] == "CRITICAL"

    def test_vix_normal_no_alert(self):
        alerts = detect_alerts([], {}, {}, vix_price=18.0)
        assert len(alerts) == 0

    def test_state_change_filter_keeps_critical(self):
        """CRITICAL は state-change フィルタを通過する (KIK-727)。

        exit-rule 抵触が継続している状態で2日目にアラートが消えると、
        最も重要な警告を見落とす。CRITICAL は毎日出し続ける。
        """
        positions = [_pos("CANON", 100)]
        infos = {"CANON": _info("CANON", 84)}
        histories = {"CANON": [85] * 20}
        prev = [{"symbol": "CANON", "type": "exit_rule"}]
        alerts = detect_alerts(positions, infos, histories, prev_alerts=prev)
        exit_alerts = [a for a in alerts if a["type"] == "exit_rule"]
        assert len(exit_alerts) == 1
        assert exit_alerts[0]["severity"] == "CRITICAL"

    def test_state_change_filter_suppresses_info(self):
        """INFO / WARN は前日と同じ symbol+type なら従来どおり抑制される。"""
        closes = [100 - i * 2 for i in range(20)]  # 下落継続 → rsi_low
        positions = [_pos("CANON", 60)]
        infos = {"CANON": _info("CANON", 62)}  # 損益 +3% で exit 系は無関係
        prev = [{"symbol": "CANON", "type": "rsi_low"}]
        alerts = detect_alerts(positions, infos, {"CANON": closes}, prev_alerts=prev)
        assert [a for a in alerts if a["type"] == "rsi_low"] == []

    def test_hard_stop_excludes_exit_rule(self):
        """At -21%, only hard_stop fires, not exit_rule (elif)."""
        positions = [_pos("DEC", 100)]
        infos = {"DEC": _info("DEC", 78)}  # -22%
        alerts = detect_alerts(positions, infos, {"DEC": [80]*20})
        types = [a["type"] for a in alerts if a["symbol"] == "DEC"]
        assert "hard_stop" in types
        assert "exit_rule" not in types

    def test_multiple_alerts_same_stock(self):
        """A stock can have exit_rule + rsi_low simultaneously."""
        closes = [100 - i * 3 for i in range(20)]  # descending → RSI low
        positions = [_pos("CANON", 100)]
        infos = {"CANON": _info("CANON", 84)}  # -16%
        alerts = detect_alerts(positions, infos, {"CANON": closes})
        types = [a["type"] for a in alerts if a["symbol"] == "CANON"]
        assert "exit_rule" in types
        assert "rsi_low" in types

    def test_malformed_earnings_date(self):
        """Malformed next_earnings should not crash."""
        positions = [_pos("TEST", 100, next_earnings="not-a-date")]
        infos = {"TEST": _info("TEST", 105)}
        alerts = detect_alerts(positions, infos, {})
        earn = [a for a in alerts if a["type"] == "earnings_soon"]
        assert len(earn) == 0  # graceful skip

    def test_format_truncates_critical(self):
        """More than 3 CRITICAL alerts: only first 3 shown."""
        alerts = [
            {"symbol": f"S{i}", "type": "exit_rule", "severity": "CRITICAL",
             "message": f"test{i}", "value": -16}
            for i in range(5)
        ]
        result = format_morning_summary(alerts)
        assert result.count("🔴") == 3

    def test_severity_ordering(self):
        """CRITICAL alerts come before INFO."""
        positions = [_pos("A", 100)]
        infos = {"A": _info("A", 84)}
        alerts = detect_alerts(positions, infos, {"A": [85]*20}, vix_price=27)
        # A: exit_rule (CRITICAL) + VIX (INFO)
        assert len(alerts) >= 2
        assert alerts[0]["severity"] == "CRITICAL"


# ---------------------------------------------------------------------------
# format_morning_summary
# ---------------------------------------------------------------------------

class TestFormatMorningSummary:
    def test_no_alerts(self):
        result = format_morning_summary([])
        assert "☀️ 異常なし" in result

    def test_with_alerts(self):
        alerts = [
            {"symbol": "CANON", "type": "exit_rule", "severity": "CRITICAL",
             "message": "損益-16% → exit-rule到達", "value": -16},
            {"symbol": "^VIX", "type": "vix_high", "severity": "INFO",
             "message": "VIX 27.5", "value": 27.5},
        ]
        result = format_morning_summary(alerts)
        assert "⚠️" in result
        assert "CANON" in result
        assert "VIX" in result

    def test_deepdive_suggestion(self):
        alerts = [
            {"symbol": "7751.T", "type": "exit_rule", "severity": "CRITICAL",
             "message": "test", "value": -16},
        ]
        result = format_morning_summary(alerts)
        assert "売るべきか" in result

    def test_includes_date(self):
        result = format_morning_summary([])
        today = date.today().strftime("%m/%d")
        assert today in result
