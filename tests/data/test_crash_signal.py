"""暴落全力買いサイン検知のテスト（src/data/crash_signal.py・2026-09-22 レビュー修正版）.

コミット 0d44467 のレビューで確定した欠陥の回帰テスト:
  #1 平日朝（当日バー未確定）に None で沈黙 → 前営業日フォールバック
  #2 障害と平常が区別不能 → available/reason で縮退を明示
  #4 全市場ベースで閾値未較正・ETFの分子分母不整合 → MktCap行限定 + 1.4%
"""

import datetime

import pandas as pd
import pytest

from src.data import crash_signal as CS
from src.data.crash_signal import (CRASH_STOP_LOW_MIN, CRASH_TURNOVER_CAP_RATIO,
                                   evaluate_crash_buy_signal)


class TestEvaluate:
    """純関数部（閾値は定数参照 — 再較正してもテストが意図を保つ）."""

    def test_both_signals_fire(self):
        """2024-08-05 型: ストップ安800・売買代金比が閾値超."""
        cap = 1000e12
        r = evaluate_crash_buy_signal(800, cap * (CRASH_TURNOVER_CAP_RATIO * 1.5), cap)
        assert r["mechanical_signals"] == 2
        assert "2/2" in r["label"] and "14:30" in r["label"] and "人が判断" in r["label"]

    def test_normal_market(self):
        """平常日（2026-09-18 実測 0.80% 相当）は 0/2."""
        r = evaluate_crash_buy_signal(0, 11.27e12, 1410e12)
        assert r["mechanical_signals"] == 0
        assert "平常" in r["label"]

    def test_calm_day_has_headroom(self):
        """#4 の核心: 較正後の閾値は平常日実測の1.5倍以上の余裕を持つ."""
        calm_ratio = 11.27e12 / 1410e12
        assert CRASH_TURNOVER_CAP_RATIO >= calm_ratio * 1.5

    def test_stop_low_boundary(self):
        assert evaluate_crash_buy_signal(CRASH_STOP_LOW_MIN, 0, 1e12)["signal_stop_low"]
        assert not evaluate_crash_buy_signal(CRASH_STOP_LOW_MIN - 1, 0, 1e12)["signal_stop_low"]

    def test_ratio_boundary_exact_does_not_fire(self):
        """書籍は「超える」— 閾値ちょうどは不成立."""
        cap = 1000e12
        r = evaluate_crash_buy_signal(0, cap * CRASH_TURNOVER_CAP_RATIO, cap)
        assert r["signal_turnover"] is False

    def test_zero_cap_is_not_crash(self):
        r = evaluate_crash_buy_signal(0, 5e12, 0)
        assert r["turnover_cap_ratio"] is None and r["signal_turnover"] is False

    def test_available_true_on_evaluate(self):
        assert evaluate_crash_buy_signal(0, 1e12, 100e12)["available"] is True


def _bars(rows):
    return pd.DataFrame(rows, columns=["Code", "LL", "Va", "MktCap"])


class TestDetect:
    """取得部。client をモックして #1/#2/#4 の挙動を固定する."""

    @pytest.fixture(autouse=True)
    def _cal(self, monkeypatch):
        import src.data.data_freshness as DF
        DF.reset_cache()
        today = datetime.date.today().isoformat()
        y1 = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        y2 = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
        monkeypatch.setattr(DF, "_load_calendar",
                            lambda: [(y2, True), (y1, True), (today, True)])
        yield
        DF.reset_cache()

    def _client(self, monkeypatch, frames_by_date, avail=True, get_exc=None):
        class C:
            def get_eq_bars_daily(self, date_yyyymmdd=""):
                if get_exc:
                    raise get_exc
                return frames_by_date.get(date_yyyymmdd, pd.DataFrame())
        import src.data.jquants_client._client as JC
        monkeypatch.setattr(JC, "is_available", lambda: avail)
        monkeypatch.setattr(JC, "get_client", lambda: C())

    def test_falls_back_to_previous_business_day(self, monkeypatch):
        """#1 回帰: 当日バーが空でも前営業日で判定する（沈黙しない）."""
        today = datetime.date.today().isoformat().replace("-", "")
        y1 = (datetime.date.today() - datetime.timedelta(days=1)).isoformat().replace("-", "")
        self._client(monkeypatch, {y1: _bars([("1301", "0", 1e9, 1000.0)])})
        r = CS.detect_crash_buy_signal()
        assert r["available"] is True
        assert r["date"] == y1                      # 当日→空、前日→採用

    def test_unconfigured_is_na_not_calm(self, monkeypatch):
        """#2 回帰: 未設定は available=False で「平常」と区別される."""
        self._client(monkeypatch, {}, avail=False)
        r = CS.detect_crash_buy_signal()
        assert r["available"] is False
        assert "n/a" in r["label"] and "未設定" in r["reason"]

    def test_fetch_error_is_na_with_reason(self, monkeypatch):
        """#2 回帰: 429等の例外は理由つき n/a になる."""
        self._client(monkeypatch, {}, get_exc=RuntimeError("429 Too Many Requests"))
        r = CS.detect_crash_buy_signal()
        assert r["available"] is False
        assert "RuntimeError" in r["reason"]

    def test_all_dates_empty_is_na(self, monkeypatch):
        self._client(monkeypatch, {})
        r = CS.detect_crash_buy_signal()
        assert r["available"] is False
        assert "バー" in r["reason"]

    def test_etf_rows_excluded_from_both_sides(self, monkeypatch):
        """#4 回帰: MktCap null 行（レバETF等）は分子からも分母からも外す."""
        today = datetime.date.today().isoformat().replace("-", "")
        rows = [("1301", "0", 1.0e9, 1000.0),      # 株式
                ("1570", "1", 9.0e9, None)]        # ETF: 巨額の売買代金+ストップ安
        self._client(monkeypatch, {today: _bars(rows)})
        r = CS.detect_crash_buy_signal()
        assert r["available"] is True
        assert r["rows_dropped_no_mktcap"] == 1
        assert r["stop_low_count"] == 0            # ETFのストップ安は数えない
        assert r["turnover_jpy"] == 1.0e9          # ETFの売買代金は分子に入らない

    def test_explicit_date_bypasses_fallback(self, monkeypatch):
        d = "20260918"
        self._client(monkeypatch, {d: _bars([("1301", "1", 1e9, 1000.0)])})
        r = CS.detect_crash_buy_signal(date_yyyymmdd=d)
        assert r["available"] and r["date"] == d and r["stop_low_count"] == 1
