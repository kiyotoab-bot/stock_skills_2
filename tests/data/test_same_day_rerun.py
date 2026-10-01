"""同じ日にルーティンを2回回しても記録が消えず、RL6 が当日バーを外さない（KIK-777）.

2026-09-30 に日次を 01:05（9/29 バー）と 23:50（9/30 バー）の2回実行した。
- save_routine_report / save_review が同名で上書きし、1回目の記録を消しかけた
- latest_review_date() が保存日 9/30 を返し、RL6 の since=9/30 で 9/30 バーが判定から外れた
"""

import datetime
import json

from src.data.checklist_review import (
    check_stop_breach, free_suffix, latest_review_date, next_stop_breach_since,
    run_review, save_review,
)
from src.data.morning_summary import latest_routine_dates, save_routine_report

STOPS = {"8031.T": {"stop": 4721.0}}


def _rl6(histories, since=None):
    prices = {s: h[-1][1] for s, h in histories.items()}
    return check_stop_breach(prices, STOPS, histories=histories, since=since)


class TestFreeSuffix:
    def test_empty_when_nothing_exists(self, tmp_path):
        assert free_suffix([tmp_path / "daily_20260930{}.md"]) == ""

    def test_hhmm_when_base_exists(self, tmp_path):
        (tmp_path / "daily_20260930.md").write_text("x", encoding="utf-8")
        now = datetime.datetime(2026, 9, 30, 23, 50, 7)
        assert free_suffix([tmp_path / "daily_20260930{}.md"], now) == "_2350"

    def test_falls_back_to_seconds_then_counter(self, tmp_path):
        for n in ("daily_20260930.md", "daily_20260930_2350.md", "daily_20260930_235007.md"):
            (tmp_path / n).write_text("x", encoding="utf-8")
        now = datetime.datetime(2026, 9, 30, 23, 50, 7)
        assert free_suffix([tmp_path / "daily_20260930{}.md"], now) == "_235007-2"

    def test_all_patterns_must_be_free(self, tmp_path):
        """md が空いていても json が埋まっていれば接尾辞を付ける（md と json を揃える）."""
        (tmp_path / "daily_20260930.json").write_text("{}", encoding="utf-8")
        now = datetime.datetime(2026, 9, 30, 23, 50)
        got = free_suffix([tmp_path / "daily_20260930{}.md",
                           tmp_path / "daily_20260930{}.json"], now)
        assert got == "_2350"

    def test_braces_in_directory_do_not_break(self, tmp_path):
        d = tmp_path / "a{b}"
        d.mkdir()
        assert free_suffix([d / "x{}.md"]) == ""


class TestSaveDoesNotOverwrite:
    def test_routine_report_second_run_keeps_first(self, tmp_path):
        rep, log = tmp_path / "rep", tmp_path / "log"
        day = datetime.date(2026, 9, 30)
        a = save_routine_report("daily", "# 01:05", {"n": 1}, day, str(rep), str(log))
        b = save_routine_report("daily", "# 23:50", {"n": 2}, day, str(rep), str(log))
        assert a["markdown"] != b["markdown"] and a["json"] != b["json"]
        assert (rep / "daily_20260930.md").read_text(encoding="utf-8") == "# 01:05"
        assert json.loads((log / "daily_20260930.json").read_text(encoding="utf-8"))["n"] == 1
        # md と json は同じ接尾辞
        sfx = b["markdown"].replace("\\", "/").rsplit("daily_20260930", 1)[1][:-3]
        assert b["json"].endswith(f"daily_20260930{sfx}.json")

    def test_freshness_counts_suffixed_report(self, tmp_path):
        (tmp_path / "daily_20260930_2350.md").write_text("x", encoding="utf-8")
        (tmp_path / "daily_20260929.md").write_text("x", encoding="utf-8")
        assert latest_routine_dates(str(tmp_path))["daily"] == "2026-09-30"

    def test_freshness_ignores_unrelated_names(self, tmp_path):
        (tmp_path / "daily_20261005_backup.md").write_text("x", encoding="utf-8")
        (tmp_path / "daily_20260929.md").write_text("x", encoding="utf-8")
        assert latest_routine_dates(str(tmp_path))["daily"] == "2026-09-29"

    def test_review_second_run_keeps_first(self, tmp_path):
        a = save_review({"verdict": "PASS", "n": 1}, str(tmp_path), label="daily")
        b = save_review({"verdict": "WARN", "n": 2}, str(tmp_path), label="daily")
        assert a != b
        assert json.loads(open(a, encoding="utf-8").read())["n"] == 1
        # 接尾辞付きでも保存日は拾える（REVIEW の最終レビュー日）
        assert latest_review_date(str(tmp_path)) == datetime.date.today().isoformat()


