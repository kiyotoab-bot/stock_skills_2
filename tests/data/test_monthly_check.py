"""Tests for src/data/monthly_check.py (KIK-738).

月次チェックは「今月の1回をどう使うか」を扱う枠。自然文のノートから
予定と認定状況を拾うため、**緩く拾いすぎて誤検出する**方向の失敗が起きやすい。
実装中に実際に3回踏んだので、その3つを回帰テストとして固定する。
"""

import copy
import datetime
import json

import pytest
from unittest.mock import patch

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

    # 実データに存在する「行頭が日付の散文」。計画行と誤認すると売却済み銘柄が
    # 「今月の投入枠 確定」として出る（KIK-739 のレビューで実証された）。
    # 旧テストは assert 無しの dead code で、docstring が主張する誤検出を
    # 1件も捕まえていなかった。
    @pytest.mark.parametrize("prose", [
        "  2026-09-01 に 8725.T を買った（実行済み・計画ではない）",
        "  2026-09-03 の 8725.T を、月次上限のカウントから除外する。",
        "  2026-09-05 は 8725.T の決算日 100株 保有",
        "  2026-09-07 から 8725.T の監視を始める ¥1,000,000",
        "  補足として 2026-09-01 の 8725.T 100株 は対象外",
    ])
    def test_prose_is_not_a_plan_row(self, prose):
        note = copy.deepcopy(PLAN_NOTE)
        note["content"] += "\n" + prose + "\n"
        slots = {s["month"]: s for s in MC.planned_slots([note], TODAY)}
        assert "8725.T" not in slots["2026-09"]["symbols"], prose
        # 本物の計画行は残っていること（散文除外で巻き添えにしない）
        assert slots["2026-09"]["symbols"] == ["9104.T"]

    def test_plan_row_needs_a_plan_like_cell(self):
        """年月＋銘柄だけの行は計画表とみなさない（株数・金額・tier が要る）."""
        assert MC.plan_rows("  2026-09  9104.T") == []
        assert MC.plan_rows("  2026-09  9104.T 200株")
        assert MC.plan_rows("  2026-09  9104.T ¥1,237,200")
        assert MC.plan_rows("  2026-09  非Industrials枠 ― ¥1,100,000 conviction")

    def test_line_anchor_is_required(self):
        """行中の日付は拾わない。`.search` に緩めると散文が入り込む."""
        assert MC.plan_rows("参考: 2026-09 9104.T 200株 を検討") == []

    def test_multiline_flag_is_required(self):
        """MULTILINE を外すと本文全体に対して1行目しか見なくなる."""
        rows = MC.plan_rows("見出し\n  2026-09  9104.T 200株\n  2026-10  6501.T 100株")
        assert [m for m, _ in rows] == ["2026-09", "2026-10"]

    def test_no_plan_note_returns_empty_slots(self):
        slots = MC.planned_slots([], TODAY)
        assert len(slots) == 4
        assert all(s["status"] == "記載なし" for s in slots)


class TestLatestPlanNote:
    """どのノートを計画表とみなすか。3条件とも固定する (KIK-739)."""

    def test_picks_the_newest(self):
        n = MC.latest_plan_note([OLD_PLAN_NOTE, PLAN_NOTE])
        assert n["id"] == "note_plan"

    def test_non_target_notes_are_ignored(self):
        n = copy.deepcopy(PLAN_NOTE)
        n["type"] = "observation"
        assert MC.latest_plan_note([n]) is None

    def test_needs_two_distinct_months(self):
        """1行だけの散文ノートを計画表と誤認しない."""
        n = copy.deepcopy(PLAN_NOTE)
        n["content"] = "【発注指示書】\n  2026-09  9104.T 200株 ¥1,237,200\n"
        assert MC.latest_plan_note([n]) is None

    def test_keyword_alone_does_not_qualify(self):
        """『投入計画』の語を含むだけの散文ノートを選ばない（実データで誤選定した）."""
        prose = {"id": "n", "type": "target", "symbol": "", "timestamp": "2026-08-09",
                 "content": ("【訂正: 冷却期間】投入計画について\n"
                             "  2026-08-06 の target に「起点を 6268.T 売却に戻す」と書いた\n"
                             "  2026-07-30 の 6268.T 売却 100株 は起点にしない\n")}
        assert MC.latest_plan_note([prose, PLAN_NOTE])["id"] == "note_plan"

    def test_falls_back_to_date_without_timestamp(self):
        a = copy.deepcopy(PLAN_NOTE); a.pop("timestamp"); a["date"] = "2026-08-09"
        a["id"] = "newer"
        assert MC.latest_plan_note([PLAN_NOTE, a])["id"] == "newer"

    def test_no_candidates(self):
        assert MC.latest_plan_note([]) is None


