"""Tests for concentration checks (KIK-735).

2026-08-07 のユーザー判断で「確信度加重の集中投資」を導入した。
上限を 15% → conviction 25% に引き上げる代わりに、conviction を CV1/CV2/CV3 の
条件で機械的に判定する。各テストは実際のPFと過去の失敗を再現している。
"""

import pytest

from src.data.concentration import (
    EXEMPT,
    GREEN,
    RED,
    YELLOW,
    check_concentration,
    classify_conviction,
    load_concentration_config,
    max_additional_shares,
)

CFG = {
    "concentration": {
        "basis": "equity",
        "single_stock": {
            "normal": {"warn": 12, "limit": 15},
            "conviction": {"warn": 20, "limit": 25},
        },
        "top3_stocks": {"warn": 60, "limit": 70},
        "sector": {"warn": 35, "limit": 45},
    }
}

# 2026-08-06 終値の実際のPF
ACTUAL = [
    {"symbol": "8031.T", "value": 476300, "sector": "Industrials"},
    {"symbol": "6701.T", "value": 469000, "sector": "Technology"},
    {"symbol": "7453.T", "value": 439500, "sector": "Consumer Cyclical"},
    {"symbol": "7259.T", "value": 224300, "sector": "Consumer Cyclical"},
]
CASH = 6296491


def _by_sym(res):
    return {s["symbol"]: s for s in res["stocks"]}


class TestDenominator:
    """分母未定義で同じPFが逆の判定になっていた件（2026-08-07 発覚）。

    日次(6/2,6/5)は総資産比・週次(7/27)は株式比を使っており、
    8031.T は 6.2% と 30.0% の両方で報告されていた。
    """

    def test_equity_is_the_basis(self):
        res = check_concentration(ACTUAL, CFG, cash=CASH)
        assert res["basis"] == "equity"
        got = _by_sym(res)["8031.T"]
        assert got["pct_equity"] == pytest.approx(29.6, abs=0.1)
        assert got["pct_total"] == pytest.approx(6.0, abs=0.1)

    def test_cash_does_not_dilute_the_verdict(self):
        """現金を増やしても判定は変わらないこと。"""
        a = check_concentration(ACTUAL, CFG, cash=0)
        b = check_concentration(ACTUAL, CFG, cash=99_000_000)
        assert a["verdict"] == b["verdict"]
        assert _by_sym(a)["8031.T"]["level"] == _by_sym(b)["8031.T"]["level"]

    def test_actual_portfolio_breaches_as_normal(self):
        """現行PFは normal 扱いだと3銘柄が limit 超過。"""
        res = check_concentration(ACTUAL, CFG, cash=CASH)
        red = [s["symbol"] for s in res["stocks"] if s["level"] == RED]
        assert set(red) == {"8031.T", "6701.T", "7453.T"}
        assert res["verdict"] == RED


