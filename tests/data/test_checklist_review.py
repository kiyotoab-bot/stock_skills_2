"""Tests for the mechanical checklist reviewer (KIK-734).

外部LLM（GPT / Gemini / Grok）が3つとも使えず、レビューが「自分の判断を自分で
検証する」形にしかならなかったため、主観を挟まず判定できる項目を自動化した。
各テストは 2026-08 に実際に起きた失敗を再現している。
"""

import datetime

import pytest

from src.data.checklist_review import (
    DQ3_PER_FLOOR,
    FAIL,
    NA,
    PASS,
    WARN,
    check_cooldown,
    check_data_quality,
    check_followthrough,
    check_order,
    check_pf_tier,
    check_stop_breach,
    check_stop_sigma,
    summarize,
)

TODAY = datetime.date(2026, 8, 6)


def _by_id(results):
    return {r["id"]: r for r in results}


class TestDataQuality:
    def test_amano_suspect_fails(self):
        """6436.T アマノ: 予想配当250円（会社予想180円）で推奨に載った件。"""
        got = _by_id(check_data_quality({"6436.T": {
            "forecast_source": "jquants", "forecast_suspect": True,
        }}))
        assert got["DQ2"]["status"] == FAIL
        assert "6436.T" in got["DQ2"]["detail"]

    def test_clean_symbol_passes(self):
        got = _by_id(check_data_quality({"7751.T": {
            "forecast_source": "jquants", "forecast_suspect": False,
            "per_forward_company": 11.4, "dividend_yield_company": 0.0353,
        }}))
        assert got["DQ1"]["status"] == PASS
        assert got["DQ2"]["status"] == PASS
        assert got["DQ3"]["status"] == PASS

    def test_yfinance_fallback_warns(self):
        got = _by_id(check_data_quality({"4568.T": {"forecast_source": "yfinance"}}))
        assert got["DQ1"]["status"] == WARN

    def test_nippon_steel_extreme_per_warns(self):
        """5401.T: yfinance が予想PER 1.2 を返していた件。"""
        got = _by_id(check_data_quality({"5401.T": {
            "forecast_source": "jquants", "forecast_suspect": False, "forward_per": 1.2,
        }}))
        assert got["DQ3"]["status"] == WARN
        assert "5401.T" in got["DQ3"]["detail"]

    def test_extreme_yield_warns(self):
        got = _by_id(check_data_quality({"6436.T": {
            "forecast_source": "jquants", "forecast_suspect": False,
            "dividend_yield": 0.0644,
        }}))
        assert got["DQ3"]["status"] == WARN

    def test_us_symbol_is_na(self):
        got = _by_id(check_data_quality({"AAPL": {"forecast_source": None}}))
        assert got["DQ1"]["status"] == NA

    def test_nec_per_6_4_warns(self):
        """DQ3 の incident そのもの。当初 PER<5 で実装したため 6.4 が素通りしていた。"""
        got = _by_id(check_data_quality({"6701.T": {
            "forecast_source": "jquants", "forecast_suspect": False, "forward_per": 6.4,
        }}))
        assert got["DQ3"]["status"] == WARN
        assert "6701.T" in got["DQ3"]["detail"]

    def test_per_at_floor_is_not_flagged(self):
        got = _by_id(check_data_quality({"8031.T": {
            "forecast_source": "jquants", "forecast_suspect": False,
            "per_forward_company": DQ3_PER_FLOOR,
        }}))
        assert got["DQ3"]["status"] == PASS


