"""Tests for 半年期日（6ヶ月ルール） — KIK-756.

制度信用の返済期限は最大6ヶ月。高値で信用買いした投資家の含み損が解消
されていなければ、期限までに投げ売りが出て戻り売りの重石になる。

守りたい性質:
  1. 高値更新中は重石にならない（含み損が無ければ投げ売りの動機も無い）
  2. 期日の 14〜30日前は「フライング」で需給整理が先行する
  3. 期日通過後は一巡したとみなす
"""

import datetime

import pytest

from src.data.margin_deadline import (
    DEADLINE_MONTHS,
    FLYING_END_DAYS,
    FLYING_START_DAYS,
    MIN_DRAWDOWN_PCT,
    _add_months,
    check_margin_deadline,
)


TODAY = datetime.date(2026, 8, 11)


def _series(peak_date, peak_price, current_price, today=TODAY):
    """天井 → 現在の2点だけの系列を作る（判定に必要な情報はこれで足りる）。"""
    return [peak_price, current_price], [peak_date, today]


class TestAddMonths:
    def test_simple(self):
        assert _add_months(datetime.date(2026, 3, 18), 6) == datetime.date(2026, 9, 18)

    def test_year_boundary(self):
        assert _add_months(datetime.date(2025, 11, 21), 6) == datetime.date(2026, 5, 21)

    def test_month_end_is_absorbed(self):
        """8/31 の6ヶ月後は 2/31 ではない。"""
        assert _add_months(datetime.date(2026, 8, 31), 6) == datetime.date(2027, 2, 28)

    def test_leap_year(self):
        assert _add_months(datetime.date(2023, 8, 31), 6) == datetime.date(2024, 2, 29)

    def test_negative_months(self):
        assert _add_months(datetime.date(2026, 8, 11), -12) == datetime.date(2025, 8, 11)


class TestNoOverhang:
    def test_at_the_high_is_not_overhang(self):
        """高値更新中は信用買いの含み損が無い。重石にならない。"""
        c, d = _series(datetime.date(2026, 8, 10), 4526.0, 4526.0)
        r = check_margin_deadline(c, d, today=TODAY)
        assert r["phase"] == "no_overhang"
        assert r["deadline"] is None

    def test_shallow_drawdown_is_not_overhang(self):
        """下落がごく浅いと投げ売りの動機が乏しい。閾値未満は除外する。"""
        c, d = _series(datetime.date(2026, 2, 9), 1000.0, 972.0)   # -2.8%
        assert check_margin_deadline(c, d, today=TODAY)["phase"] == "no_overhang"

    def test_threshold_boundary(self):
        """MIN_DRAWDOWN_PCT ちょうど下回れば重石として扱う。"""
        peak = datetime.date(2026, 6, 1)
        deep = check_margin_deadline(*_series(peak, 1000.0, 1000.0 * (1 - (MIN_DRAWDOWN_PCT + 0.5) / 100)),
                                     today=TODAY)
        assert deep["phase"] != "no_overhang"

    def test_no_overhang_still_reports_the_peak(self):
        """重石が無くても天井は返す。黙って消すと後から検証できない。"""
        c, d = _series(datetime.date(2026, 8, 10), 4526.0, 4526.0)
        r = check_margin_deadline(c, d, today=TODAY)
        assert r["peak_date"] == "2026-08-10"
        assert r["drawdown_pct"] == 0.0


class TestPhases:
    def test_pressure_before_flying_window(self):
        """期日まで30日超は重石が残っている局面。"""
        peak = datetime.date(2026, 3, 18)          # 期日 2026-09-18 = 38日後
        r = check_margin_deadline(*_series(peak, 1000.0, 740.0), today=TODAY)
        assert r["phase"] == "pressure"
        assert r["deadline"] == "2026-09-18"
        assert r["days_to_deadline"] == 38

    def test_flying_window(self):
        """期日の 14〜30日前は需給整理が先行して底打ちしやすい。"""
        peak = _add_months(TODAY + datetime.timedelta(days=20), -DEADLINE_MONTHS)
        r = check_margin_deadline(*_series(peak, 1000.0, 800.0), today=TODAY)
        assert r["phase"] == "flying"
        assert FLYING_END_DAYS <= r["days_to_deadline"] <= FLYING_START_DAYS

    @pytest.mark.parametrize("days", [FLYING_START_DAYS, FLYING_END_DAYS])
    def test_flying_boundaries_are_inclusive(self, days):
        peak = _add_months(TODAY + datetime.timedelta(days=days), -DEADLINE_MONTHS)
        r = check_margin_deadline(*_series(peak, 1000.0, 800.0), today=TODAY)
        assert r["phase"] == "flying"

    def test_just_outside_flying_is_pressure(self):
        peak = _add_months(TODAY + datetime.timedelta(days=FLYING_START_DAYS + 1),
                           -DEADLINE_MONTHS)
        r = check_margin_deadline(*_series(peak, 1000.0, 800.0), today=TODAY)
        assert r["phase"] == "pressure"

    def test_cleared_after_deadline(self):
        peak = datetime.date(2025, 11, 21)          # 期日 2026-05-21 = 82日前
        r = check_margin_deadline(*_series(peak, 1000.0, 809.0), today=TODAY)
        assert r["phase"] == "cleared"
        assert r["days_to_deadline"] == -82

    def test_deadline_today_is_not_cleared(self):
        peak = _add_months(TODAY, -DEADLINE_MONTHS)
        r = check_margin_deadline(*_series(peak, 1000.0, 800.0), today=TODAY)
        assert r["days_to_deadline"] == 0
        assert r["phase"] != "cleared"