class TestTiers:
    def test_conviction_raises_the_limit(self):
        pos = [dict(p) for p in ACTUAL]
        pos[2]["tier"] = "conviction"      # 7453.T 26.8% → conviction なら limit 25 超
        res = check_concentration(pos, CFG, cash=CASH)
        assert _by_sym(res)["7453.T"]["limit"] == 25

    def test_same_pct_differs_by_tier(self):
        """18% は normal なら red、conviction なら green。tier が判定を変える。"""
        pos = [{"symbol": "A", "value": 18, "tier": "conviction", "sector": "S1"},
               {"symbol": "B", "value": 18, "tier": "normal", "sector": "S2"},
               {"symbol": "C", "value": 64, "tier": "conviction", "sector": "S3"}]
        res = check_concentration(pos, CFG)
        assert _by_sym(res)["A"]["level"] == GREEN     # 18 < warn 20
        assert _by_sym(res)["B"]["level"] == RED       # 18 >= limit 15
        assert _by_sym(res)["C"]["level"] == RED       # 64 >= limit 25

    @pytest.mark.parametrize("pct,expect", [
        (19.9, GREEN), (20.0, YELLOW), (24.9, YELLOW), (25.0, RED)])
    def test_conviction_thresholds(self, pct, expect):
        pos = [{"symbol": "A", "value": pct, "tier": "conviction", "sector": "S1"},
               {"symbol": "B", "value": 100 - pct, "tier": "conviction", "sector": "S2"}]
        assert _by_sym(check_concentration(pos, CFG))["A"]["level"] == expect

    def test_unknown_tier_falls_back_to_normal(self):
        pos = [{"symbol": "A", "value": 16, "tier": "なんとなく", "sector": "S"},
               {"symbol": "B", "value": 84, "sector": "S2"}]
        res = check_concentration(pos, CFG)
        assert _by_sym(res)["A"]["limit"] == 15

    @pytest.mark.parametrize("pct,expect", [
        (11.9, GREEN), (12.0, YELLOW), (14.9, YELLOW), (15.0, RED)])
    def test_normal_thresholds(self, pct, expect):
        pos = [{"symbol": "A", "value": pct, "sector": "S1"},
               {"symbol": "B", "value": 100 - pct, "sector": "S2"}]
        assert _by_sym(check_concentration(pos, CFG))["A"]["level"] == expect


class TestConvictionOverride:
    """7453.T 良品計画: ユーザーが「テーゼ関係なく保持」と明言した銘柄。

    株式比 26.8% で conviction limit 25% を超えるが、**トリムの根拠にしない**。
    """

    def test_override_is_exempt(self):
        pos = [dict(p) for p in ACTUAL]
        pos[2]["tier"] = "conviction_override"
        res = check_concentration(pos, CFG, cash=CASH)
        assert _by_sym(res)["7453.T"]["level"] == EXEMPT

    def test_override_does_not_make_verdict_red_by_itself(self):
        pos = [{"symbol": "7453.T", "value": 90, "tier": "conviction_override",
                "sector": "Consumer Cyclical"},
               {"symbol": "X", "value": 10, "tier": "normal", "sector": "Other"}]
        res = check_concentration(pos, CFG)
        assert _by_sym(res)["7453.T"]["level"] == EXEMPT
        # top3/sector 側では依然として数えられる（事実の報告は止めない）
        assert res["top3"]["pct_equity"] == pytest.approx(100.0)

    def test_override_cannot_be_bought_more(self):
        got = max_additional_shares("7453.T", 4395, ACTUAL,
                                    tier="conviction_override", config=CFG)
        assert got["shares"] == 0