class TestMissingCompanyEps:
    """DQ7: forecast_source=='jquants' でも会社予想EPSが空なら PER は yfinance の値。

    6701.T 日本電気は IFRS/Non-GAAP 開示で決算短信の EPS 欄が空。配当だけ
    J-Quants から入るため DQ1 は PASS し、2026-08-07 の週次で会社PER 6.5 と
    表示した（実際は 21.5）。DQ1 も DQ3 も当時は発火しなかった。
    """

    def test_dividend_only_jquants_warns(self):
        got = _by_id(check_data_quality({"6701.T": {
            "forecast_source": "jquants", "forecast_suspect": False,
            "per_forward_company": None, "forecast_dps_company": 40.0,
            "forward_per": 6.5,
        }}))
        assert got["DQ1"]["status"] == PASS, "DQ1 だけでは捕まらないことの確認"
        assert got["DQ7"]["status"] == WARN
        assert "6701.T" in got["DQ7"]["detail"]

    def test_company_eps_present_passes(self):
        got = _by_id(check_data_quality({"8031.T": {
            "forecast_source": "jquants", "forecast_suspect": False,
            "per_forward_company": 14.7, "forward_per": 16.2,
        }}))
        assert got["DQ7"]["status"] == PASS

    def test_no_per_at_all_is_not_flagged(self):
        """PER が両方無いなら誤表示のしようがない。"""
        got = _by_id(check_data_quality({"1234.T": {
            "forecast_source": "jquants", "forecast_suspect": False,
        }}))
        assert got["DQ7"]["status"] == PASS

    def test_only_offending_symbols_listed(self):
        got = _by_id(check_data_quality({
            "6701.T": {"forecast_source": "jquants", "forward_per": 6.5},
            "8031.T": {"forecast_source": "jquants", "per_forward_company": 14.7,
                       "forward_per": 16.2},
        }))
        assert "6701.T" in got["DQ7"]["detail"]
        assert "8031.T" not in got["DQ7"]["detail"]


class TestPfTier:
    def test_actual_boundary_case_warns(self):
        """実際の状況: $49,925 で small/medium の境界すぐ下だった。"""
        got = _by_id(check_pf_tier(7_875_591, 157.75))
        assert got["RL1"]["status"] == WARN
        assert "small" in got["RL1"]["detail"]

    def test_clearly_inside_tier_passes(self):
        got = _by_id(check_pf_tier(15_000_000, 150.0))  # $100K
        assert got["RL1"]["status"] == PASS
        assert "medium" in got["RL1"]["detail"]

    def test_missing_fx_is_na(self):
        assert _by_id(check_pf_tier(7_875_591, 0))["RL1"]["status"] == NA


class TestStopSigma:
    def test_kamigumi_noise_zone_fails(self):
        """9364.T のストップが 0.64日σ しか離れていなかった件。"""
        got = _by_id(check_stop_sigma({"9364.T": 0.64, "6701.T": 3.80}))
        assert got["RL5"]["status"] == FAIL
        assert "9364.T" in got["RL5"]["detail"]

    def test_all_wide_passes(self):
        assert _by_id(check_stop_sigma({"A.T": 3.5, "B.T": 2.1}))["RL5"]["status"] == PASS

    def test_boundary_one_sigma_is_noise(self):
        assert _by_id(check_stop_sigma({"A.T": 1.0}))["RL5"]["status"] == FAIL
        assert _by_id(check_stop_sigma({"A.T": 1.01}))["RL5"]["status"] == PASS

    def test_empty_is_na(self):
        assert _by_id(check_stop_sigma({}))["RL5"]["status"] == NA