class TestPeakSelection:
    def test_highest_price_wins_not_latest(self):
        """天井は最高値。直近の小さな戻り高値ではない。"""
        closes = [1000.0, 700.0, 850.0, 800.0]
        dates = [datetime.date(2026, 3, 1), datetime.date(2026, 5, 1),
                 datetime.date(2026, 7, 1), TODAY]
        r = check_margin_deadline(closes, dates, today=TODAY)
        assert r["peak_date"] == "2026-03-01"
        assert r["peak_price"] == 1000.0

    def test_lookback_excludes_older_peaks(self):
        """探索範囲の外の高値は拾わない。"""
        closes = [5000.0, 1000.0, 800.0]
        dates = [datetime.date(2024, 1, 1), datetime.date(2026, 3, 1), TODAY]
        r = check_margin_deadline(closes, dates, today=TODAY, lookback_months=12)
        assert r["peak_date"] == "2026-03-01"

    def test_current_price_is_the_last_bar(self):
        closes = [1000.0, 900.0, 750.0]
        dates = [datetime.date(2026, 3, 1), datetime.date(2026, 6, 1), TODAY]
        assert check_margin_deadline(closes, dates, today=TODAY)["current_price"] == 750.0


class TestGuards:
    def test_empty(self):
        assert check_margin_deadline([], [], today=TODAY)["phase"] == "unavailable"

    def test_length_mismatch(self):
        r = check_margin_deadline([1.0, 2.0], [TODAY], today=TODAY)
        assert r["phase"] == "unavailable"

    def test_all_dates_out_of_range(self):
        closes = [1000.0]
        dates = [datetime.date(2020, 1, 1)]
        assert check_margin_deadline(closes, dates, today=TODAY)["phase"] == "unavailable"

    def test_non_positive_prices_are_skipped(self):
        closes = [0.0, -5.0, 1000.0, 800.0]
        dates = [datetime.date(2026, 2, 1), datetime.date(2026, 2, 2),
                 datetime.date(2026, 3, 1), TODAY]
        r = check_margin_deadline(closes, dates, today=TODAY)
        assert r["peak_price"] == 1000.0

    def test_unparseable_date_is_skipped(self):
        closes = [1000.0, 800.0]
        dates = ["ゴミ", TODAY]
        r = check_margin_deadline(closes, dates, today=TODAY)
        assert r["peak_price"] == 800.0   # 天井行が落ちるので現値のみ

    def test_iso_string_dates_are_accepted(self):
        r = check_margin_deadline([1000.0, 800.0], ["2026-03-18", "2026-08-11"],
                                  today=TODAY)
        assert r["peak_date"] == "2026-03-18"

    def test_pandas_timestamp_is_accepted(self):
        pd = pytest.importorskip("pandas")
        dates = [pd.Timestamp("2026-03-18"), pd.Timestamp("2026-08-11")]
        r = check_margin_deadline([1000.0, 800.0], dates, today=TODAY)
        assert r["peak_date"] == "2026-03-18"


class TestLabel:
    def test_pressure_label_names_the_deadline(self):
        peak = datetime.date(2026, 3, 18)
        label = check_margin_deadline(*_series(peak, 1000.0, 740.0), today=TODAY)["label"]
        assert "2026-09-18" in label and "38日" in label

    def test_flying_label_says_flying(self):
        peak = _add_months(TODAY + datetime.timedelta(days=20), -DEADLINE_MONTHS)
        label = check_margin_deadline(*_series(peak, 1000.0, 800.0), today=TODAY)["label"]
        assert "フライング" in label