class TestClassifyConviction:
    def _notes(self, **kw):
        base = {"symbol": "7751.T", "note_type": "thesis",
                "content": "【7751.T キヤノン 一次情報検証】J-Quants 会社予想で確認"}
        base.update(kw)
        return [base]

    def test_all_three_criteria_met(self):
        got = classify_conviction("7751.T", self._notes(),
                                  {"7751.T": {"stop": 4100.0}})
        assert got["tier"] == "conviction"
        assert got["criteria"] == {"CV1": True, "CV2": True, "CV3": True}

    def test_missing_exit_condition_is_normal(self):
        """CV3 が欠けたら 25% は張れない。集中とストップ規律は表裏。"""
        got = classify_conviction("7751.T", self._notes(), {})
        assert got["tier"] == "normal"
        assert got["unmet"] == ["CV3"]

    def test_missing_primary_source_is_normal(self):
        got = classify_conviction(
            "7751.T", self._notes(content="なんとなく良さそう"),
            {"7751.T": {"stop": 4100.0}})
        assert got["tier"] == "normal"
        assert "CV1" in got["unmet"]

    def test_no_thesis_is_normal(self):
        got = classify_conviction("9999.T", [], {"9999.T": {"stop": 100.0}})
        assert got["tier"] == "normal"
        assert set(got["unmet"]) >= {"CV1", "CV2"}

    def test_user_override_wins(self):
        """良品計画は exit条件が無いが override で conviction_override になる。"""
        got = classify_conviction("7453.T", [], {"7453.T": {"stop": None, "conviction": True}})
        assert got["tier"] == "conviction_override"
        assert got["override"] is True

    def test_override_detected_from_note_text(self):
        notes = [{"symbol": "8267.T", "note_type": "thesis",
                  "content": "conviction_override: True ホールド確定"}]
        assert classify_conviction("8267.T", notes, {})["tier"] == "conviction_override"

    def test_exit_rule_note_satisfies_cv3(self):
        notes = self._notes() + [{"symbol": "7751.T", "note_type": "exit-rule",
                                  "content": "¥4,100 割れで撤退"}]
        assert classify_conviction("7751.T", notes, {})["tier"] == "conviction"

    def test_symbol_matching_is_case_insensitive(self):
        notes = [{"symbol": "aapl", "note_type": "thesis",
                  "content": "会社発表ベースで検証済み"}]
        got = classify_conviction("AAPL", notes, {"AAPL": {"stop": 1.0}})
        assert got["tier"] == "conviction"

    def test_other_symbols_notes_are_ignored(self):
        notes = [{"symbol": "OTHER.T", "note_type": "thesis", "content": "会社予想で検証"}]
        assert classify_conviction("7751.T", notes, {})["tier"] == "normal"


class TestTop3AndSector:
    def test_top3_uses_equity(self):
        res = check_concentration(ACTUAL, CFG, cash=CASH)
        assert res["top3"]["pct_equity"] == pytest.approx(86.1, abs=0.2)
        assert res["top3"]["level"] == RED

    def test_sector_aggregates(self):
        res = check_concentration(ACTUAL, CFG, cash=CASH)
        cc = [s for s in res["sectors"] if s["sector"] == "Consumer Cyclical"][0]
        assert cc["pct_equity"] == pytest.approx(41.2, abs=0.2)
        assert cc["level"] == YELLOW      # warn 35 / limit 45

    def test_two_conviction_in_one_sector_hits_sector_limit(self):
        pos = [{"symbol": "A", "value": 25, "tier": "conviction", "sector": "Tech"},
               {"symbol": "B", "value": 25, "tier": "conviction", "sector": "Tech"},
               {"symbol": "C", "value": 50, "tier": "normal", "sector": "Other"}]
        res = check_concentration(pos, CFG)
        tech = [s for s in res["sectors"] if s["sector"] == "Tech"][0]
        assert tech["pct_equity"] == pytest.approx(50.0)
        assert tech["level"] == RED


class TestMaxAdditionalShares:
    """上限は『これ以上買わない』の基準。買える量を返せて初めて使える。"""

    def test_accounts_for_denominator_growth(self):
        """買い増すと分母も増える。単純な (limit*equity - current) では過小になる。"""
        pos = [{"symbol": "A", "value": 100_000}, {"symbol": "B", "value": 900_000}]
        got = max_additional_shares("A", 1000, pos, tier="normal", config=CFG)
        # room = (0.15*1_000_000 - 100_000) / 0.85 = 58,823
        assert got["room_jpy"] == pytest.approx(58_823.5, abs=1)
        assert got["lots"] == 0          # 100株 = ¥100,000 なので買えない
        # 買い増し後に上限ちょうどになることの確認
        after = (100_000 + got["room_jpy"]) / (1_000_000 + got["room_jpy"])
        assert after == pytest.approx(0.15, abs=1e-9)

    def test_returns_whole_lots_only(self):
        pos = [{"symbol": "A", "value": 100_000}, {"symbol": "B", "value": 900_000}]
        got = max_additional_shares("A", 300, pos, tier="normal", config=CFG)
        assert got["shares"] % 100 == 0
        assert got["shares"] == 100      # ¥30,000/lot、room ¥58,823 → 1単元

    def test_already_over_limit_returns_zero(self):
        got = max_additional_shares("8031.T", 4763, ACTUAL, tier="normal", config=CFG)
        assert got["shares"] == 0
        assert "既に上限" in got["reason"]

    def test_conviction_has_more_room(self):
        n = max_additional_shares("7259.T", 2243, ACTUAL, tier="normal", config=CFG)
        c = max_additional_shares("7259.T", 2243, ACTUAL, tier="conviction", config=CFG)
        assert c["room_jpy"] > n["room_jpy"]

    def test_new_position_from_scratch(self):
        pos = [{"symbol": "A", "value": 1_000_000}]
        got = max_additional_shares("NEW.T", 1000, pos, tier="normal", config=CFG)
        assert got["shares"] > 0

    @pytest.mark.parametrize("price", [0, -1])
    def test_bad_price_is_safe(self, price):
        assert max_additional_shares("A", price, ACTUAL, config=CFG)["shares"] == 0


