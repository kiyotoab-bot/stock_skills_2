"""Tests for 最新バーの NaN 補完 — KIK-759.

yfinance は最新バーの行だけ作って Close を NaN で返すことがある。
呼び出し側は df["Close"].dropna() するので **NaN 行は黙って消え、
1日古い終値が「最新」として計算に入る**。警告もエラーも出ない。

2026-08-15 に保有・計画6銘柄すべてで発生していた。RSI・SMA・
バンドウォーク・半年期日・ストップ距離がすべて1日ずれていた。
"""

import pandas as pd
import pytest

from src.data.yahoo_client.history import _patch_latest_bar


def _frame(dates, closes):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes,
         "Close": closes, "Volume": [1000] * len(closes)},
        index=idx,
    )


def _stub_bars(monkeypatch, dates, closes, available=True):
    monkeypatch.setattr(
        "src.data.jquants_client.prices.get_daily_bars",
        lambda symbol: {"available": available, "dates": dates, "closes": closes,
                        "opens": closes, "highs": closes, "lows": closes,
                        "volumes": [1000] * len(closes)},
    )


class TestPatching:
    def test_nan_tail_is_replaced(self, monkeypatch):
        df = _frame(["2026-08-13", "2026-08-14"], [4917.0, float("nan")])
        _stub_bars(monkeypatch, ["2026-08-13", "2026-08-14"], [4917.0, 5168.0])
        out = _patch_latest_bar("6701.T", df)
        close = out["Close"].dropna()
        assert str(close.index[-1])[:10] == "2026-08-14"
        assert close.iloc[-1] == 5168.0

    def test_row_count_is_preserved(self, monkeypatch):
        df = _frame(["2026-08-12", "2026-08-13", "2026-08-14"],
                    [4913.0, 4917.0, float("nan")])
        _stub_bars(monkeypatch, ["2026-08-13", "2026-08-14"], [4917.0, 5168.0])
        out = _patch_latest_bar("6701.T", df)
        assert len(out) == 3
        assert out["Close"].notna().all()

    def test_ohlcv_columns_survive(self, monkeypatch):
        df = _frame(["2026-08-13", "2026-08-14"], [4917.0, float("nan")])
        _stub_bars(monkeypatch, ["2026-08-13", "2026-08-14"], [4917.0, 5168.0])
        out = _patch_latest_bar("6701.T", df)
        for col in ("Open", "High", "Low", "Close", "Volume"):
            assert col in out.columns
        assert out["Volume"].iloc[-1] == 1000


class TestNoOp:
    def test_complete_tail_is_untouched(self, monkeypatch):
        df = _frame(["2026-08-13", "2026-08-14"], [4917.0, 5168.0])
        _stub_bars(monkeypatch, ["2026-08-13", "2026-08-15"], [4917.0, 9999.0])
        out = _patch_latest_bar("6701.T", df)
        assert out["Close"].iloc[-1] == 5168.0   # 9999 で上書きしない

    def test_non_japanese_symbol_is_skipped(self, monkeypatch):
        """米国株・指数には J-Quants が使えない。"""
        df = _frame(["2026-08-13", "2026-08-14"], [100.0, float("nan")])
        _stub_bars(monkeypatch, ["2026-08-14"], [200.0])
        out = _patch_latest_bar("AAPL", df)
        assert out["Close"].isna().iloc[-1]

    def test_index_symbol_is_skipped(self, monkeypatch):
        df = _frame(["2026-08-13", "2026-08-14"], [100.0, float("nan")])
        _stub_bars(monkeypatch, ["2026-08-14"], [200.0])
        assert _patch_latest_bar("^N225", df)["Close"].isna().iloc[-1]

    def test_jquants_not_newer_is_skipped(self, monkeypatch):
        df = _frame(["2026-08-13", "2026-08-14"], [4917.0, float("nan")])
        _stub_bars(monkeypatch, ["2026-08-13"], [4917.0])
        out = _patch_latest_bar("6701.T", df)
        assert out["Close"].isna().iloc[-1]

    def test_jquants_unavailable_is_skipped(self, monkeypatch):
        df = _frame(["2026-08-13", "2026-08-14"], [4917.0, float("nan")])
        _stub_bars(monkeypatch, ["2026-08-14"], [5168.0], available=False)
        assert _patch_latest_bar("6701.T", df)["Close"].isna().iloc[-1]

    def test_all_nan_is_skipped(self, monkeypatch):
        df = _frame(["2026-08-13", "2026-08-14"], [float("nan"), float("nan")])
        _stub_bars(monkeypatch, ["2026-08-14"], [5168.0])
        assert _patch_latest_bar("6701.T", df)["Close"].isna().all()


class TestGracefulDegradation:
    def test_jquants_error_returns_original(self, monkeypatch):
        """補完に失敗しても価格履歴そのものは返す。"""
        def _boom(symbol):
            raise RuntimeError("network down")
        monkeypatch.setattr("src.data.jquants_client.prices.get_daily_bars", _boom)
        df = _frame(["2026-08-13", "2026-08-14"], [4917.0, float("nan")])
        out = _patch_latest_bar("6701.T", df)
        assert len(out) == 2
        assert out["Close"].iloc[0] == 4917.0