class TestStopBreach:
    """KIK-765: 逆指値を証券会社に置かない運用（2026-08-17 ユーザー判断）。

    ストップが注文ではなく判断になったので、日次チェックが報告して初めて機能する。
    報告し忘れを run_review 経由の記録で潰す。
    """

    STOPS = {
        "6701.T": {"stop": 4609.0, "closed": False},
        "8031.T": {"stop": 4536.0, "closed": False},
        "7453.T": {"stop": None, "closed": False},      # conviction_override
        "6758.T": {"stop": 3400.0, "closed": True},     # 手仕舞い済み
    }
    SIGMAS = {"6701.T": 3.03, "8031.T": 1.57}

    def test_breach_fails_and_says_what_to_do(self):
        prices = {"6701.T": 4600.0, "8031.T": 4796.0}
        got = _by_id(check_stop_breach(prices, self.STOPS, self.SIGMAS))["RL6"]
        assert got["status"] == FAIL
        assert "6701.T" in got["detail"] and "寄成" in got["detail"]

    def test_exactly_at_the_stop_is_a_breach(self):
        """終値ベース判定。ちょうど到達したら抵触として扱う."""
        got = _by_id(check_stop_breach({"6701.T": 4609.0}, self.STOPS, self.SIGMAS))["RL6"]
        assert got["status"] == FAIL

    def test_within_one_sigma_warns(self):
        """2026-08-17 の 6701.T: -3.70% / 日次σ3.03% = 1.22σ → まだ WARN ではない."""
        prices = {"6701.T": 4700.0}          # -1.94% / 3.03 = 0.64σ
        got = _by_id(check_stop_breach(prices, self.STOPS, self.SIGMAS))["RL6"]
        assert got["status"] == WARN

    def test_actual_2026_08_17_state_passes(self):
        prices = {"6701.T": 4786.0, "8031.T": 4796.0}
        got = _by_id(check_stop_breach(prices, self.STOPS, self.SIGMAS))["RL6"]
        assert got["status"] == PASS

    def test_all_holdings_are_listed_even_when_green(self):
        """全green でも表を出す。出さないと『見ていない』と区別がつかない."""
        prices = {"6701.T": 4786.0, "8031.T": 4796.0}
        detail = _by_id(check_stop_breach(prices, self.STOPS, self.SIGMAS))["RL6"]["detail"]
        assert "6701.T" in detail and "8031.T" in detail

    def test_exempt_symbol_is_named_not_dropped(self):
        """免除銘柄を黙って落とさない（落とすと設定漏れと見分けがつかない）."""
        prices = {"6701.T": 4786.0, "7453.T": 4345.0}
        detail = _by_id(check_stop_breach(prices, self.STOPS, self.SIGMAS))["RL6"]["detail"]
        assert "免除" in detail and "7453.T" in detail

    def test_closed_position_is_not_monitored(self):
        """手仕舞い済み（KIK-764）は監視対象外。旧ストップで抵触判定しない."""
        prices = {"6758.T": 3000.0}          # 旧stop 3400 を割っているが売却済み
        got = _by_id(check_stop_breach(prices, self.STOPS, self.SIGMAS))["RL6"]
        assert got["status"] == PASS
        assert "6758.T" not in got["detail"]

    def test_missing_sigma_still_detects_breach(self):
        """σが無くても抵触判定はできる。σは1σ警告にしか使わない."""
        got = _by_id(check_stop_breach({"6701.T": 4000.0}, self.STOPS, None))["RL6"]
        assert got["status"] == FAIL

    def test_no_holdings_is_na(self):
        assert _by_id(check_stop_breach({}, self.STOPS, self.SIGMAS))["RL6"]["status"] == NA


class TestStopBreachOnSkippedDays:
    """KIK-766: 前回チェック以降の全営業日を見る.

    最新終値だけを見ると「火曜に割って水曜に戻した」を取りこぼす。
    ストップは日々の終値に対する規則なので、間の日も判定対象。
    日次チェックを毎日回せるとは限らない以上、ここを塞がないと
    「回した日はたまたま戻っていた」で規則が空振りする。
    """

    STOPS = {"6701.T": {"stop": 4609.0, "closed": False},
             "7453.T": {"stop": None, "closed": False}}
    SIGMAS = {"6701.T": 3.03}
    HIST = {"6701.T": [("2026-08-17", 4786.0), ("2026-08-18", 4500.0),
                       ("2026-08-19", 4700.0)]}

    def test_breach_on_a_skipped_day_is_caught(self):
        got = _by_id(check_stop_breach({"6701.T": 4700.0}, self.STOPS, self.SIGMAS,
                                       histories=self.HIST, since="2026-08-17"))["RL6"]
        assert got["status"] == FAIL
        assert "2026-08-18" in got["detail"] and "見逃し" in got["detail"]

    def test_without_since_keeps_the_old_behaviour(self):
        """後方互換。histories/since を渡さなければ最新終値だけを見る."""
        got = _by_id(check_stop_breach({"6701.T": 4700.0}, self.STOPS,
                                       self.SIGMAS))["RL6"]
        assert got["status"] == WARN          # 4,700 は 0.64σ

    def test_bars_on_or_before_since_are_not_rechecked(self):
        """前回チェック済みの日を蒸し返さない（since より後だけ見る）."""
        hist = {"6701.T": [("2026-08-17", 4500.0), ("2026-08-18", 4700.0)]}
        got = _by_id(check_stop_breach({"6701.T": 4700.0}, self.STOPS, self.SIGMAS,
                                       histories=hist, since="2026-08-17"))["RL6"]
        assert got["status"] == WARN
        assert "見逃し" not in got["detail"]

    def test_multiple_skipped_breaches_report_the_worst(self):
        hist = {"6701.T": [("2026-08-18", 4550.0), ("2026-08-19", 4400.0),
                           ("2026-08-20", 4700.0)]}
        got = _by_id(check_stop_breach({"6701.T": 4700.0}, self.STOPS, self.SIGMAS,
                                       histories=hist, since="2026-08-17"))["RL6"]
        assert "4,400" in got["detail"] and "2日" in got["detail"]

    def test_current_breach_is_not_double_reported(self):
        """今日も抵触しているなら通常の抵触として出す。二重に言わない."""
        hist = {"6701.T": [("2026-08-18", 4500.0)]}
        got = _by_id(check_stop_breach({"6701.T": 4500.0}, self.STOPS, self.SIGMAS,
                                       histories=hist, since="2026-08-17"))["RL6"]
        assert got["status"] == FAIL
        assert "見逃し" not in got["detail"]

    def test_exempt_symbol_is_not_scanned(self):
        """免除銘柄は履歴を見ない（ストップが無いので抵触の概念がない）."""
        hist = {"7453.T": [("2026-08-18", 1.0)]}
        got = _by_id(check_stop_breach({"7453.T": 4345.0}, self.STOPS, self.SIGMAS,
                                       histories=hist, since="2026-08-17"))["RL6"]
        assert got["status"] == PASS and "免除" in got["detail"]

    def test_history_without_since_is_ignored(self):
        """since が無ければ走査しない。全期間を蒸し返すと毎日 FAIL になる."""
        got = _by_id(check_stop_breach({"6701.T": 4700.0}, self.STOPS, self.SIGMAS,
                                       histories=self.HIST))["RL6"]
        assert got["status"] == WARN