class TestConvictionStatus:
    """判定は concentration.classify_conviction に委譲する (KIK-739)."""

    def test_delegates_and_reports_override(self):
        """conviction_override は『認定済み』ではなくユーザーによる免除."""
        with patch("src.data.concentration.classify_conviction",
                   return_value={"tier": "conviction_override",
                                 "criteria": {"CV1": True, "CV2": True, "CV3": False},
                                 "reasons": ["ユーザー判断"]}) as m:
            r = MC.conviction_status("7453.T", [], {"7453.T": {"stop": None}})
        m.assert_called_once()
        assert r["tier"] == "conviction_override"
        assert r["qualified"] is True and r["exempt"] is True

    def test_conviction_is_qualified_not_exempt(self):
        with patch("src.data.concentration.classify_conviction",
                   return_value={"tier": "conviction",
                                 "criteria": {"CV1": True, "CV2": True, "CV3": True}}):
            r = MC.conviction_status("7751.T", [])
        assert r["qualified"] is True and r["exempt"] is False and r["met"] == 3

    @pytest.mark.parametrize("criteria,met", [
        ({"CV1": True, "CV2": False, "CV3": False}, 1),
        ({"CV1": True, "CV2": True, "CV3": False}, 2),
        ({"CV1": False, "CV2": False, "CV3": False}, 0),
    ])
    def test_partial_is_normal(self, criteria, met):
        """3つ揃って初めて conviction。部分充足で緩めない."""
        with patch("src.data.concentration.classify_conviction",
                   return_value={"tier": "normal", "criteria": criteria}):
            r = MC.conviction_status("X", [])
        assert r["met"] == met and r["qualified"] is False and r["tier"] == "normal"

    def test_evidence_is_collected_but_not_used_for_judgement(self):
        """本文の CV 記述は根拠として添えるだけ。判定には使わない."""
        note = {"symbol": "X", "content": "CV1 一次情報検証済 / CV2 テーゼ文書化済"}
        with patch("src.data.concentration.classify_conviction",
                   return_value={"tier": "normal",
                                 "criteria": {"CV1": False, "CV2": False, "CV3": False}}):
            r = MC.conviction_status("X", [note])
        assert r["met"] == 0                      # 本文に CV1 とあっても met にしない
        assert r["checks"]["CV1"]["evidence"]     # 根拠は残す

    def test_negation_wording_no_longer_matters(self):
        """否定語ホワイトリスト（未充足/未取得/未整備…）から漏れて 3/3 に戻る穴を塞いだ."""
        note = {"symbol": "X", "content": "conviction 認定（CV1/CV2/CV3）が未取得"}
        with patch("src.data.concentration.classify_conviction",
                   return_value={"tier": "normal",
                                 "criteria": {"CV1": False, "CV2": False, "CV3": False}}):
            r = MC.conviction_status("X", [note])
        assert r["met"] == 0 and r["qualified"] is False


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

    def test_no_buys_at_all_states_the_reason(self):
        """『買えません（理由なし）』にしない。月次上限でマスクされない入力で見る."""
        b = MC.trade_budget([{"date": "2026-07-01", "action": "sell", "symbol": "X"}],
                            TODAY)
        assert b["monthly_used"] == 0 and b["monthly_remaining"] == 1
        assert b["last_buy"] is None and b["cooldown_days_left"] is None
        assert b["can_buy_now"] is False
        assert any("買付履歴なし" in x for x in b["blockers"])

    def test_excluded_trades_are_kept_and_flagged(self):
        b = MC.trade_budget(self.TRADES + [{"date": "2026-08-04", "action": "sell",
                                            "symbol": "Y"}],
                            TODAY, excluded_dates={"2026-08-04"})
        assert b["monthly_used"] == 0 and b["excluded_count"] == 1
        assert len(b["this_month_trades"]) == 1
        assert b["this_month_trades"][0]["excluded"] is True

    # --- KIK-763: ストップ執行は月次上限の枠外（2026-08-17 ユーザー判断） ---

    def test_limit_exempt_trade_does_not_consume_the_monthly_limit(self):
        """ストップ抵触の売却は枠を食わない。excluded_dates を渡さなくても効く."""
        trades = self.TRADES + [{"date": "2026-08-05", "action": "sell",
                                 "symbol": "6701.T", "limit_exempt": True,
                                 "exempt_reason": "stop-loss 4609 triggered"}]
        b = MC.trade_budget(trades, TODAY)
        assert b["monthly_used"] == 0 and b["monthly_remaining"] == 1
        assert not any("月次上限" in x for x in b["blockers"])

    def test_limit_exempt_trade_is_kept_and_flagged(self):
        """枠から外しても取引の事実は消さない（excluded_dates と同じ扱い）."""
        trades = self.TRADES + [{"date": "2026-08-05", "action": "sell",
                                 "symbol": "6701.T", "limit_exempt": True}]
        b = MC.trade_budget(trades, TODAY)
        assert b["excluded_count"] == 1
        assert len(b["this_month_trades"]) == 1
        assert b["this_month_trades"][0]["excluded"] is True

    def test_ordinary_sell_still_consumes_the_monthly_limit(self):
        """免除は明示したときだけ。既定で枠が緩む方向には壊さない."""
        trades = self.TRADES + [{"date": "2026-08-05", "action": "sell", "symbol": "Y"}]
        b = MC.trade_budget(trades, TODAY)
        assert b["monthly_used"] == 1 and b["monthly_remaining"] == 0

    def test_limit_exempt_buy_does_not_become_the_cooldown_anchor(self):
        """枠外にした買付を冷却期間の起点にしない（判定を1か所に揃える）."""
        trades = self.TRADES + [{"date": "2026-08-07", "action": "buy",
                                 "symbol": "Z", "limit_exempt": True}]
        b = MC.trade_budget(trades, TODAY)
        assert b["last_buy"] == "2026-07-13"


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
        assert r["trade_count"] == 3 and r["realized_pnl"] == 50
        assert r["buys"] == 1 and r["sells"] == 2

    def test_with_pnl_is_compared_against_sells_not_all_trades(self):
        """買付を含む trade_count と比べると常に足りなく見えて誤読される."""
        r = MC.realized_pnl(self.TRADES, "2026-08")
        assert r["sells_with_pnl"] == 2 and r["sells"] == 2
        assert r["sells_missing_pnl"] == 0

    def test_zero_pnl_is_not_dropped(self):
        """`a or b` チェーンだと損益0の手仕舞いが偽として次のキーに落ちる."""
        r = MC.realized_pnl([{"date": "2026-08-01", "action": "sell",
                              "realized_pnl": 0}], "2026-08")
        assert r["sells_with_pnl"] == 1 and r["realized_pnl"] == 0.0

    @pytest.mark.parametrize("raw,expected", [
        ("12,000", 12000.0), ("¥8,000", 8000.0), ("+500", 500.0), (-114000, -114000.0),
    ])
    def test_hand_written_numbers_are_parsed(self, raw, expected):
        r = MC.realized_pnl([{"date": "2026-08-01", "action": "sell",
                              "realized_pnl": raw}], "2026-08")
        assert r["realized_pnl"] == expected

    def test_unparsable_pnl_is_counted_not_silently_dropped(self):
        r = MC.realized_pnl([{"date": "2026-08-01", "action": "sell",
                              "realized_pnl": "n/a"}], "2026-08")
        assert r["unparsed_pnl"] == 1 and r["realized_pnl"] == 0.0

    def test_limit_exempt_pnl_is_counted_normally(self):
        """KIK-763: 枠から外れても損益は実在する。excluded_pnl に回さない.

        ここを excluded_dates と同じ扱いにすると、ストップ執行の損益が
        目標 ¥10,000,000 への進捗から消える。
        """
        r = MC.realized_pnl([{"date": "2026-08-05", "action": "sell",
                              "realized_pnl": 71714, "limit_exempt": True}], "2026-08")
        assert r["realized_pnl"] == 71714.0
        assert r["excluded_pnl"] == 0.0 and r["excluded_count"] == 0

    def test_excluded_dates_are_separated_not_erased(self):
        """枠のカウントから外すだけで、損益は実際に発生している (KIK-739)."""
        r = MC.realized_pnl(self.TRADES, "2026-08", excluded_dates={"2026-08-04"})
        assert r["realized_pnl"] == 0.0
        assert r["excluded_pnl"] == 50.0 and r["excluded_count"] == 2
        assert r["trade_count"] == 3          # 取引自体は消さない


