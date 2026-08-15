"""Tests for DQ4 のコード化 — KIK-761.

checklists.yaml の DQ4「データの基準日を確認したか。最新バーが null で
欠けていないか」はコードが無く目視に委ねられていた。そして目視されなかった。

2026-08-15: yfinance が 8/14 のバーを Close=NaN で返し、dropna() が落とし、
保有・計画6銘柄すべてで 8/13 の終値が「最新」として全指標に入っていた。
警告もエラーも出ない。

このゲートは**計算を始める前**に通す。個々の計算を直すのではなく、
入力が正しい日付かを最初に確かめる。
"""

import datetime

import pytest

from src.data import data_freshness as df
from src.data.checklist_review import FAIL, NA, PASS, WARN


# 2026-08-10(月)〜08-17(月)。08-11 は山の日、08-15/16 は土日
_CAL = [
    ("2026-08-10", True), ("2026-08-11", False), ("2026-08-12", True),
    ("2026-08-13", True), ("2026-08-14", True), ("2026-08-15", False),
    ("2026-08-16", False), ("2026-08-17", True),
]


@pytest.fixture(autouse=True)
def _cal(monkeypatch):
    df.reset_cache()
    monkeypatch.setattr(df, "_load_calendar", lambda: _CAL)
    yield
    df.reset_cache()


def _d(s):
    return datetime.date.fromisoformat(s)


class TestLastTradingDay:
    @pytest.mark.parametrize("today,expected", [
        ("2026-08-14", "2026-08-14"),   # 営業日当日
        ("2026-08-15", "2026-08-14"),   # 土曜 → 前営業日
        ("2026-08-16", "2026-08-14"),   # 日曜
        ("2026-08-11", "2026-08-10"),   # 祝日（山の日）
        ("2026-08-17", "2026-08-17"),
    ])
    def test_resolves(self, today, expected):
        assert df.last_trading_day(_d(today)) == expected

    def test_no_calendar_returns_none(self, monkeypatch):
        monkeypatch.setattr(df, "_load_calendar", lambda: [])
        assert df.last_trading_day(_d("2026-08-14")) is None


class TestFreshness:
    def test_all_current_passes(self):
        latest = {s: "2026-08-14" for s in ("6701.T", "7751.T")}
        r = df.check_data_freshness(latest, today=_d("2026-08-15"))[0]
        assert r["status"] == PASS
        assert r["id"] == "DQ4"

    def test_the_2026_08_15_incident_is_caught(self):
        """実害が出ていた状態。6銘柄すべてが1営業日古い。"""
        latest = {s: "2026-08-13" for s in
                  ("6701.T", "7453.T", "8031.T", "7259.T", "7751.T", "9104.T")}
        r = df.check_data_freshness(latest, today=_d("2026-08-15"))[0]
        assert r["status"] == WARN
        assert "6/6銘柄が古い" in r["detail"]

    def test_holiday_is_not_counted_as_stale(self):
        """8/11 は山の日。8/10 のバーで 8/11 に見ても古くない。"""
        r = df.check_data_freshness({"6701.T": "2026-08-10"}, today=_d("2026-08-11"))[0]
        assert r["status"] == PASS

    def test_weekend_uses_friday(self):
        r = df.check_data_freshness({"6701.T": "2026-08-14"}, today=_d("2026-08-16"))[0]
        assert r["status"] == PASS

    def test_three_business_days_is_fail(self):
        """1営業日は WARN、3営業日以上は FAIL。"""
        r = df.check_data_freshness({"6701.T": "2026-08-10"}, today=_d("2026-08-14"))[0]
        assert r["status"] == FAIL

    def test_partial_staleness_is_reported(self):
        """一部だけ古いのが最も見つけにくい。銘柄名を出す。"""
        latest = {"6701.T": "2026-08-14", "7751.T": "2026-08-13"}
        r = df.check_data_freshness(latest, today=_d("2026-08-15"))[0]
        assert r["status"] == WARN
        assert "7751.T" in r["detail"]
        assert "1/2銘柄" in r["detail"]

    def test_missing_date_is_flagged(self):
        r = df.check_data_freshness({"6701.T": None}, today=_d("2026-08-15"))[0]
        assert r["status"] == WARN
        assert "日付なし" in r["detail"]

    def test_future_date_is_not_stale(self):
        """当日中に呼ぶと当日バーが入ることがある。古い扱いにしない。"""
        r = df.check_data_freshness({"6701.T": "2026-08-17"}, today=_d("2026-08-14"))[0]
        assert r["status"] == PASS

    def test_empty_input(self):
        assert df.check_data_freshness({}, today=_d("2026-08-15"))[0]["status"] == NA


class TestNanTailReporting:
    def test_patched_symbols_are_reported(self):
        latest = {"6701.T": "2026-08-14"}
        out = df.check_data_freshness(latest, today=_d("2026-08-15"),
                                      nan_tail_by_symbol={"6701.T": True})
        assert len(out) == 2
        assert "補完" in out[1]["detail"]
        assert out[1]["status"] == PASS

    def test_patch_reported_as_warn_when_still_stale(self):
        """補完したのに古いままなら、補完が効いていない。"""
        latest = {"6701.T": "2026-08-13"}
        out = df.check_data_freshness(latest, today=_d("2026-08-15"),
                                      nan_tail_by_symbol={"6701.T": True})
        assert out[1]["status"] == WARN

    def test_no_nan_adds_no_row(self):
        out = df.check_data_freshness({"6701.T": "2026-08-14"},
                                      today=_d("2026-08-15"),
                                      nan_tail_by_symbol={"6701.T": False})
        assert len(out) == 1


class TestWithoutCalendar:
    """J-Quants が使えない環境でも「一部だけ古い」は検出できる。"""

    @pytest.fixture(autouse=True)
    def _no_cal(self, monkeypatch):
        monkeypatch.setattr(df, "_load_calendar", lambda: [])

    def test_aligned_symbols_is_na(self):
        latest = {"6701.T": "2026-08-13", "7751.T": "2026-08-13"}
        r = df.check_data_freshness(latest, today=_d("2026-08-15"))[0]
        assert r["status"] == NA
        assert "揃っている" in r["detail"]

    def test_lagging_symbol_is_warned(self):
        latest = {"6701.T": "2026-08-14", "7751.T": "2026-08-13"}
        r = df.check_data_freshness(latest, today=_d("2026-08-15"))[0]
        assert r["status"] == WARN
        assert "7751.T" in r["detail"]