class TestFollowthrough:
    def test_the_aisin_incident(self):
        """7/28に『8/3に再評価』と書いて実行しなかった件。"""
        notes = [{
            "type": "target", "symbol": "7259.T",
            "trigger": "2026-08-03 に再評価", "expected_action": "指値の再設定可否を判断",
        }]
        got = _by_id(check_followthrough(notes, TODAY))
        assert got["FT1"]["status"] == WARN
        assert "7259.T" in got["FT1"]["detail"]

    def test_future_trigger_is_not_overdue(self):
        notes = [{"type": "target", "symbol": "X.T", "trigger": "2026-09-01 に発注"}]
        assert _by_id(check_followthrough(notes, TODAY))["FT1"]["status"] == PASS

    def test_non_target_notes_ignored(self):
        notes = [{"type": "lesson", "trigger": "2026-01-01"}]
        assert _by_id(check_followthrough(notes, TODAY))["FT1"]["status"] == PASS

    def test_notes_without_trigger_ignored(self):
        notes = [{"type": "target", "symbol": "X.T", "content": "2026-01-01 のメモ"}]
        assert _by_id(check_followthrough(notes, TODAY))["FT1"]["status"] == PASS

    def test_empty_is_pass(self):
        assert _by_id(check_followthrough([], TODAY))["FT1"]["status"] == PASS