class TestGoalDeadlineBoundaries:
    """期限当日・超過で落ちていた (KIK-739)."""

    @pytest.mark.parametrize("deadline", ["2026-08-08", "2026-01-01", "2020-01-01"])
    def test_expired_returns_none_not_overflow(self, deadline):
        g = MC.goal_progress(1_646_500, 6_296_491, 10_000_000, deadline, TODAY)
        assert g["expired"] is True
        assert g["required_cagr_as_is"] is None
        assert g["required_cagr_fully_invested"] is None

    def test_one_day_left_is_finite(self):
        g = MC.goal_progress(1_646_500, 6_296_491, 10_000_000, "2026-08-09", TODAY)
        assert g["expired"] is False
        assert g["required_cagr_as_is"] is not None

    def test_unparsable_deadline_reports_error(self):
        g = MC.goal_progress(1_646_500, 6_296_491, 10_000_000, "not-a-date", TODAY)
        assert "error" in g

    def test_goal_defaults_come_from_config(self):
        g = MC.goal_progress(1_646_500, 6_296_491, today=TODAY)
        assert g["target"] == 10_000_000 and g["deadline"] == "2031-04-30"
        assert g["goal_source"] == "config/allocation.yaml"

    def test_string_inputs_do_not_crash(self):
        g = MC.goal_progress("1646500", "6296491", today=TODAY)
        assert g["total"] == 7_942_991