class TestStopBreachSince:
    H_0929 = {"8031.T": [("2026-09-26", 4990.0, 4950.0), ("2026-09-29", 4829.0, 4825.0)]}
    H_0930 = {"8031.T": [("2026-09-26", 4990.0, 4950.0), ("2026-09-29", 4829.0, 4825.0),
                         ("2026-09-30", 4930.0, 4700.0)]}      # 9/30 安値がトリガー割れ

    def test_rl6_records_cursor_per_symbol(self):
        r = _rl6(self.H_0929, since="2026-09-28")[0]
        assert r["stop_cursor"] == {"8031.T": {"date": "2026-09-29", "stop": 4721.0}}

    def test_no_since_does_not_advance_cursor(self):
        """since 省略は最新バーしか見ていない。判定範囲を記録しない（レビュー指摘 3）."""
        assert "stop_cursor" not in _rl6(self.H_0929)[0]

    def test_run_review_saves_cursor(self, tmp_path):
        r = run_review(_rl6(self.H_0929, since="2026-09-28"),
                       reviews_dir=str(tmp_path), label="daily")
        assert r["rl6_cursor"]["8031.T"]["date"] == "2026-09-29"

    def test_rerun_same_day_still_sees_that_days_bar(self, tmp_path):
        """01:05 に 9/29 バーで判定 → 同日夜は 9/30 バーを見る（この issue の本体）."""
        run_review(_rl6(self.H_0929, since="2026-09-28"),
                   reviews_dir=str(tmp_path), label="daily")
        # 旧実装（保存日）だと since=今日 になり、9/30 のトリガー割れを見落とす
        assert latest_review_date(str(tmp_path)) == datetime.date.today().isoformat()
        r = _rl6(self.H_0930, since=next_stop_breach_since(str(tmp_path)))[0]
        assert r["status"] == "FAIL" and "2026-09-30" in r["detail"]

    def test_previous_latest_bar_rechecked_with_its_own_stop(self):
        """前回の最新バーは未確定だったかもしれないので見直す。確定値で割っていれば出す."""
        cur = {"8031.T": {"date": "2026-09-30", "stop": 4721.0}}
        r = _rl6(self.H_0930, since=cur)[0]
        assert r["status"] == "FAIL" and "2026-09-30" in r["detail"]

    def test_raised_stop_is_not_applied_to_rechecked_bar(self):
        """ストップ切り上げ後、前日バーに新ストップを当てて偽の抵触を出さない（レビュー指摘 1）."""
        stops = {"8031.T": {"stop": 4850.0}}                      # 10/1 に 4721 → 4850
        h = {"8031.T": [("2026-09-30", 4930.0, 4800.0), ("2026-10-01", 5100.0, 5000.0)]}
        cur = {"8031.T": {"date": "2026-09-30", "stop": 4721.0}}  # 9/30 は 4721 で判定済み
        r = check_stop_breach({"8031.T": 5100.0}, stops, histories=h, since=cur)[0]
        assert r["status"] != "FAIL", r["detail"]
        assert r["stop_cursor"]["8031.T"] == {"date": "2026-10-01", "stop": 4850.0}

    def test_no_new_bar_keeps_the_stop_the_bar_was_judged_with(self):
        stops = {"8031.T": {"stop": 4850.0}}
        h = {"8031.T": [("2026-09-30", 4930.0, 4800.0)]}
        cur = {"8031.T": {"date": "2026-09-30", "stop": 4721.0}}
        r = check_stop_breach({"8031.T": 4930.0}, stops, histories=h, since=cur)[0]
        assert r["stop_cursor"]["8031.T"] == {"date": "2026-09-30", "stop": 4721.0}

    def test_stale_symbol_does_not_hold_back_others(self, tmp_path):
        """1銘柄の履歴が止まっても他銘柄の起点は進む（レビュー指摘 2）."""
        stops = {"A": {"stop": 100.0}, "B": {"stop": 100.0}}
        h = {"A": [("2026-09-01", 90.0, 90.0), ("2026-09-30", 150.0, 150.0)],   # 9/1 に割れていた
             "B": [("2026-06-30", 150.0, 150.0)]}                                # 6/30 で停止
        (tmp_path / "checklist_daily_20260930.json").write_text(json.dumps(
            {"rl6_cursor": {"A": {"date": "2026-09-29", "stop": 100.0},
                            "B": {"date": "2026-06-30", "stop": 100.0}}}), encoding="utf-8")
        r = check_stop_breach({"A": 150.0, "B": 150.0}, stops, histories=h,
                              since=next_stop_breach_since(str(tmp_path)))[0]
        # A の 9/1 は見ない。B は購入日が分からないので起点を戻すが、黙らず WARN（KIK-778）
        assert r["status"] == "WARN", r["detail"]
        assert "購入日不明" in r["detail"] and "B（前回 2026-06-30）" in r["detail"]

    def test_new_holding_starts_after_latest_cursor(self):
        stops = {"8031.T": {"stop": 4721.0}, "NEW": {"stop": 100.0}}
        h = {"8031.T": [("2026-09-30", 4930.0, 4900.0)],
             "NEW": [("2026-09-20", 90.0, 90.0), ("2026-09-30", 150.0, 150.0)]}   # 買う前の安値
        cur = {"8031.T": {"date": "2026-09-29", "stop": 4721.0}}
        r = check_stop_breach({"8031.T": 4930.0, "NEW": 150.0}, stops, histories=h, since=cur)[0]
        assert r["status"] == "PASS", r["detail"]
        assert r["stop_cursor"]["NEW"]["date"] == "2026-09-30"

    def test_timestamp_dates_are_normalised(self):
        import pandas as pd
        h = {"8031.T": [(pd.Timestamp("2026-09-29"), 4829.0, 4825.0),
                        (pd.Timestamp("2026-09-30"), 4930.0, 4700.0)]}
        r = _rl6(h, since="2026-09-29")[0]
        assert r["status"] == "FAIL" and r["stop_cursor"]["8031.T"]["date"] == "2026-09-30"

    def test_merge_takes_latest_date_per_symbol_and_lower_stop_on_tie(self, tmp_path):
        (tmp_path / "checklist_daily_20260930.json").write_text(json.dumps(
            {"rl6_cursor": {"A": {"date": "2026-09-29", "stop": 10.0},
                            "B": {"date": "2026-09-30", "stop": 12.0}}}), encoding="utf-8")
        (tmp_path / "checklist_daily_20260930_2350.json").write_text(json.dumps(
            {"rl6_cursor": {"A": {"date": "2026-09-30", "stop": 11.0},
                            "B": {"date": "2026-09-30", "stop": 11.5},
                            "C": {"date": "2026/09/30", "stop": 1.0},        # 読めない日付は捨てる
                            "D": {"date": "2026-09-30", "stop": None}}}), encoding="utf-8")
        got = next_stop_breach_since(str(tmp_path))
        assert got == {"A": {"date": "2026-09-30", "stop": 11.0},
                       "B": {"date": "2026-09-30", "stop": 11.5}}

    def test_legacy_records_fall_back_to_review_date(self, tmp_path):
        (tmp_path / "checklist_daily_20260925.json").write_text("{}", encoding="utf-8")
        assert next_stop_breach_since(str(tmp_path)) == "2026-09-25"

    def test_missing_dir_and_broken_json(self, tmp_path):
        assert next_stop_breach_since(str(tmp_path / "nope")) is None
        (tmp_path / "checklist_daily_20260930.json").write_text("{broken", encoding="utf-8")
        assert next_stop_breach_since(str(tmp_path)) == "2026-09-30"