class TestCooldown:
    def _write(self, tmp_path, records):
        import json
        for i, r in enumerate(records):
            (tmp_path / f"t{i}.json").write_text(
                json.dumps([r], ensure_ascii=False), encoding="utf-8")
        return str(tmp_path)

    def test_sell_does_not_reset_cooldown(self, tmp_path):
        """2026-08-06 の改訂の核心: 売却は冷却期間をリセットしない。"""
        d = self._write(tmp_path, [
            {"date": "2026-07-13", "action": "buy", "symbol": "6268.T"},
            {"date": "2026-08-04", "action": "sell", "symbol": "2768.T"},
        ])
        got = _by_id(check_cooldown(d, today=datetime.date(2026, 8, 10)))
        assert "2026-07-13" in got["PO1"]["detail"]
        assert "2026-08-10" in got["PO1"]["detail"]

    def test_monthly_cap_blocks(self, tmp_path):
        d = self._write(tmp_path, [
            {"date": "2026-07-13", "action": "buy", "symbol": "A.T"},
            {"date": "2026-08-04", "action": "sell", "symbol": "B.T"},
        ])
        got = _by_id(check_cooldown(d, today=datetime.date(2026, 8, 10)))
        assert got["PO1"]["status"] == FAIL  # 今月すでに1回売買している

    def test_excluded_dates_are_ignored(self, tmp_path):
        """誤発注日を除外できること（8/4 の7件を月次上限から外した運用）。"""
        d = self._write(tmp_path, [
            {"date": "2026-07-13", "action": "buy", "symbol": "A.T"},
            {"date": "2026-08-04", "action": "sell", "symbol": "B.T"},
        ])
        got = _by_id(check_cooldown(
            d, excluded_dates={"2026-08-04"}, today=datetime.date(2026, 8, 10)))
        assert got["PO1"]["status"] == PASS

    def test_limit_exempt_sell_does_not_block(self, tmp_path):
        """KIK-763: ストップ執行は月次上限に数えない。日付を渡さなくても効く.

        trade_budget と判定を揃えてある。片方だけ直すと同じレポートに
        「今月0回（budget）」と「今月1回（PO1）」が並ぶ。
        """
        d = self._write(tmp_path, [
            {"date": "2026-07-13", "action": "buy", "symbol": "A.T"},
            {"date": "2026-08-04", "action": "sell", "symbol": "B.T",
             "limit_exempt": True, "exempt_reason": "stop-loss triggered"},
        ])
        got = _by_id(check_cooldown(d, today=datetime.date(2026, 8, 10)))
        assert got["PO1"]["status"] == PASS
        assert "今月の売買 0回" in got["PO1"]["detail"]

    def test_cooldown_not_elapsed_fails(self, tmp_path):
        d = self._write(tmp_path, [{"date": "2026-08-01", "action": "buy", "symbol": "A.T"}])
        got = _by_id(check_cooldown(d, today=datetime.date(2026, 8, 10)))
        assert got["PO1"]["status"] == FAIL
        assert "あと" in got["PO1"]["detail"]

    def test_no_buy_history_warns(self, tmp_path):
        d = self._write(tmp_path, [{"date": "2026-08-01", "action": "sell", "symbol": "A.T"}])
        assert _by_id(check_cooldown(d, today=TODAY))["PO1"]["status"] == WARN

    def test_trade_type_key_counts_as_buy(self, tmp_path):
        """``save_trade()`` は ``action`` ではなく ``trade_type`` で書く。

        2026-08-10 のキヤノン買付がこの形式で、``action`` だけを見ていた
        ため買付として数えられず、冷却期間の起点が 2026-07-13 のまま
        ずれていた（2026-08-16 発覚）。
        """
        d = self._write(tmp_path, [
            {"date": "2026-07-13", "action": "buy", "symbol": "A.T"},
            {"date": "2026-08-10", "trade_type": "buy", "symbol": "7751.T"},
        ])
        got = _by_id(check_cooldown(d, today=datetime.date(2026, 9, 5)))
        assert "2026-08-10" in got["PO1"]["detail"]   # 起点は直近の買付
        assert "2026-09-07" in got["PO1"]["detail"]   # +4週
        assert got["PO1"]["status"] == FAIL           # 冷却期間中

    def test_trade_type_buy_not_double_counted(self, tmp_path):
        """``action`` と ``trade_type`` を両方持つレコードでも1件に数える。"""
        d = self._write(tmp_path, [
            {"date": "2026-08-03", "action": "buy", "trade_type": "buy", "symbol": "A.T"},
        ])
        got = _by_id(check_cooldown(d, today=datetime.date(2026, 8, 31)))
        assert "今月の売買 1回" in got["PO1"]["detail"]


