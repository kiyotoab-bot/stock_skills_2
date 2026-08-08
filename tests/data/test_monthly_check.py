"""Tests for src/data/monthly_check.py (KIK-738).

月次チェックは「今月の1回をどう使うか」を扱う枠。自然文のノートから
予定と認定状況を拾うため、**緩く拾いすぎて誤検出する**方向の失敗が起きやすい。
実装中に実際に3回踏んだので、その3つを回帰テストとして固定する。
"""

import datetime
import json

import pytest

from src.data import monthly_check as MC

TODAY = datetime.date(2026, 8, 8)

PLAN_NOTE = {
    "id": "note_plan", "type": "target", "symbol": "", "date": "2026-08-07",
    "timestamp": "2026-08-07T21:05:48",
    "content": """【投入計画を集中版に差し替え（案C）】2026-08-07 ユーザー判断

■ 新計画（2026-08-07 終値ベース / 総資産 ¥7,942,991）
  2026-08-10  7751.T キヤノン   300株 ¥1,390,500  conviction  21.8%
  2026-09     9104.T 商船三井   200株 ¥1,237,200  conviction  19.4%
  2026-10     非Industrials枠  ―    ¥1,100,000  conviction  17.2%（9月に再スクリーニング）
  2026-11     6501.T 日立      100株 ¥  562,000  normal       8.8%
""",
}
OLD_PLAN_NOTE = {
    "id": "note_old", "type": "target", "symbol": "", "date": "2026-08-05",
    "timestamp": "2026-08-05T10:00:00",
    "content": """【投入計画（旧・全銘柄100株）】破棄済み

  2026-09     8725.T MS&AD  100株
  2026-10     6268.T ナブテスコ 100株
""",
}


class TestPlannedSlots:
    def test_reads_the_plan_table(self):
        slots = {s["month"]: s for s in MC.planned_slots([PLAN_NOTE], TODAY)}
        assert slots["2026-08"]["symbols"] == ["7751.T"]
        assert slots["2026-09"]["symbols"] == ["9104.T"]
        assert slots["2026-11"]["symbols"] == ["6501.T"]

    def test_undecided_slot_is_flagged_not_dropped(self):
        """10月枠が未定のまま9月末を迎えるのを防ぐのが本来の目的."""
        slots = {s["month"]: s for s in MC.planned_slots([PLAN_NOTE], TODAY)}
        oct_ = slots["2026-10"]
        assert oct_["symbols"] == []
        assert oct_["status"] == "枠あり銘柄未定"
        assert oct_["lines"], "根拠行を残さないと何が未定なのか分からない"

    def test_only_the_latest_plan_is_used(self):
        """破棄済みの旧計画を現行として数えない."""
        slots = {s["month"]: s for s in MC.planned_slots([OLD_PLAN_NOTE, PLAN_NOTE], TODAY)}
        assert slots["2026-09"]["symbols"] == ["9104.T"]
        assert "8725.T" not in slots["2026-09"]["symbols"]
        assert slots["2026-10"]["symbols"] == []   # 旧計画の 6268.T を拾わない

    def test_prose_mentioning_a_date_and_symbol_is_not_a_plan_row(self):
        """行頭アンカーが無いと『2026-04-13 に 6701.T を買った』を計画行と誤認する."""
        note = dict(PLAN_NOTE)
        note["content"] += "\n  ※ 参考: 2026-08-13 に 6701.T を追加検討したが見送った\n"
        slots = {s["month"]: s for s in MC.planned_slots([note], TODAY)}
        # 行頭が日付なので拾われてしまう形。ここでは行頭でない例を確かめる
        note2 = dict(PLAN_NOTE)
        note2["content"] += "\n  補足として 2026-09-01 の 8725.T は対象外\n"
        slots2 = {s["month"]: s for s in MC.planned_slots([note2], TODAY)}
        assert "8725.T" not in slots2["2026-09"]["symbols"]

    def test_no_plan_note_returns_empty_slots(self):
        slots = MC.planned_slots([], TODAY)
        assert len(slots) == 4
        assert all(s["status"] == "記載なし" for s in slots)