class TestCursorEdgeCases:
    """再レビュー指摘（KIK-777）."""

    def test_touch_after_raising_stop_is_warned_not_silenced(self):
        """判定→切り上げ→同じバーで安値到達。前回ストップより上なので FAIL ではないが WARN で出す."""
        stops = {"A": {"stop": 105.0}}
        h = {"A": [("2026-10-01", 120.0, 104.0)]}
        cur = {"A": {"date": "2026-10-01", "stop": 100.0}}
        r = check_stop_breach({"A": 120.0}, stops, histories=h, since=cur)[0]
        assert r["status"] == "WARN" and "切り上げ後に触れた可能性" in r["detail"]

    def test_no_warn_when_bar_stays_above_raised_stop(self):
        stops = {"A": {"stop": 105.0}}
        h = {"A": [("2026-10-01", 120.0, 110.0)]}
        cur = {"A": {"date": "2026-10-01", "stop": 100.0}}
        r = check_stop_breach({"A": 120.0}, stops, histories=h, since=cur)[0]
        assert r["status"] == "PASS", r["detail"]

    def test_rebought_symbol_does_not_judge_unheld_period(self):
        """7月に売って10月に買い直した銘柄を、保有していない期間で FAIL にしない."""
        stops = {"A": {"stop": 100.0}, "B": {"stop": 10.0}}
        h = {"A": [("2026-08-01", 80.0, 80.0), ("2026-10-01", 120.0, 118.0)],
             "B": [("2026-10-01", 20.0, 20.0)]}
        cur = {"A": {"date": "2026-07-01", "stop": 90.0}, "B": {"date": "2026-09-30", "stop": 10.0}}
        r = check_stop_breach({"A": 120.0, "B": 20.0}, stops, histories=h, since=cur)[0]
        # 購入日が無いので買い直しと断定できず WARN。FAIL にはしない（KIK-778）
        assert r["status"] == "WARN", r["detail"]
        assert "新規保有扱い" in r["detail"] and r["stop_cursor"]["A"]["date"] == "2026-10-01"

    def test_empty_cursor_behaves_like_no_since(self):
        h = {"8031.T": [("2026-09-01", 4000.0, 4000.0), ("2026-09-30", 4930.0, 4900.0)]}
        r = check_stop_breach({"8031.T": 4930.0}, STOPS, histories=h, since={})[0]
        assert r["status"] == "PASS" and "stop_cursor" not in r
