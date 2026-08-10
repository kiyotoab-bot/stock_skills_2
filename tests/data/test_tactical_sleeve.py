"""Tests for the tactical (short-term) sleeve — KIK-751.

短期枠は中長期枠と別勘定で回る。ここで守りたい性質は3つ:
  1. tactical の取引が core の冷却期間・月次上限を消費しない
  2. sleeve が無い過去のレコードは core として扱われる（後方互換）
  3. 保有期限（週数・年末）の超過が overdue として出る
"""

import datetime

import pytest

from src.data.monthly_check import (
    CORE_SLEEVE,
    TACTICAL_SLEEVE,
    filter_sleeve,
    load_trades,
    realized_pnl,
    tactical_status,
    trade_budget,
)
from src.data.concentration import check_concentration


TODAY = datetime.date(2026, 8, 10)

_CFG = {
    "enabled": True, "max_pct_of_total": 5, "max_positions": 1,
    "monthly_limit": 2, "cooldown_weeks": 0, "max_hold_weeks": 8,
    "hard_deadline": "12-31", "stop_pct": 8,
}


def _trade(date_str, action="buy", symbol="X", sleeve=None, pnl=None):
    t = {"date": date_str, "action": action, "symbol": symbol,
         "shares": 100, "price": 1000, "realized_pnl": pnl, "memo": ""}
    if sleeve is not None:
        t["sleeve"] = sleeve
    return t


# ---------------------------------------------------------------------------
# 枠の分離
# ---------------------------------------------------------------------------

class TestSleeveSeparation:
    def test_tactical_trade_does_not_consume_core_budget(self):
        """短期枠の買付は中長期の冷却期間・月次上限を消費しない。"""
        trades = [_trade("2026-08-05", sleeve=TACTICAL_SLEEVE)]
        core = trade_budget(trades, TODAY, cooldown_weeks=4, monthly_limit=1)
        assert core["monthly_used"] == 0
        assert core["monthly_remaining"] == 1
        assert core["last_buy"] is None

    def test_core_trade_does_not_consume_tactical_budget(self):
        trades = [_trade("2026-08-05", sleeve=CORE_SLEEVE)]
        tac = trade_budget(trades, TODAY, cooldown_weeks=0, monthly_limit=2,
                           sleeve=TACTICAL_SLEEVE)
        assert tac["monthly_used"] == 0

    def test_missing_sleeve_counts_as_core(self):
        """sleeve キーの無い過去のレコードは core 扱い（後方互換）。"""
        trades = [_trade("2026-08-05")]
        assert trade_budget(trades, TODAY, monthly_limit=1)["monthly_used"] == 1
        assert trade_budget(trades, TODAY, monthly_limit=2,
                            sleeve=TACTICAL_SLEEVE)["monthly_used"] == 0

    def test_sleeve_none_counts_everything(self):
        trades = [_trade("2026-08-05", sleeve=CORE_SLEEVE),
                  _trade("2026-08-06", sleeve=TACTICAL_SLEEVE)]
        both = trade_budget(trades, TODAY, monthly_limit=9, sleeve=None)
        assert both["monthly_used"] == 2

    def test_filter_sleeve(self):
        trades = [_trade("2026-08-05"), _trade("2026-08-06", sleeve=TACTICAL_SLEEVE)]
        assert len(filter_sleeve(trades, CORE_SLEEVE)) == 1
        assert len(filter_sleeve(trades, TACTICAL_SLEEVE)) == 1
        assert len(filter_sleeve(trades, None)) == 2

    def test_budget_reports_its_sleeve(self):
        b = trade_budget([], TODAY, sleeve=TACTICAL_SLEEVE)
        assert b["sleeve"] == TACTICAL_SLEEVE


class TestRealizedPnlSeparation:
    def test_realized_pnl_split_by_sleeve(self):
        """短期枠の損益を中長期に混ぜない。混ぜると投入計画の効果が測れない。"""
        trades = [
            _trade("2026-08-03", action="sell", sleeve=CORE_SLEEVE, pnl=1000),
            _trade("2026-08-06", action="sell", sleeve=TACTICAL_SLEEVE, pnl=-300),
        ]
        core = realized_pnl(trades, "2026-08")
        tac = realized_pnl(trades, "2026-08", sleeve=TACTICAL_SLEEVE)
        assert core["realized_pnl"] == 1000
        assert tac["realized_pnl"] == -300
        assert core["sleeve"] == CORE_SLEEVE

    def test_zero_pnl_is_not_dropped(self):
        trades = [_trade("2026-08-06", action="sell", sleeve=TACTICAL_SLEEVE, pnl=0)]
        r = realized_pnl(trades, "2026-08", sleeve=TACTICAL_SLEEVE)
        assert r["sells_with_pnl"] == 1
        assert r["realized_pnl"] == 0