class TestTierRules:
    """規模ティアで冷却期間を自動的に緩めない (KIK-739)."""

    def test_operative_stays_conservative_at_the_boundary(self):
        r = MC.tier_rules(50_592)
        assert r["tier_by_size"] == "medium"
        assert r["operative_tier"] == "small"
        assert r["cooldown_weeks"] == 4          # 2週に縮めない
        assert r["near_boundary"] is True
        assert "medium" in r["tier_mismatch"]

    def test_no_mismatch_below_the_boundary(self):
        r = MC.tier_rules(40_000)
        assert r["tier_by_size"] == "small" and r["tier_mismatch"] is None

    def test_source_states_the_yaml_is_unreadable(self):
        """sector_matrix.yaml は YAML として壊れているので SSoT にできない."""
        assert "sector_matrix.yaml" in MC.tier_rules(40_000)["source"]


class TestLoadTrades:
    """存在理由がキー名の揺れ吸収なので、揺れを全部踏む (KIK-739)."""

    def _write(self, d, name, payload):
        (d / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_key_variants(self, tmp_path):
        self._write(tmp_path, "a.json", [{"trade_date": "2026-08-01",
                                          "trade_type": "BUY", "symbol": "X",
                                          "realized_pl": 100}])
        self._write(tmp_path, "b.json", {"date": "2026-08-02", "action": "sell",
                                         "symbol": "Y", "pnl": 0})
        out = {t["symbol"]: t for t in MC.load_trades(str(tmp_path))}
        assert out["X"]["date"] == "2026-08-01"
        assert out["X"]["action"] == "buy"          # .lower() が要る
        assert out["X"]["realized_pnl"] == 100
        assert out["Y"]["realized_pnl"] == 0        # or チェーンだと消える

    def test_broken_json_does_not_stop_the_rest(self, tmp_path):
        (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
        self._write(tmp_path, "ok.json", [{"date": "2026-08-01", "action": "buy",
                                           "symbol": "Z"}])
        assert [t["symbol"] for t in MC.load_trades(str(tmp_path))] == ["Z"]

    def test_records_without_date_or_action_are_dropped(self, tmp_path):
        self._write(tmp_path, "a.json", [{"action": "buy"}, {"date": "2026-08-01"},
                                         {"date": "", "action": "buy"}])
        assert MC.load_trades(str(tmp_path)) == []

    def test_missing_directory(self, tmp_path):
        assert MC.load_trades(str(tmp_path / "nope")) == []

    def test_limit_exempt_survives_normalization(self, tmp_path):
        """KIK-763: load_trades はホワイトリスト。載せ忘れると黙って消える.

        save_trade に足しただけでは枠の判定まで届かないので、ここで固定する。
        """
        self._write(tmp_path, "a.json", [
            {"date": "2026-08-05", "action": "sell", "symbol": "6701.T",
             "limit_exempt": True, "exempt_reason": "stop-loss 4609 triggered"},
            {"date": "2026-08-06", "action": "sell", "symbol": "Y"},
        ])
        out = {t["symbol"]: t for t in MC.load_trades(str(tmp_path))}
        assert out["6701.T"]["limit_exempt"] is True
        assert out["6701.T"]["exempt_reason"] == "stop-loss 4609 triggered"
        assert out["Y"]["limit_exempt"] is False     # 既定で枠を食う側に倒す


class TestAddMonths:
    @pytest.mark.parametrize("n,expected", [
        (0, "2026-08"), (1, "2026-09"), (4, "2026-12"), (5, "2027-01"), (-1, "2026-07"),
    ])
    def test_rolls_over_the_year(self, n, expected):
        assert MC.month_key(MC.add_months(TODAY, n)) == expected


class TestBuildMonthlyContext:
    def _trade_dir(self, tmp_path):
        d = tmp_path / "trade"
        d.mkdir()
        (d / "t.json").write_text(json.dumps(
            [{"date": "2026-07-13", "action": "buy", "symbol": "6268.T",
              "shares": 100, "price": 4000},
             {"date": "2026-07-20", "action": "sell", "symbol": "6268.T",
              "realized_pnl": -5000},
             {"date": "2026-08-02", "action": "sell", "symbol": "6436.T",
              "realized_pnl": 7000}]), encoding="utf-8")
        return d

    def test_single_entry_point_returns_every_section(self, tmp_path):
        ctx = MC.build_monthly_context(
            [PLAN_NOTE], [{"symbol": "6701.T"}], 1_646_500, 6_296_491,
            today=TODAY, trade_dir=str(self._trade_dir(tmp_path)))
        assert set(ctx) >= {"month", "tier_rules", "budget", "slots", "conviction",
                            "goal", "realized", "last_month_realized", "holdings"}
        assert ctx["month"] == "2026-08"
        assert ctx["budget"]["cooldown_end"] == "2026-08-10"

    def test_slots_feed_conviction(self, tmp_path):
        """組み立ての正しさこそこの関数の存在理由。キーの有無だけでは足りない."""
        ctx = MC.build_monthly_context(
            [PLAN_NOTE], [], 1_646_500, 6_296_491,
            today=TODAY, trade_dir=str(self._trade_dir(tmp_path)))
        assert [c["symbol"] for c in ctx["conviction"]] == ["7751.T", "9104.T", "6501.T"]

    def test_this_month_and_last_month_are_not_swapped(self, tmp_path):
        ctx = MC.build_monthly_context(
            [PLAN_NOTE], [], 1_646_500, 6_296_491,
            today=TODAY, trade_dir=str(self._trade_dir(tmp_path)))
        assert ctx["realized"]["realized_pnl"] == 7000        # 8月
        assert ctx["last_month_realized"]["realized_pnl"] == -5000   # 7月

    def test_beyond_horizon_plan_months_are_kept(self, tmp_path):
        """12月のアイシンは認定が要るのに horizon=3 だと8月時点で消えていた."""
        note = copy.deepcopy(PLAN_NOTE)
        note["content"] += "  2026-12     7259.T アイシン  +200株 ¥451,600  conviction\n"
        ctx = MC.build_monthly_context(
            [note], [], 1_646_500, 6_296_491,
            today=TODAY, trade_dir=str(self._trade_dir(tmp_path)))
        dec = [s for s in ctx["slots"] if s["month"] == "2026-12"]
        assert dec and dec[0]["symbols"] == ["7259.T"] and dec[0]["beyond_horizon"]
        assert "7259.T" in [c["symbol"] for c in ctx["conviction"]]

    def test_excluded_dates_reach_both_budget_and_realized(self, tmp_path):
        """片方にしか渡さないと『今月0回』と『今月の実現損益7件』が並ぶ."""
        ctx = MC.build_monthly_context(
            [PLAN_NOTE], [], 1_646_500, 6_296_491, today=TODAY,
            trade_dir=str(self._trade_dir(tmp_path)),
            excluded_dates={"2026-08-02"})
        assert ctx["budget"]["monthly_used"] == 0
        assert ctx["realized"]["realized_pnl"] == 0.0
        assert ctx["realized"]["excluded_pnl"] == 7000


class TestLoadTierRules:
    """冷却期間・月次上限の出典は sector_matrix.yaml (KIK-740)."""

    def test_reads_the_yaml(self):
        """KIK-739 は『この yaml は壊れていて読めない』と記録したが誤りだった.

        ワークツリー（HEAD から切る）で検証したため、2026-08-06 の冷却期間
        改訂を含む未コミットの修正版を見ていなかった。
        """
        loaded = MC.load_tier_rules()
        assert loaded["source"] == "sector_matrix.yaml"
        assert loaded["rules"]["small"] == {"cooldown_weeks": 4, "monthly_limit": 1}
        assert loaded["rules"]["medium"]["cooldown_weeks"] == 2
        assert loaded["rules"]["large"]["monthly_limit"] == 4

    def test_falls_back_when_unreadable(self):
        with patch("builtins.open", side_effect=OSError("gone")):
            loaded = MC.load_tier_rules()
        assert loaded["rules"] == MC._TIER_FALLBACK
        assert "fallback" in loaded["source"]

    def test_tier_rules_reports_the_yaml_as_source(self):
        assert MC.tier_rules(40_000)["source"] == "sector_matrix.yaml"

    def test_yaml_values_still_do_not_relax_the_cooldown(self):
        """yaml から読めても、規模で自動的に緩めない判断は変えない."""
        r = MC.tier_rules(50_592)
        assert r["tier_by_size"] == "medium" and r["cooldown_weeks"] == 4