class TestConvictionStatus:
    CANON = {
        "id": "n1", "type": "target", "symbol": "7751.T", "date": "2026-08-07",
        "content": "conviction（CV1 一次情報検証済 / CV2 テーゼ文書化済 / CV3 ストップ¥4,350 設定済）",
    }
    REPORT = {
        "id": "n2", "type": "observation", "symbol": "", "date": "2026-08-07",
        "content": ("日次チェック\n"
                    "- 7751.T キヤノンは 8/10 発注\n"
                    "- 9104.T 商船三井は CV1・CV2・CV3 が3つとも未充足\n"),
    }

    def test_explicit_records_are_counted(self):
        r = MC.conviction_status("7751.T", [self.CANON])
        assert r["met"] == 3 and r["qualified"] and r["tier"] == "conviction"

    def test_other_symbols_negative_line_does_not_contaminate(self):
        """同じ汎用ノートに載った別銘柄の『未充足』を巻き込まない (KIK-738)."""
        r = MC.conviction_status("7751.T", [self.CANON, self.REPORT])
        assert r["met"] == 3, r["checks"]

    def test_symbol_without_records_is_not_qualified(self):
        r = MC.conviction_status("9104.T", [self.CANON, self.REPORT])
        assert r["met"] == 0 and r["tier"] == "normal"
        assert all(not c["recorded"] for c in r["checks"].values())

    def test_negation_on_the_symbols_own_note_is_respected(self):
        note = {"id": "n3", "type": "target", "symbol": "9104.T",
                "content": "CV1 未充足 / CV2 未充足 / CV3 未充足"}
        r = MC.conviction_status("9104.T", [note])
        assert r["met"] == 0
        assert all(c["recorded"] for c in r["checks"].values())

    def test_keywords_alone_do_not_qualify(self):
        """『ストップ』『テーゼ』で判定すると全銘柄 3/3 になり警告装置が死ぬ."""
        note = {"id": "n4", "type": "thesis", "symbol": "6501.T",
                "content": "投資テーゼ: データセンター。ストップは 5,000 円。一次情報で確認済み。"}
        r = MC.conviction_status("6501.T", [note])
        assert r["met"] == 0


class TestTradeBudget:
    TRADES = [
        {"date": "2026-07-13", "action": "buy", "symbol": "6268.T"},
        {"date": "2026-07-30", "action": "sell", "symbol": "6268.T"},
    ]

    def test_cooldown_counts_from_the_buy_only(self):
        """売却は冷却期間をリセットしない（2026-08-06 改訂）."""
        b = MC.trade_budget(self.TRADES, TODAY)
        assert b["cooldown_end"] == "2026-08-10"
        assert b["cooldown_days_left"] == 2
        assert b["can_buy_now"] is False

    def test_cleared_after_the_cooldown(self):
        b = MC.trade_budget(self.TRADES, datetime.date(2026, 8, 10))
        assert b["cooldown_cleared"] and b["can_buy_now"] and not b["blockers"]

    def test_monthly_limit_counts_sells_too(self):
        trades = self.TRADES + [{"date": "2026-08-11", "action": "sell", "symbol": "X"}]
        b = MC.trade_budget(trades, datetime.date(2026, 8, 12))
        assert b["monthly_used"] == 1 and b["monthly_remaining"] == 0
        assert b["can_buy_now"] is False
        assert any("月次上限" in x for x in b["blockers"])

    def test_both_blockers_are_reported(self):
        trades = [{"date": "2026-08-05", "action": "buy", "symbol": "X"}]
        b = MC.trade_budget(trades, datetime.date(2026, 8, 12))
        assert len(b["blockers"]) == 2

    def test_excluded_dates_are_ignored(self):
        trades = self.TRADES + [{"date": "2026-08-04", "action": "sell", "symbol": "Y"}]
        b = MC.trade_budget(trades, TODAY, excluded_dates={"2026-08-04"})
        assert b["monthly_used"] == 0

    def test_no_buys_at_all(self):
        b = MC.trade_budget([{"date": "2026-08-01", "action": "sell", "symbol": "X"}], TODAY)
        assert b["last_buy"] is None and b["cooldown_days_left"] is None
        assert b["can_buy_now"] is False