# ---------------------------------------------------------------------------
# tactical_status
# ---------------------------------------------------------------------------

class TestTacticalStatus:
    def test_empty_sleeve_can_buy(self):
        s = tactical_status([], [], 8_000_000, TODAY, _CFG)
        assert s["can_buy_now"] is True
        assert s["open_positions"] == []
        assert s["size_cap"] == 400_000

    def test_no_history_is_not_a_blocker_without_cooldown(self):
        """冷却ゼロの枠で「買付履歴なし」を塞ぐ理由にしない。

        can_buy_now=True と blockers が同時に立つと、どちらが正か読めなくなる。
        """
        s = tactical_status([], [], 8_000_000, TODAY, _CFG)
        assert s["blockers"] == []
        assert not any("買付履歴なし" in b for b in s["blockers"])

    def test_core_still_blocks_on_missing_history(self):
        """冷却がある枠では従来どおり「買付履歴なし」を出す（回帰防止）。"""
        b = trade_budget([], TODAY, cooldown_weeks=4, monthly_limit=1)
        assert any("買付履歴なし" in x for x in b["blockers"])
        assert b["can_buy_now"] is False

    def test_disabled_blocks_buying(self):
        s = tactical_status([], [], 8_000_000, TODAY, {**_CFG, "enabled": False})
        assert s["can_buy_now"] is False
        assert any("無効" in b for b in s["blockers"])

    def test_position_limit_blocks_buying(self):
        pos = [{"symbol": "3765.T", "shares": 100, "role": "tactical"}]
        trades = [_trade("2026-08-01", symbol="3765.T", sleeve=TACTICAL_SLEEVE)]
        s = tactical_status(trades, pos, 8_000_000, TODAY, _CFG)
        assert s["can_buy_now"] is False
        assert any("同時保有上限" in b for b in s["blockers"])

    def test_monthly_limit_blocks_buying(self):
        trades = [_trade("2026-08-01", sleeve=TACTICAL_SLEEVE),
                  _trade("2026-08-02", sleeve=TACTICAL_SLEEVE)]
        s = tactical_status(trades, [], 8_000_000, TODAY, _CFG)
        assert s["monthly_used"] == 2
        assert s["can_buy_now"] is False

    def test_core_position_is_not_tactical(self):
        """role が tactical でない保有は短期枠の建玉に数えない。"""
        pos = [{"symbol": "7751.T", "shares": 300, "role": "income"}]
        s = tactical_status([], pos, 8_000_000, TODAY, _CFG)
        assert s["open_positions"] == []
        assert s["can_buy_now"] is True

    def test_weeks_held_is_computed_from_entry(self):
        pos = [{"symbol": "3765.T", "shares": 100, "role": "tactical"}]
        trades = [_trade("2026-07-27", symbol="3765.T", sleeve=TACTICAL_SLEEVE)]
        s = tactical_status(trades, pos, 8_000_000, TODAY, _CFG)
        op = s["open_positions"][0]
        assert op["weeks_held"] == pytest.approx(2.0, abs=0.2)
        assert op["hold_deadline"] == "2026-09-21"
        assert s["overdue"] == []

    def test_hold_limit_exceeded_is_overdue(self):
        """8週を超えたら損益に関係なく手仕舞い対象。塩漬け防止の本体。"""
        pos = [{"symbol": "3765.T", "shares": 100, "role": "tactical"}]
        trades = [_trade("2026-06-01", symbol="3765.T", sleeve=TACTICAL_SLEEVE)]
        s = tactical_status(trades, pos, 8_000_000, TODAY, _CFG)
        assert len(s["overdue"]) == 1
        assert "保有" in s["overdue"][0]

    def test_missing_entry_date_is_overdue(self):
        """建玉があるのに取引履歴が無い＝期限を計算できない。放置しない。"""
        pos = [{"symbol": "3765.T", "shares": 100, "role": "tactical"}]
        s = tactical_status([], pos, 8_000_000, TODAY, _CFG)
        assert any("エントリー日" in x for x in s["overdue"])

    def test_year_end_deadline_flags_open_position(self):
        pos = [{"symbol": "3765.T", "shares": 100, "role": "tactical"}]
        trades = [_trade("2026-12-20", symbol="3765.T", sleeve=TACTICAL_SLEEVE)]
        s = tactical_status(trades, pos, 8_000_000, datetime.date(2026, 12, 31), _CFG)
        assert any("年末期限" in x for x in s["overdue"])

    def test_year_end_countdown(self):
        s = tactical_status([], [], 8_000_000, TODAY, _CFG)
        assert s["year_end_deadline"] == "2026-12-31"
        assert s["days_to_year_end"] == 143

    def test_size_cap_scales_with_total(self):
        assert tactical_status([], [], 10_000_000, TODAY, _CFG)["size_cap"] == 500_000


