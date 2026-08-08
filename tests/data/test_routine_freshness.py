"""Tests for routine freshness detection (KIK-733).

週次レビューにしか含まれない項目（リスク判定・アクションプラン・レビュー・需給）は、
週次を回さないと誰も気づかないまま抜け続ける。実際 2026-07-27 から 08-06 まで
10日間、週次が一度も実行されず、その間にリスク判定・Reviewer・需給がすべて
抜けていた（需給はユーザーの指摘で発覚した）。日次の側から検知できるようにする。
"""

from datetime import date

import pytest

from src.data.morning_summary import (
    ROUTINE_STALE_DAYS,
    check_routine_freshness,
    latest_routine_dates,
)

TODAY = date(2026, 8, 6)


def _types(alerts):
    return {a["type"]: a for a in alerts}


class TestCheckRoutineFreshness:
    def test_the_actual_incident_is_warn(self):
        """実際に起きた状況: 週次が 2026-07-27 で止まっていた（10日）。"""
        got = _types(check_routine_freshness(
            {"weekly": "2026-07-27", "daily": "2026-08-05"}, TODAY))
        assert got["weekly_stale"]["severity"] == "WARN"
        assert got["weekly_stale"]["value"] == 10
        assert "リスク判定" in got["weekly_stale"]["message"]
        assert "daily_stale" not in got

    def test_fresh_weekly_is_silent(self):
        got = check_routine_freshness(
            {"weekly": "2026-08-03", "daily": "2026-08-06",
             "monthly": "2026-08-01"}, TODAY)
        assert got == []

    @pytest.mark.parametrize("last,expect", [
        ("2026-08-01", None),        # 5日 — 閾値未満
        ("2026-07-30", "WARN"),      # 7日
        ("2026-07-24", "WARN"),      # 13日
        ("2026-07-23", "CRITICAL"),  # 14日
        ("2026-06-01", "CRITICAL"),  # 66日
    ])
    def test_weekly_thresholds(self, last, expect):
        got = _types(check_routine_freshness({"weekly": last, "daily": "2026-08-06"}, TODAY))
        if expect is None:
            assert "weekly_stale" not in got
        else:
            assert got["weekly_stale"]["severity"] == expect

    @pytest.mark.parametrize("last,expect", [
        ("2026-08-05", None),        # 1日
        ("2026-08-03", "WARN"),      # 3日
        ("2026-07-30", "CRITICAL"),  # 7日
    ])
    def test_daily_thresholds(self, last, expect):
        got = _types(check_routine_freshness(
            {"weekly": "2026-08-06", "daily": last, "monthly": "2026-08-01"}, TODAY))
        if expect is None:
            assert "daily_stale" not in got
        else:
            assert got["daily_stale"]["severity"] == expect

    def test_never_run_is_reported_not_skipped(self):
        """記録が無いことを「問題なし」と誤読しないこと。"""
        got = _types(check_routine_freshness(
            {"weekly": None, "daily": None, "monthly": None}, TODAY))
        assert got["weekly_never_run"]["severity"] == "WARN"
        assert got["daily_never_run"]["severity"] == "WARN"
        assert got["monthly_never_run"]["severity"] == "WARN"

    def test_missing_key_is_treated_as_never_run(self):
        got = _types(check_routine_freshness({}, TODAY))
        assert "weekly_never_run" in got and "daily_never_run" in got
        assert "monthly_never_run" in got

    def test_malformed_date_does_not_raise(self):
        got = check_routine_freshness({"weekly": "not-a-date", "daily": "2026-08-06"}, TODAY)
        assert all(a["type"] != "weekly_stale" for a in got)

    def test_both_can_fire(self):
        got = _types(check_routine_freshness(
            {"weekly": "2026-06-01", "daily": "2026-07-01"}, TODAY))
        assert got["weekly_stale"]["severity"] == "CRITICAL"
        assert got["daily_stale"]["severity"] == "CRITICAL"

    def test_alerts_use_routine_symbol(self):
        got = check_routine_freshness({"weekly": "2026-06-01"}, TODAY)
        assert all(a["symbol"] == "ROUTINE" for a in got)

    def test_weekly_message_names_what_is_missing(self):
        """『週次が古い』だけでは何が抜けたか分からない。"""
        got = _types(check_routine_freshness({"weekly": "2026-07-27"}, TODAY))
        msg = got["weekly_stale"]["message"]
        for word in ("リスク判定", "レビュー", "需給"):
            assert word in msg


