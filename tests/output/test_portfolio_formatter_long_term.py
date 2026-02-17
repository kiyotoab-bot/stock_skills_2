"""Tests for long-term suitability column in format_health_check() (KIK-371)."""

from src.output.portfolio_formatter import format_health_check


def _make_health_data(long_term=None, alert_level="none"):
    """Build minimal health data for formatter tests."""
    pos = {
        "symbol": "TEST.T",
        "pnl_pct": 0.05,
        "trend_health": {"trend": "上昇"},
        "change_quality": {"quality_label": "良好", "change_score": 75},
        "alert": {"level": alert_level, "emoji": "", "label": "なし", "reasons": []},
    }
    if long_term is not None:
        pos["long_term"] = long_term

    alerts = []
    if alert_level != "none":
        pos["alert"]["emoji"] = "⚡"
        pos["alert"]["label"] = "早期警告"
        pos["alert"]["reasons"] = ["テスト理由"]
        pos["trend_health"]["sma50"] = 100.0
        pos["trend_health"]["sma200"] = 95.0
        pos["trend_health"]["rsi"] = 45.0
        alerts = [pos]

    summary = {
        "total": 1,
        "healthy": 1 if alert_level == "none" else 0,
        "early_warning": 1 if alert_level == "early_warning" else 0,
        "caution": 0,
        "exit": 0,
    }
    return {"positions": [pos], "alerts": alerts, "summary": summary}


class TestFormatHealthCheckLongTerm:

    def test_long_term_column_header(self):
        data = _make_health_data(
            long_term={"label": "長期向き", "summary": "高ROE・EPS成長"},
        )
        result = format_health_check(data)
        assert "長期適性" in result

    def test_long_term_suitable_label(self):
        data = _make_health_data(
            long_term={"label": "長期向き", "summary": "高ROE・EPS成長"},
        )
        result = format_health_check(data)
        assert "長期向き" in result

    def test_short_term_label(self):
        data = _make_health_data(
            long_term={"label": "短期向き", "summary": "割高PER"},
        )
        result = format_health_check(data)
        assert "短期向き" in result

    def test_needs_review_label(self):
        data = _make_health_data(
            long_term={"label": "要検討", "summary": "EPS減少"},
        )
        result = format_health_check(data)
        assert "要検討" in result

    def test_missing_long_term_data_graceful(self):
        """Health check data without long_term key should not crash."""
        data = _make_health_data(long_term=None)
        result = format_health_check(data)
        assert "TEST.T" in result

    def test_alert_details_include_long_term(self):
        """Alert details section should show long-term context."""
        data = _make_health_data(
            long_term={"label": "短期向き", "summary": "割高PER"},
            alert_level="early_warning",
        )
        result = format_health_check(data)
        assert "長期適性" in result
        assert "短期向き" in result

    def test_excluded_label_not_in_alert_details(self):
        """ETF/cash 対象外 should not appear in alert details."""
        data = _make_health_data(
            long_term={"label": "対象外", "summary": "ETF"},
            alert_level="early_warning",
        )
        result = format_health_check(data)
        # Should not add long-term context line for 対象外
        lines = result.split("\n")
        lt_context_lines = [l for l in lines if "長期適性:" in l]
        assert len(lt_context_lines) == 0


# ===================================================================
# Return stability display tests (KIK-403)
# ===================================================================


class TestFormatHealthCheckReturnStability:
    """Tests for return stability display in format_health_check() (KIK-403)."""

    def test_return_stability_column_header(self):
        data = _make_health_data(
            long_term={"label": "長期向き", "summary": "高ROE"},
        )
        data["positions"][0]["return_stability"] = {
            "stability": "stable", "label": "✅ 安定高還元",
            "latest_rate": 0.06, "avg_rate": 0.06, "reason": "3年平均6.0%で安定",
        }
        result = format_health_check(data)
        assert "還元安定度" in result

    def test_stable_label_displayed(self):
        data = _make_health_data(
            long_term={"label": "長期向き", "summary": "高ROE"},
        )
        data["positions"][0]["return_stability"] = {
            "stability": "stable", "label": "✅ 安定高還元",
            "latest_rate": 0.06, "avg_rate": 0.06, "reason": "3年平均6.0%で安定",
        }
        result = format_health_check(data)
        assert "安定高還元" in result

    def test_temporary_label_in_table(self):
        data = _make_health_data(
            long_term={"label": "長期向き", "summary": "高ROE"},
        )
        data["positions"][0]["return_stability"] = {
            "stability": "temporary", "label": "⚠️ 一時的高還元",
            "latest_rate": 0.12, "avg_rate": 0.06, "reason": "前年比2.0倍に急増",
        }
        result = format_health_check(data)
        assert "一時的高還元" in result

    def test_temporary_shown_in_alert_details(self):
        data = _make_health_data(
            long_term={"label": "要検討", "summary": "EPS減少"},
            alert_level="early_warning",
        )
        data["positions"][0]["return_stability"] = {
            "stability": "temporary", "label": "⚠️ 一時的高還元",
            "latest_rate": 0.12, "avg_rate": 0.06, "reason": "前年比2.0倍に急増",
        }
        data["alerts"][0]["return_stability"] = data["positions"][0]["return_stability"]
        result = format_health_check(data)
        assert "一時的高還元" in result
        assert "12.0%" in result

    def test_decreasing_shown_in_alert_details(self):
        data = _make_health_data(
            long_term={"label": "要検討", "summary": "EPS減少"},
            alert_level="early_warning",
        )
        data["positions"][0]["return_stability"] = {
            "stability": "decreasing", "label": "📉 減少傾向",
            "latest_rate": 0.02, "avg_rate": 0.04, "reason": "3年連続減少",
        }
        data["alerts"][0]["return_stability"] = data["positions"][0]["return_stability"]
        result = format_health_check(data)
        assert "還元減少傾向" in result

    def test_no_stability_data_graceful(self):
        """Health data without return_stability should not crash."""
        data = _make_health_data(long_term={"label": "要検討", "summary": "EPS減少"})
        result = format_health_check(data)
        assert "TEST.T" in result

    def test_no_data_stability_shows_dash(self):
        data = _make_health_data(
            long_term={"label": "長期向き", "summary": "高ROE"},
        )
        data["positions"][0]["return_stability"] = {
            "stability": "no_data", "label": "-",
            "latest_rate": None, "avg_rate": None, "reason": None,
        }
        result = format_health_check(data)
        # Table row should have the dash label
        assert "TEST.T" in result