# ---------------------------------------------------------------------------
# 集中度からの除外
# ---------------------------------------------------------------------------

class TestConcentrationExcludesTactical:
    def _cfg(self):
        return {"concentration": {
            "basis": "equity",
            "single_stock": {"normal": {"warn": 12, "limit": 15},
                             "conviction": {"warn": 20, "limit": 25}},
            "top3_stocks": {"warn": 60, "limit": 70},
            "sector": {"warn": 35, "limit": 45},
        }}

    def test_tactical_excluded_from_denominator(self):
        """短期枠を混ぜると中長期の1銘柄比率が動いてしまう。"""
        core_only = [{"symbol": "A", "value": 1_000_000, "sector": "S"}]
        with_tac = core_only + [{"symbol": "T", "value": 1_000_000,
                                 "sector": "S", "role": "tactical"}]
        a = check_concentration(core_only, self._cfg())
        b = check_concentration(with_tac, self._cfg())
        assert a["equity"] == b["equity"] == 1_000_000
        assert a["stocks"][0]["pct_equity"] == b["stocks"][0]["pct_equity"]
        assert len(b["stocks"]) == 1   # 短期枠は銘柄テーブルに出ない

    def test_tactical_reported_not_silently_dropped(self):
        pos = [{"symbol": "A", "value": 1_000_000, "sector": "S"},
               {"symbol": "T", "value": 400_000, "sector": "S", "role": "tactical"}]
        r = check_concentration(pos, self._cfg())
        assert r["tactical_excluded"] == ["T"]
        assert r["tactical_value"] == 400_000

    def test_tactical_still_counted_in_total_assets(self):
        """判定からは外すが、総資産には残す（現金と同じ扱いにはしない）。"""
        pos = [{"symbol": "A", "value": 1_000_000, "sector": "S"},
               {"symbol": "T", "value": 400_000, "sector": "S", "role": "tactical"}]
        r = check_concentration(pos, self._cfg(), cash=600_000)
        assert r["total_assets"] == 2_000_000

    def test_only_tactical_positions_is_not_a_crash(self):
        pos = [{"symbol": "T", "value": 400_000, "sector": "S", "role": "tactical"}]
        r = check_concentration(pos, self._cfg())
        assert r["equity"] == 0.0
        assert r["tactical_excluded"] == ["T"]


# ---------------------------------------------------------------------------
# save_trade → load_trades の往復
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_saved_sleeve_is_read_back(self, tmp_path):
        from src.data.history.save_trade import save_trade
        base = tmp_path / "history"
        save_trade("3765.T", "buy", 100, 2392, "JPY", "2026-08-10",
                   base_dir=str(base), sleeve="tactical")
        loaded = load_trades(str(base / "trade"))
        assert len(loaded) == 1
        assert loaded[0]["sleeve"] == "tactical"

    def test_default_sleeve_is_core(self, tmp_path):
        from src.data.history.save_trade import save_trade
        base = tmp_path / "history"
        save_trade("7751.T", "buy", 300, 4651, "JPY", "2026-08-10", base_dir=str(base))
        loaded = load_trades(str(base / "trade"))
        assert loaded[0]["sleeve"] == "core"

    def test_max_positions_zero_blocks_buying(self):
        """max_positions=0 は「建てない」という意思表示。`or 1` で潰さない。"""
        s = tactical_status([], [], 8_000_000, TODAY, {**_CFG, "max_positions": 0})
        assert s["can_buy_now"] is False
        assert s["max_positions"] == 0

    def test_partial_config_falls_back_to_defaults(self):
        """部分的な dict を渡されても既定で埋める。

        埋めないと max_pct_of_total が欠けたとき size_cap=0 になり、
        枠が黙って使えなくなる（エラーも警告も出ない）。
        """
        s = tactical_status([], [], 8_000_000, TODAY, {"enabled": True})
        assert s["size_cap"] == 400_000
        assert s["max_hold_weeks"] == 8
        assert s["stop_pct"] == 8