class TestLatestRoutineDates:
    def test_reads_report_filenames(self, tmp_path):
        for name in ["daily_20260804.md", "daily_20260805.md",
                     "weekly_20260718.md", "weekly_20260727.md"]:
            (tmp_path / name).write_text("x", encoding="utf-8")
        got = latest_routine_dates(str(tmp_path))
        assert got == {"daily": "2026-08-05", "weekly": "2026-07-27", "monthly": None}

    def test_missing_dir_returns_nones(self, tmp_path):
        got = latest_routine_dates(str(tmp_path / "nope"))
        assert got == {"daily": None, "weekly": None, "monthly": None}

    def test_ignores_non_date_filenames(self, tmp_path):
        (tmp_path / "daily_draft.md").write_text("x", encoding="utf-8")
        (tmp_path / "weekly_20260727.md").write_text("x", encoding="utf-8")
        got = latest_routine_dates(str(tmp_path))
        assert got["daily"] is None
        assert got["weekly"] == "2026-07-27"


def test_thresholds_are_ordered():
    for kind, thr in ROUTINE_STALE_DAYS.items():
        assert thr["warn"] < thr["critical"], kind


class TestSaveRoutineReport:
    """2026-08-06 に日次を3回実行しながら保存を怠った件。

    Markdown と JSON を別々に書く手順だったため「実行したが記録していない」が起きた。
    1呼び出しにまとめて書き忘れの余地を減らす。
    """

    def test_writes_both_files(self, tmp_path):
        from src.data.morning_summary import save_routine_report
        got = save_routine_report(
            "daily", "# レポート", {"total": 123}, date(2026, 8, 7),
            reports_dir=str(tmp_path / "rep"), logs_dir=str(tmp_path / "log"))
        assert (tmp_path / "rep" / "daily_20260807.md").read_text(encoding="utf-8") == "# レポート"
        import json
        payload = json.loads((tmp_path / "log" / "daily_20260807.json").read_text(encoding="utf-8"))
        assert payload["date"] == "2026-08-07"
        assert payload["mode"] == "routine-daily"
        assert payload["total"] == 123
        assert set(got) == {"markdown", "json"}

    def test_markdown_only_when_no_data(self, tmp_path):
        from src.data.morning_summary import save_routine_report
        got = save_routine_report("weekly", "# W", None, date(2026, 8, 7),
                                  reports_dir=str(tmp_path), logs_dir=str(tmp_path / "l"))
        assert "json" not in got
        assert (tmp_path / "weekly_20260807.md").exists()

    def test_saved_report_clears_staleness(self, tmp_path):
        """保存すれば鮮度チェックが解消することの確認。"""
        from src.data.morning_summary import (
            check_routine_freshness, latest_routine_dates, save_routine_report)
        rep = tmp_path / "rep"
        save_routine_report("daily", "# x", None, date(2026, 8, 7), reports_dir=str(rep))
        save_routine_report("weekly", "# y", None, date(2026, 8, 7), reports_dir=str(rep))
        save_routine_report("monthly", "# m", None, date(2026, 8, 1), reports_dir=str(rep))
        got = check_routine_freshness(latest_routine_dates(str(rep)), date(2026, 8, 7))
        assert got == []

    def test_rejects_unknown_kind(self, tmp_path):
        from src.data.morning_summary import save_routine_report
        # KIK-738 で monthly は有効な kind になったので、別の未知値で確かめる
        with pytest.raises(ValueError):
            save_routine_report("yearly", "# x", None, date(2026, 8, 7),
                                reports_dir=str(tmp_path))
