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


class TestCheckSeriesGaps:
    """DQ8: 系列の**途中**の欠落 — KIK-773.

    2026-08-31: yfinance の ^N225 が 2026-08-28 のバーを丸ごと欠落させた。
    最新バーは 08-31 で正しいので DQ4 は PASS。しかし前日比が 08-27 との
    比較になり +0.27%（正 -0.14%）と誤報告した。
    """

    _BIZ = ["2026-08-10", "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-17"]

    def test_no_gap_passes(self):
        r = df.check_series_gaps({"A": self._BIZ}, today=_d("2026-08-17"))[0]
        assert r["status"] == PASS
        assert "欠落なし" in r["detail"]

    def test_interior_gap_warns(self):
        """途中の1本欠落を WARN で拾う。"""
        series = [d for d in self._BIZ if d != "2026-08-13"]
        r = df.check_series_gaps({"A": series}, today=_d("2026-08-17"))[0]
        assert r["status"] == WARN
        assert "2026-08-13" in r["detail"]
        assert "1本欠落" in r["detail"]

    def test_three_gaps_fail(self):
        r = df.check_series_gaps(
            {"A": ["2026-08-10", "2026-08-17"]}, today=_d("2026-08-17"))[0]
        assert r["status"] == FAIL

    def test_dq4_passes_while_dq8_fails(self):
        """DQ4 では捕まらないことを明示する（この差が KIK-773 の理由）。"""
        series = [d for d in self._BIZ if d != "2026-08-13"]
        dq4 = df.check_data_freshness({"A": series[-1]}, today=_d("2026-08-17"))[0]
        dq8 = df.check_series_gaps({"A": series}, today=_d("2026-08-17"))[0]
        assert dq4["status"] == PASS
        assert dq8["status"] == WARN

    def test_non_business_day_absence_is_not_a_gap(self):
        """休場日・週末が無いのは欠落ではない。"""
        r = df.check_series_gaps({"A": self._BIZ}, today=_d("2026-08-17"))[0]
        assert r["status"] == PASS

    def test_series_starting_late_is_not_a_gap(self):
        """新規上場などで系列が途中から始まるのは欠落ではない。"""
        r = df.check_series_gaps(
            {"A": ["2026-08-14", "2026-08-17"]}, today=_d("2026-08-17"))[0]
        assert r["status"] == PASS

    def test_series_ending_early_is_not_a_gap(self):
        """末尾の古さは DQ4 の担当。DQ8 は穴だけを見る。"""
        r = df.check_series_gaps(
            {"A": ["2026-08-10", "2026-08-12"]}, today=_d("2026-08-17"))[0]
        assert r["status"] == PASS

    def test_lookback_limits_the_window(self):
        r = df.check_series_gaps(
            {"A": ["2026-08-10", "2026-08-14", "2026-08-17"]},
            today=_d("2026-08-17"), lookback=2)[0]
        assert r["status"] == PASS   # 窓は 08-14/08-17 のみ

    def test_empty_input_is_na(self):
        assert df.check_series_gaps({}, today=_d("2026-08-17"))[0]["status"] == NA

    def test_no_calendar_is_na(self, monkeypatch):
        """カレンダーが無いときは相対比較に落とさない。

        全銘柄が同じ日を落としている可能性があり、銘柄間比較では検知にならない。
        """
        monkeypatch.setattr(df, "_load_calendar", lambda: [])
        r = df.check_series_gaps({"A": self._BIZ}, today=_d("2026-08-17"))[0]
        assert r["status"] == NA

    def test_facade_matches_impl(self):
        from src.data.checklist_review import check_series_gaps as facade

        series = [d for d in self._BIZ if d != "2026-08-13"]
        assert (facade(series_by := {"A": series}, today=_d("2026-08-17"))[0]["status"]
                == df.check_series_gaps(series_by, today=_d("2026-08-17"))[0]["status"])
