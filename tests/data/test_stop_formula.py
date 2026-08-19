"""Tests for 統一式ストップとトレーリング判定 — KIK-759.

    stop = max(簿価×0.85, min(局面高値×0.92, 現値×(1-0.85σ_h60)))

2026-08-07 以降この式で運用しているが関数が無く、7751.T ¥4,350 /
9104.T ¥5,787 / 6701.T ¥4,609 はすべて手計算だった。

守りたい性質:
  1. 3基準の min/max が仕様どおり
  2. **切り下げを提案しない**（トレーリングは上げるだけ）
"""

import pytest

from src.data.stop_formula import (
    HARD_FLOOR_RATIO,
    PHASE_HIGH_RATIO,
    SIGMA_MULTIPLIER,
    SIGMA_WINDOW,
    calc_stop,
    check_trailing_stop,
)


def _series(n=120, start=1000.0, step=0.0, noise=0.0):
    """σ を持たせるため交互に振らせた系列。"""
    out = []
    p = start
    for i in range(n):
        p = p + step + (noise if i % 2 else -noise)
        out.append(p)
    return out


class TestCalcStop:
    def test_three_bases_are_reported(self):
        c = _series(noise=10)
        r = calc_stop(c, book_value=900.0)
        assert r["hard_floor"] == round(900.0 * HARD_FLOOR_RATIO)
        assert r["phase_high_base"] == round(max(c[-60:]) * PHASE_HIGH_RATIO)
        assert r["stop"] == max(r["hard_floor"], min(r["phase_high_base"], r["vol_base"]))

    def test_hard_floor_binds_when_highest(self):
        """簿価が高い（含み損が深い）と簿価×0.85 が効く。"""
        c = _series(noise=5)
        r = calc_stop(c, book_value=5000.0)
        assert r["binding"] == "hard"
        assert r["stop"] == round(5000.0 * HARD_FLOOR_RATIO)

    def test_vol_binds_on_high_volatility(self):
        """σ が大きいとボラ基準が局面高値基準より下に来る。"""
        c = _series(noise=60)
        r = calc_stop(c, book_value=500.0)
        assert r["binding"] == "vol"
        assert r["vol_base"] < r["phase_high_base"]

    def test_phase_high_binds_near_the_high_with_low_volatility(self):
        """現値が局面高値の近くで σ が小さいと、局面高値×0.92 が効く。

        実例は 9104.T 商船三井（現値が60日高値ちょうど・binding=phase_high）。
        高値から 8% 以内かつ 0.85σ√20 < 8% のとき、局面高値基準が下に来る。
        """
        c = _series(noise=1)          # 999/1000 を往復する低ボラ系列
        r = calc_stop(c, book_value=500.0)
        assert r["binding"] == "phase_high"
        assert r["phase_high_base"] < r["vol_base"]

    def test_distance_is_measured_from_current_price(self):
        c = _series(noise=10)
        r = calc_stop(c, book_value=900.0)
        expected = (c[-1] - r["stop"]) / c[-1] * 100
        assert r["distance_pct"] == pytest.approx(expected, abs=0.05)

    def test_sigma_uses_the_configured_horizon(self):
        """0.85σ の σ は日次だが、掛かるのは √20 のホライズン。

        アンカーの平滑（KIK-768）と切り分けるため anchor_smooth=1 で見る。
        """
        c = _series(noise=10)
        r = calc_stop(c, book_value=100.0, anchor_smooth=1)
        sigma = r["daily_sigma_pct"] / 100
        expected = c[-1] * (1 - SIGMA_MULTIPLIER * sigma * (SIGMA_WINDOW ** 0.5))
        assert r["vol_base"] == round(expected)

    def test_stop_never_below_hard_floor(self):
        c = [1000.0] + [1000.0 - i * 8 for i in range(1, 120)]
        r = calc_stop(c, book_value=1000.0)
        assert r["stop"] >= r["hard_floor"]


class TestGuards:
    def test_too_short(self):
        assert calc_stop([100.0] * 10, 90.0)["stop"] is None

    def test_empty(self):
        assert calc_stop([], 90.0)["stop"] is None

    def test_zero_book_value(self):
        """取得前に現値を簿価として渡すのを防ぐ意味でも、0 は弾く。"""
        assert calc_stop(_series(), 0)["stop"] is None

    def test_none_in_closes(self):
        c = _series()
        c[5] = None
        assert calc_stop(c, 900.0)["stop"] is None

    def test_unavailable_payload_shape(self):
        r = calc_stop([], 90.0)
        for k in ("stop", "hard_floor", "phase_high_base", "vol_base", "binding"):
            assert k in r


class TestTrailing:
    def test_raise_when_formula_is_higher(self):
        c = _series(noise=10)
        base = calc_stop(c, 900.0)["stop"]
        r = check_trailing_stop(c, 900.0, current_stop=base - 100)
        assert r["should_raise"] is True
        assert r["new_stop"] == base
        assert r["raise_amount"] == 100

    def test_never_lowers(self):
        """式の値が現行より下でも切り下げを提案しない。

        株価が下がれば局面高値基準もボラ基準も下がる。機械的に従うと
        損失の許容幅を広げることになり、トレーリングの逆になる。
        """
        c = _series(noise=10)
        base = calc_stop(c, 900.0)["stop"]
        r = check_trailing_stop(c, 900.0, current_stop=base + 500)
        assert r["should_raise"] is False
        assert r["current_stop"] == base + 500
        assert "据え置き" in r["label"]

    def test_equal_is_not_a_raise(self):
        c = _series(noise=10)
        base = calc_stop(c, 900.0)["stop"]
        assert check_trailing_stop(c, 900.0, current_stop=base)["should_raise"] is False

    def test_no_current_stop_is_a_raise(self):
        c = _series(noise=10)
        r = check_trailing_stop(c, 900.0, current_stop=None)
        assert r["should_raise"] is True
        assert "未設定" in r["label"]

    def test_locked_profit_is_relative_to_book(self):
        c = _series(noise=10)
        r = check_trailing_stop(c, 900.0, current_stop=None)
        assert r["locked_profit"] == round(r["new_stop"] - 900.0)

    def test_insufficient_data_does_not_raise(self):
        r = check_trailing_stop([100.0] * 5, 90.0, current_stop=80.0)
        assert r["should_raise"] is False
        assert r["new_stop"] is None