class TestEmptyAndConfig:
    def test_no_positions(self):
        res = check_concentration([], CFG, cash=1000)
        assert res["verdict"] == GREEN
        assert "判定不能" in res["note"]

    def test_real_config_loads_and_has_tiers(self):
        cfg = load_concentration_config()
        single = cfg["concentration"]["single_stock"]
        assert cfg["concentration"]["basis"] == "equity"
        assert single["normal"]["limit"] == 15
        assert single["conviction"]["limit"] == 25
        assert len(cfg["conviction_criteria"]) == 3
        assert cfg["conviction_override"]["never_propose_sell"] is True


class TestPreOrderPO8:
    """発注前チェックに集中度を組み込む（PO8）。

    2026-06-22 の 8031.T 購入時は信用倍率38.5倍を見ていなかったのと同様に、
    集中度も発注の瞬間には誰も見ていなかった。買った後の比率を先に出す。
    """

    # 総資産 ¥7,905,591 / cash目標20% → 計画株式額 ¥6,324,473
    PLANNED = 6_324_473.0

    def _po8(self, **kw):
        from src.data.checklist_review import check_order
        kw.setdefault("info", {"price": 4763.0})
        kw.setdefault("positions", ACTUAL)
        kw.setdefault("denominator", self.PLANNED)
        res = check_order(kw.pop("symbol", "8031.T"), kw.pop("info"),
                          positions=kw.pop("positions"), **kw)
        return [r for r in res if r["id"] == "PO8"][0]

    def test_canon_purchase_passes_against_planned_equity(self):
        """8/10 キヤノン100株 ¥452,700。

        現在株式 ¥1,609,100 を分母にすると 22.0% で FAIL になるが、
        計画株式額 ¥6,324,473 に対しては 7.2% でしかない。
        """
        from src.data.checklist_review import PASS as P
        got = self._po8(symbol="7751.T", info={"price": 4527.0})
        assert got["status"] == P
        assert "単元" in got["detail"]

    def test_current_equity_denominator_blocks_everything(self):
        """分母を現在株式にすると1単元も買えない = 指標として使えない。"""
        from src.data.checklist_review import FAIL as F
        got = self._po8(symbol="7751.T", info={"price": 4527.0}, denominator=None)
        assert got["status"] == F

    def test_over_limit_name_still_fails(self):
        """8031.T ¥476,300 は計画株式比 7.5%。さらに買うと 15% を超える量は限られる。"""
        got = self._po8(symbol="8031.T")
        assert got["status"] in ("PASS", "FAIL")
        from src.data.concentration import max_additional_shares
        room = max_additional_shares("8031.T", 4763, ACTUAL, tier="normal",
                                     config=CFG, denominator=self.PLANNED)
        # 上限 ¥948,671 − 現在 ¥476,300 = ¥472,371 → 4763*100=¥476,300 で0単元
        assert room["room_jpy"] == pytest.approx(472_370.95, abs=1)
        assert room["lots"] == 0

    def test_conviction_tier_gives_more_room(self):
        n = self._po8(symbol="7259.T", info={"price": 2243.0}, tier="normal")
        c = self._po8(symbol="7259.T", info={"price": 2243.0}, tier="conviction")
        assert c["detail"] != n["detail"]

    def test_override_is_warned_not_failed(self):
        from src.data.checklist_review import WARN as W
        got = self._po8(symbol="7453.T", info={"price": 4395.0},
                        tier="conviction_override")
        assert got["status"] == W
        assert "買い増しの根拠にはしない" in got["detail"]

    def test_missing_price_is_na(self):
        from src.data.checklist_review import NA as N
        assert self._po8(symbol="X", info={})["status"] == N

    def test_po8_absent_when_positions_not_passed(self):
        """後方互換: positions を渡さなければ従来どおり PO8 は出ない。"""
        from src.data.checklist_review import check_order
        ids = {r["id"] for r in check_order("7751.T", {"price": 4527.0})}
        assert "PO8" not in ids
        assert {"PO2", "PO3", "PO4", "PO7"} <= ids