class TestCheckOrder:
    canon = {
        "price": 4527.0, "forecast_source": "jquants",
        "forecast_suspect": False, "per_forward_company": 11.4,
    }

    def test_canon_current_state(self):
        """8/10 発注予定のキヤノン。PO3 だけ横ばいで WARN になるのが実態。"""
        got = _by_id(check_order(
            "7751.T", self.canon,
            revision={"revision_in_fy": -0.3},
            margin={"available": True, "margin_ratio": 11.47},
            price_cap=4700,
        ))
        assert got["PO2"]["status"] == PASS
        assert got["PO3"]["status"] == WARN      # -0.3% は据え置き
        assert got["PO4"]["status"] == PASS
        assert got["PO7"]["status"] == PASS

    def test_price_cap_breach_fails(self):
        info = {**self.canon, "price": 4800.0}
        got = _by_id(check_order("7751.T", info, price_cap=4700))
        assert got["PO4"]["status"] == FAIL

    def test_downward_revision_fails(self):
        got = _by_id(check_order("X.T", self.canon, revision={"revision_in_fy": -12.0}))
        assert got["PO3"]["status"] == FAIL

    def test_upward_revision_passes(self):
        got = _by_id(check_order("9104.T", self.canon, revision={"revision_in_fy": 41.2}))
        assert got["PO3"]["status"] == PASS

    def test_mitsui_margin_fails(self):
        """8031.T の 38.5倍。"""
        got = _by_id(check_order(
            "8031.T", self.canon, margin={"available": True, "margin_ratio": 38.5}))
        assert got["PO7"]["status"] == FAIL

    def test_missing_margin_warns(self):
        got = _by_id(check_order("X.T", self.canon, margin=None))
        assert got["PO7"]["status"] == WARN

    def test_suspect_warns(self):
        info = {**self.canon, "forecast_suspect": True}
        assert _by_id(check_order("X.T", info))["PO2"]["status"] == WARN

    def test_missing_revision_is_na(self):
        got = _by_id(check_order("6701.T", self.canon, revision={"revision_in_fy": None}))
        assert got["PO3"]["status"] == NA


class TestSummarize:
    def test_fail_dominates(self):
        s = summarize([{"id": "a", "status": PASS, "detail": ""},
                       {"id": "b", "status": WARN, "detail": ""},
                       {"id": "c", "status": FAIL, "detail": ""}])
        assert s["verdict"] == FAIL
        assert s["results"][0]["status"] == FAIL   # 重い順に並ぶ

    def test_warn_when_no_fail(self):
        s = summarize([{"id": "a", "status": PASS, "detail": ""},
                       {"id": "b", "status": WARN, "detail": ""}])
        assert s["verdict"] == WARN

    def test_all_pass(self):
        s = summarize([{"id": "a", "status": PASS, "detail": ""}])
        assert s["verdict"] == PASS

    def test_caveat_is_always_present(self):
        """PASS を『全項目確認済み』と誤読させないこと。"""
        s = summarize([{"id": "a", "status": PASS, "detail": ""}])
        assert "全項目確認済み" in s["caveat"]

    def test_na_does_not_downgrade(self):
        s = summarize([{"id": "a", "status": PASS, "detail": ""},
                       {"id": "b", "status": NA, "detail": ""}])
        assert s["verdict"] == PASS


class TestReviewCoverage:
    """auto_review が一度も発火しなかった件（2026-08-03〜06 に判断6件、レビュー0件）。"""

    def test_unreviewed_decisions_are_detected(self):
        from src.data.checklist_review import check_review_coverage
        notes = [
            {"type": "target", "symbol": "7751.T", "date": "2026-08-05"},
            {"type": "exit-rule", "symbol": "9364.T", "date": "2026-08-03"},
            {"type": "lesson", "symbol": None, "date": "2026-08-04"},  # 対象外
        ]
        got = _by_id(check_review_coverage(notes, "2026-04-26", TODAY))
        assert got["REVIEW"]["status"] == WARN
        assert "2件" in got["REVIEW"]["detail"]
        assert "102日前" in got["REVIEW"]["detail"]

    def test_many_unreviewed_is_fail(self):
        from src.data.checklist_review import check_review_coverage
        notes = [{"type": "target", "symbol": f"X{i}.T", "date": "2026-08-05"}
                 for i in range(6)]
        assert _by_id(check_review_coverage(notes, "2026-04-26", TODAY))["REVIEW"]["status"] == FAIL

    def test_reviewed_decisions_pass(self):
        from src.data.checklist_review import check_review_coverage
        notes = [{"type": "target", "symbol": "A.T", "date": "2026-08-01"}]
        assert _by_id(check_review_coverage(notes, "2026-08-05", TODAY))["REVIEW"]["status"] == PASS

    def test_no_review_record_still_reports(self):
        from src.data.checklist_review import check_review_coverage
        notes = [{"type": "target", "symbol": "A.T", "date": "2026-08-01"}]
        got = _by_id(check_review_coverage(notes, None, TODAY))
        assert got["REVIEW"]["status"] == WARN
        assert "記録なし" in got["REVIEW"]["detail"]

    def test_only_decision_note_types_count(self):
        from src.data.checklist_review import check_review_coverage
        notes = [{"type": "observation", "date": "2026-08-05"},
                 {"type": "thesis", "date": "2026-08-05"}]
        assert _by_id(check_review_coverage(notes, "2026-04-26", TODAY))["REVIEW"]["status"] == PASS

    def test_latest_review_date_reads_filenames(self, tmp_path):
        from src.data.checklist_review import latest_review_date
        (tmp_path / "pf_plan_20260426.json").write_text("{}", encoding="utf-8")
        (tmp_path / "order_20260806.json").write_text("{}", encoding="utf-8")
        assert latest_review_date(str(tmp_path)) == "2026-08-06"

    def test_latest_review_date_missing_dir(self, tmp_path):
        from src.data.checklist_review import latest_review_date
        assert latest_review_date(str(tmp_path / "nope")) is None