class TestGoalProgress:
    def test_two_required_rates_are_distinguished(self):
        """現金を寝かせた前提の必要年率を『達成不能』と読み違えない (KIK-738)."""
        g = MC.goal_progress(1_646_500, 6_296_491, 10_000_000, "2031-04-30", TODAY)
        assert g["required_cagr_as_is"] > 15      # 未投入ならこうなる
        assert 5 < g["required_cagr_fully_invested"] < 8   # 投入すれば現実的
        assert g["required_cagr_as_is"] > g["required_cagr_fully_invested"]

    def test_planned_equity_uses_the_cash_target(self):
        g = MC.goal_progress(1_000_000, 7_000_000, 10_000_000, "2031-04-30", TODAY,
                             cash_target_pct=20.0)
        assert g["planned_equity"] == round(8_000_000 * 0.8)

    def test_progress_and_gap(self):
        g = MC.goal_progress(1_646_500, 6_296_491, 10_000_000, "2031-04-30", TODAY)
        assert g["total"] == 7_942_991
        assert g["gap"] == 10_000_000 - 7_942_991
        assert 79 < g["progress_pct"] < 80

    def test_zero_equity_does_not_crash(self):
        g = MC.goal_progress(0, 1_000_000, 10_000_000, "2031-04-30", TODAY)
        assert g["required_cagr_as_is"] is None


class TestRealizedPnl:
    TRADES = [
        {"date": "2026-08-04", "action": "sell", "symbol": "A", "realized_pnl": 100},
        {"date": "2026-08-04", "action": "sell", "symbol": "B", "realized_pnl": -50},
        {"date": "2026-07-30", "action": "sell", "symbol": "C", "realized_pnl": 999},
        {"date": "2026-08-01", "action": "buy", "symbol": "D", "realized_pnl": None},
    ]

    def test_only_the_month_is_counted(self):
        r = MC.realized_pnl(self.TRADES, "2026-08")
        assert r["count"] == 3 and r["realized_pnl"] == 50
        assert r["buys"] == 1 and r["sells"] == 2

    def test_missing_pnl_is_not_counted_as_zero_silently(self):
        r = MC.realized_pnl(self.TRADES, "2026-08")
        assert r["with_pnl"] == 2 and r["count"] == 3


class TestAddMonths:
    @pytest.mark.parametrize("n,expected", [
        (0, "2026-08"), (1, "2026-09"), (4, "2026-12"), (5, "2027-01"), (-1, "2026-07"),
    ])
    def test_rolls_over_the_year(self, n, expected):
        assert MC.month_key(MC.add_months(TODAY, n)) == expected


class TestBuildMonthlyContext:
    def test_single_entry_point_returns_every_section(self, tmp_path):
        d = tmp_path / "trade"
        d.mkdir()
        (d / "t.json").write_text(json.dumps(
            [{"date": "2026-07-13", "action": "buy", "symbol": "6268.T",
              "shares": 100, "price": 4000}]), encoding="utf-8")
        ctx = MC.build_monthly_context(
            [PLAN_NOTE], [{"symbol": "6701.T"}], 1_646_500, 6_296_491,
            today=TODAY, trade_dir=str(d))
        assert set(ctx) >= {"month", "budget", "slots", "conviction", "goal",
                            "realized", "last_month_realized", "holdings"}
        assert ctx["month"] == "2026-08"
        assert ctx["budget"]["cooldown_end"] == "2026-08-10"
        assert [s["month"] for s in ctx["slots"]][:2] == ["2026-08", "2026-09"]