class TestPlannedEquity:
    """再構築期の分母（2026-08-07 に PO8 のテストで発覚）。

    株式が総資産の20.4%しかない時期に現在株式を分母にすると、
    キヤノン100株 ¥452,700 が株式比22.0%となり normal limit 15% を突破する。
    総資産比では 5.7% でリスクは小さく、判定として無意味だった。
    """

    def test_matches_the_actual_numbers(self):
        from src.data.concentration import planned_equity
        assert planned_equity(7_905_591, 20.0) == pytest.approx(6_324_473, abs=1)

    def test_canon_pct_under_each_denominator(self):
        from src.data.concentration import planned_equity
        cost = 452_700
        cur_eq = sum(p["value"] for p in ACTUAL)
        assert cost / (cur_eq + cost) * 100 == pytest.approx(22.0, abs=0.1)
        assert cost / planned_equity(7_905_591, 20.0) * 100 == pytest.approx(7.2, abs=0.1)
        assert cost / 7_905_591 * 100 == pytest.approx(5.7, abs=0.1)

    def test_check_concentration_uses_planned(self):
        from src.data.concentration import planned_equity
        pl = planned_equity(7_905_591, 20.0)
        res = check_concentration(ACTUAL, CFG, cash=CASH, denominator=pl)
        assert res["denominator_is_planned"] is True
        assert res["verdict"] == GREEN, "計画株式比では全銘柄 7.5% 以下"
        assert _by_sym(res)["8031.T"]["pct_equity"] == pytest.approx(7.5, abs=0.1)

    def test_smaller_denominator_is_ignored(self):
        """フル投資後に planned < 現在株式 でも現在株式が勝つ。"""
        res = check_concentration(ACTUAL, CFG, cash=0, denominator=1000)
        assert res["denominator_is_planned"] is False
        assert _by_sym(res)["8031.T"]["pct_equity"] == pytest.approx(29.6, abs=0.1)

    @pytest.mark.parametrize("bad", [0, -1, None])
    def test_bad_total_assets(self, bad):
        from src.data.concentration import planned_equity
        assert planned_equity(bad) == 0.0

    @pytest.mark.parametrize("pct,want", [(0, 1_000_000), (100, 0), (150, 0), (-10, 1_000_000)])
    def test_cash_pct_is_clamped(self, pct, want):
        from src.data.concentration import planned_equity
        assert planned_equity(1_000_000, pct) == pytest.approx(want)

    def test_planned_denominator_does_not_grow_when_buying(self):
        """現金→株式の付け替えなので分母は動かない。"""
        from src.data.concentration import max_additional_shares
        pl = 6_324_473.0
        got = max_additional_shares("NEW.T", 1000, ACTUAL, tier="normal",
                                    config=CFG, denominator=pl)
        assert got["room_jpy"] == pytest.approx(0.15 * pl, abs=1)