class TestExempt:
    """conviction_override（ストップを置かないと決めた銘柄）を免除する。

    ``current_stop=None`` は「まだ設定していない」と「置かないと決めた」の
    両方で起こる。区別しないと免除銘柄に毎回ストップ設定を促すことになり、
    2026-08-16 の週次で 7453.T 良品計画に実際に「↑可」が出た。
    """

    def test_exempt_never_raises(self):
        c = _series(noise=10)
        r = check_trailing_stop(c, 900.0, current_stop=None, exempt=True)
        assert r["should_raise"] is False
        assert r["exempt"] is True
        assert r["new_stop"] is None
        assert "conviction_override" in r["label"]

    def test_exempt_overrides_existing_stop(self):
        """免除銘柄にたまたま現行ストップが残っていても切り上げない。"""
        c = _series(noise=10)
        assert check_trailing_stop(c, 900.0, current_stop=1.0,
                                   exempt=True)["should_raise"] is False

    def test_not_exempt_by_default(self):
        c = _series(noise=10)
        r = check_trailing_stop(c, 900.0, current_stop=None)
        assert r["exempt"] is False
        assert r["should_raise"] is True

    def test_exempt_with_insufficient_data(self):
        r = check_trailing_stop([100.0] * 5, 90.0, current_stop=None, exempt=True)
        assert r["should_raise"] is False
        assert r["exempt"] is True


class TestSmoothedAnchor:
    """KIK-768: ボラ基準の『現値』を直近3日平均にする（2026-08-19 ユーザー判断）.

    ラチェットは上げるだけなので、毎日の終値ノイズに反応すると上げだけが積み上がり、
    ストップが株価に収束していく。6701.T は 8営業日で 4,091→4,609（+12.7%）まで上がり、
    設計 3.8σ に対し 0.37σ の距離になったところで平常の押しに刈られた。

    ⚠️ 平滑するのは**アンカーだけ**。σ を平滑すると過小評価になり、
    局面高値は「実際につけた値」なので平均する意味がない。
    """

    def test_default_is_three_days(self):
        r = calc_stop(_series(noise=10), book_value=900.0)
        assert r["anchor_smooth"] == 3

    def test_smooth_one_reproduces_the_old_behaviour(self):
        c = _series(noise=10)
        r = calc_stop(c, book_value=900.0, anchor_smooth=1)
        assert r["anchor"] == round(float(c[-1]), 1)
        assert r["anchor_smooth"] == 1

    def test_anchor_is_the_mean_of_the_last_three(self):
        c = _series(noise=10)
        r = calc_stop(c, book_value=900.0)
        assert r["anchor"] == round(sum(c[-3:]) / 3, 1)

    def test_spike_day_no_longer_lifts_the_stop_as_far(self):
        """急騰の天井引けをそのままアンカーにしない（6701.T 8/14 の構図）."""
        c = _series(noise=5)
        c[-1] = c[-1] * 1.05                      # 最終日だけ +5% スパイク
        raw = calc_stop(c, book_value=900.0, anchor_smooth=1)
        sm = calc_stop(c, book_value=900.0, anchor_smooth=3)
        assert sm["vol_base"] < raw["vol_base"]
        assert sm["anchor"] < raw["anchor"]

    def test_sigma_and_phase_high_are_not_smoothed(self):
        c = _series(noise=10)
        raw = calc_stop(c, book_value=900.0, anchor_smooth=1)
        sm = calc_stop(c, book_value=900.0, anchor_smooth=5)
        assert sm["daily_sigma_pct"] == raw["daily_sigma_pct"]
        assert sm["phase_high"] == raw["phase_high"]

    def test_current_price_stays_the_actual_close(self):
        """距離の表示は当日終値ベース。平滑値と混ぜると『今いくらか』が読めない."""
        c = _series(noise=10)
        r = calc_stop(c, book_value=900.0)
        assert r["current_price"] == float(c[-1])
        assert r["anchor"] != r["current_price"]

    def test_smooth_longer_than_series_is_clamped(self):
        c = _series(n=61, noise=5)
        r = calc_stop(c, book_value=900.0, anchor_smooth=999)
        assert r["anchor_smooth"] == len(c)

    def test_trailing_still_refuses_to_lower(self):
        """平滑化しても切り下げは提案しない（KIK-759 の性質を壊さない）."""
        c = _series(noise=10)
        high = calc_stop(c, book_value=900.0)["stop"] * 2
        t = check_trailing_stop(c, 900.0, high)
        assert t["should_raise"] is False
        assert t["new_stop"] < high        # 式の値は下だが、現行を下げはしない

    def test_smoothing_reaches_through_check_trailing_stop(self):
        """kwargs が calc_stop まで届いていること（vol 基準で比べる）."""
        c = _series(noise=5)
        c[-1] = c[-1] * 1.05
        raw = check_trailing_stop(c, 900.0, 100.0, anchor_smooth=1)
        sm = check_trailing_stop(c, 900.0, 100.0, anchor_smooth=3)
        assert sm["vol_base"] < raw["vol_base"]
        assert sm["anchor_smooth"] == 3 and raw["anchor_smooth"] == 1