class TestRunReview:
    """単一の入口としての段階的縮退（1 → 2 → 3 を必ず通す）。"""

    def test_saves_even_when_llm_unavailable(self, tmp_path, monkeypatch):
        """3の核心: 独立レビューができなくても**記録は必ず残る**。"""
        from src.data import checklist_review as CR
        monkeypatch.setattr(CR, "llm_availability", lambda: {"grok": "403"})
        got = CR.run_review([{"id": "X", "status": PASS, "detail": ""}],
                            reviews_dir=str(tmp_path))
        assert got["level"] == CR.LEVEL_MECHANICAL
        assert got["saved_to"] is not None
        assert (tmp_path / "checklist_" ).with_suffix("") or list(tmp_path.glob("*.json"))

    def test_level_upgrades_when_llm_works(self, tmp_path, monkeypatch):
        from src.data import checklist_review as CR
        monkeypatch.setattr(CR, "independent_review", lambda ctx, **k: {
            "independent": True, "availability": {"gpt": "利用可能"},
            "reviews": {"gpt": "問題なし"}, "note": "",
        })
        got = CR.run_review([{"id": "X", "status": PASS, "detail": ""}],
                            llm_context="レビューして", reviews_dir=str(tmp_path))
        assert got["level"] == CR.LEVEL_INDEPENDENT
        assert got["independent_review"]["reviews"]["gpt"] == "問題なし"

    def test_caveat_warns_about_self_review(self, tmp_path, monkeypatch):
        """独立性が無いことを PASS でも必ず添える。"""
        from src.data import checklist_review as CR
        monkeypatch.setattr(CR, "llm_availability", lambda: {})
        got = CR.run_review([{"id": "X", "status": PASS, "detail": ""}],
                            reviews_dir=str(tmp_path))
        assert "自分の判断を自分で見ている" in got["caveat"]

    def test_independent_review_has_no_self_review_caveat(self, tmp_path, monkeypatch):
        from src.data import checklist_review as CR
        monkeypatch.setattr(CR, "independent_review", lambda ctx, **k: {
            "independent": True, "availability": {}, "reviews": {}, "note": "",
        })
        got = CR.run_review([{"id": "X", "status": PASS, "detail": ""}],
                            llm_context="x", reviews_dir=str(tmp_path))
        assert "自分の判断を自分で見ている" not in got["caveat"]

    def test_fail_still_saves(self, tmp_path, monkeypatch):
        """FAIL でも記録する。『失敗したから残さない』を起こさない。"""
        from src.data import checklist_review as CR
        monkeypatch.setattr(CR, "llm_availability", lambda: {})
        got = CR.run_review([{"id": "X", "status": FAIL, "detail": "問題あり"}],
                            reviews_dir=str(tmp_path))
        assert got["verdict"] == FAIL
        assert got["saved_to"] is not None

    def test_save_can_be_disabled_for_dry_run(self, tmp_path, monkeypatch):
        from src.data import checklist_review as CR
        monkeypatch.setattr(CR, "llm_availability", lambda: {})
        got = CR.run_review([{"id": "X", "status": PASS, "detail": ""}],
                            reviews_dir=str(tmp_path), save=False)
        assert got["saved_to"] is None
        assert not list(tmp_path.glob("*.json"))

    def test_claude_is_excluded_from_independence(self):
        """自分自身は独立レビュアーになれない。"""
        import inspect
        from src.data import checklist_review as CR
        src = inspect.getsource(CR.llm_availability)
        assert 'provider == "claude"' in src
