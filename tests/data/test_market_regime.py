"""Tests for src/data/market_regime.py."""

from datetime import date, timedelta

import pytest

from src.data.market_regime import (
    align_by_dates,
    calc_nikkei_usd, NIKKEI_USD_THRESHOLDS,
    calc_jp_us_relative, JP_US_THRESHOLDS,
    calc_nt_ratio, NT_THRESHOLDS,
    calc_nikkei_per_signal, NIKKEI_PER_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat(value: float, length: int = 25) -> list[float]:
    return [value] * length


def _trend(start: float, end: float, length: int = 25) -> list[float]:
    step = (end - start) / (length - 1)
    return [start + i * step for i in range(length)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCalcNikkeiUsd:

    def test_rising_nikkei_flat_usdjpy(self):
        """日経+10%、USDJPY横ばい → ドル建て+10% → rising."""
        nikkei = _trend(38000, 41800, 25)   # +10%
        usdjpy = _flat(150.0, 25)
        result = calc_nikkei_usd(nikkei, usdjpy)
        assert result["signal"] == "rising"
        assert result["nikkei_usd_chg_pct"] > NIKKEI_USD_THRESHOLDS["rising"]

    def test_falling_yen_weakens(self):
        """日経横ばい、USDJPY 150→165（円安10%）→ ドル建て-10% → falling."""
        nikkei = _flat(38000, 25)
        usdjpy = _trend(150.0, 165.0, 25)
        result = calc_nikkei_usd(nikkei, usdjpy)
        assert result["signal"] == "falling"
        assert result["nikkei_usd_chg_pct"] < NIKKEI_USD_THRESHOLDS["falling"]

    def test_flat_both_move_equally(self):
        """日経+2%、USDJPY+2% → ドル建てほぼ0% → flat."""
        nikkei = _trend(38000, 38760, 25)   # +2%
        usdjpy = _trend(150.0, 153.0, 25)   # +2%
        result = calc_nikkei_usd(nikkei, usdjpy)
        assert result["signal"] == "flat"
        assert abs(result["nikkei_usd_chg_pct"]) < NIKKEI_USD_THRESHOLDS["rising"]

    def test_yen_strengthens_boosts_usd(self):
        """日経横ばい、USDJPY 150→138（円高8.7%）→ ドル建て上昇 → rising."""
        nikkei = _flat(38000, 25)
        usdjpy = _trend(150.0, 138.0, 25)
        result = calc_nikkei_usd(nikkei, usdjpy)
        assert result["signal"] == "rising"
        assert result["nikkei_usd_chg_pct"] > 0

    def test_latest_value_calculation(self):
        """nikkei_usd_latest = nikkei[-1] / usdjpy[-1]."""
        nikkei = _flat(38000, 25)
        usdjpy = _flat(152.0, 25)
        result = calc_nikkei_usd(nikkei, usdjpy)
        assert result["nikkei_usd_latest"] == pytest.approx(38000 / 152.0, rel=1e-4)

    def test_insufficient_nikkei_data(self):
        result = calc_nikkei_usd([38000] * 10, _flat(150.0, 25))
        assert result["signal"] == "unavailable"

    def test_insufficient_usdjpy_data(self):
        result = calc_nikkei_usd(_flat(38000, 25), [150.0] * 5)
        assert result["signal"] == "unavailable"

    def test_zero_usdjpy_unavailable(self):
        result = calc_nikkei_usd(_flat(38000, 25), [0.0] * 25)
        assert result["signal"] == "unavailable"

    def test_label_contains_usd(self):
        nikkei = _flat(38000, 25)
        usdjpy = _flat(150.0, 25)
        result = calc_nikkei_usd(nikkei, usdjpy)
        assert "USD" in result["label"]

    def test_custom_period(self):
        nikkei = _trend(38000, 40000, 15)
        usdjpy = _flat(150.0, 15)
        result = calc_nikkei_usd(nikkei, usdjpy, period=10)
        assert result["signal"] != "unavailable"


class TestCalcJpUsRelative:

    def test_japan_favorable(self):
        """Nikkei_USD up more than SPX by >= 3% → japan."""
        # Nikkei rises 10%, USDJPY flat → Nikkei_USD +10%
        # SPX rises 5%
        nikkei = _trend(38000, 41800, 25)   # +10%
        usdjpy = _flat(150.0, 25)
        spx = _trend(5000, 5250, 25)        # +5%
        result = calc_jp_us_relative(nikkei, usdjpy, spx)
        assert result["signal"] == "japan"
        assert result["relative_pct"] > JP_US_THRESHOLDS["japan_favorable"]

    def test_us_favorable(self):
        """SPX up more than Nikkei_USD by >= 3% → us."""
        # Nikkei flat, USDJPY flat → Nikkei_USD flat
        # SPX rises 5%
        nikkei = _flat(38000, 25)
        usdjpy = _flat(150.0, 25)
        spx = _trend(5000, 5250, 25)        # +5%
        result = calc_jp_us_relative(nikkei, usdjpy, spx)
        assert result["signal"] == "us"
        assert result["relative_pct"] < JP_US_THRESHOLDS["us_favorable"]

    def test_neutral(self):
        """Both rise similarly → neutral."""
        nikkei = _trend(38000, 39900, 25)   # +5%
        usdjpy = _flat(150.0, 25)
        spx = _trend(5000, 5250, 25)        # +5%
        result = calc_jp_us_relative(nikkei, usdjpy, spx)
        assert result["signal"] == "neutral"
        assert abs(result["relative_pct"]) < JP_US_THRESHOLDS["japan_favorable"]

    def test_yen_weakening_drags_nikkei_usd(self):
        """Nikkei +5% in JPY but yen weakens 10% → Nikkei_USD falls → us signal."""
        # USDJPY goes from 150 → 165 (yen -10%)
        # Nikkei +5% in JPY
        nikkei = _trend(38000, 39900, 25)   # +5% JPY
        usdjpy = _trend(150.0, 165.0, 25)   # yen -10%
        spx = _trend(5000, 5250, 25)        # +5%
        result = calc_jp_us_relative(nikkei, usdjpy, spx)
        # Nikkei_USD ≈ +5% / (1+10%) - 1 ≈ -4.5% → relative ≈ -9.5% → us
        assert result["signal"] == "us"
        assert result["nikkei_usd_chg_pct"] is not None
        assert result["nikkei_usd_chg_pct"] < 0

    def test_yen_strengthening_boosts_nikkei_usd(self):
        """Nikkei flat in JPY but yen strengthens 8% → Nikkei_USD rises → japan signal."""
        # USDJPY 150 → 138 (yen +8.7%)
        # Nikkei flat in JPY
        nikkei = _flat(38000, 25)
        usdjpy = _trend(150.0, 138.0, 25)   # yen stronger
        spx = _flat(5000, 25)               # SPX flat
        result = calc_jp_us_relative(nikkei, usdjpy, spx)
        # Nikkei_USD = 38000 / 138 vs 38000 / 150 → ≈ +8.7%
        assert result["signal"] == "japan"
        assert result["nikkei_usd_chg_pct"] > 0

    def test_returns_nikkei_usd_latest(self):
        nikkei = _flat(38000, 25)
        usdjpy = _flat(152.0, 25)
        spx = _flat(5000, 25)
        result = calc_jp_us_relative(nikkei, usdjpy, spx)
        expected = 38000 / 152.0
        assert result["nikkei_usd_latest"] == pytest.approx(expected, rel=1e-4)

    def test_insufficient_nikkei_data(self):
        result = calc_jp_us_relative([38000] * 10, _flat(150, 25), _flat(5000, 25))
        assert result["signal"] == "unavailable"

    def test_insufficient_usdjpy_data(self):
        result = calc_jp_us_relative(_flat(38000, 25), [150] * 5, _flat(5000, 25))
        assert result["signal"] == "unavailable"

    def test_insufficient_spx_data(self):
        result = calc_jp_us_relative(_flat(38000, 25), _flat(150, 25), [5000] * 10)
        assert result["signal"] == "unavailable"

    def test_zero_usdjpy_returns_unavailable(self):
        nikkei = _flat(38000, 25)
        usdjpy = [0.0] * 25
        spx = _flat(5000, 25)
        result = calc_jp_us_relative(nikkei, usdjpy, spx)
        assert result["signal"] == "unavailable"

    def test_label_contains_pct(self):
        nikkei = _trend(38000, 41800, 25)
        usdjpy = _flat(150.0, 25)
        spx = _trend(5000, 5250, 25)
        result = calc_jp_us_relative(nikkei, usdjpy, spx)
        assert "%" in result["label"]
        assert result["label"] != "データ不足"

    def test_custom_period(self):
        """period=10 uses 10-day lookback."""
        nikkei = _trend(38000, 40000, 15)
        usdjpy = _flat(150.0, 15)
        spx = _flat(5000, 15)
        result = calc_jp_us_relative(nikkei, usdjpy, spx, period=10)
        assert result["signal"] != "unavailable"


# ---------------------------------------------------------------------------
# Tests: calc_nt_ratio
# ---------------------------------------------------------------------------

class TestCalcNtRatio:

    def test_neutral(self):
        """14.0倍 → neutral."""
        result = calc_nt_ratio(42000, 3000)   # 14.0
        assert result["signal"] == "neutral"
        assert result["nt_ratio"] == pytest.approx(14.0, rel=1e-4)

    def test_nikkei_heavy(self):
        """15.79倍（≥15.5）→ nikkei_heavy."""
        result = calc_nt_ratio(60000, 3800)   # 15.789...
        assert result["signal"] == "nikkei_heavy"
        assert result["nt_ratio"] > NT_THRESHOLDS["nikkei_heavy"]

    def test_nikkei_heavy_boundary(self):
        """ちょうど15.5倍 → nikkei_heavy（下限を含む）."""
        result = calc_nt_ratio(46500, 3000)   # 15.5
        assert result["signal"] == "nikkei_heavy"

    def test_topix_heavy(self):
        """12.0倍（<13.0）→ topix_heavy."""
        result = calc_nt_ratio(36000, 3000)   # 12.0
        assert result["signal"] == "topix_heavy"
        assert result["nt_ratio"] < NT_THRESHOLDS["topix_heavy"]

    def test_topix_heavy_boundary(self):
        """ちょうど13.0倍 → neutral（13.0は正常レンジに含む）."""
        result = calc_nt_ratio(39000, 3000)   # 13.0
        assert result["signal"] == "neutral"

    def test_zero_topix_unavailable(self):
        result = calc_nt_ratio(40000, 0)
        assert result["signal"] == "unavailable"

    def test_none_topix_unavailable(self):
        result = calc_nt_ratio(40000, None)
        assert result["signal"] == "unavailable"

    def test_zero_nikkei_unavailable(self):
        result = calc_nt_ratio(0, 3000)
        assert result["signal"] == "unavailable"

    def test_label_contains_ratio(self):
        result = calc_nt_ratio(60537, 3735)   # ≈16.21倍
        assert "倍" in result["label"]
        assert result["signal"] == "nikkei_heavy"

    def test_label_unavailable(self):
        result = calc_nt_ratio(0, 0)
        assert result["label"] == "データ不足"


# ---------------------------------------------------------------------------
# Tests: calc_nikkei_per_signal
# ---------------------------------------------------------------------------

class TestCalcNikkeiPerSignal:

    def test_normal(self):
        """16倍 → 正常レンジ（13〜20倍）."""
        result = calc_nikkei_per_signal(16.0)
        assert result["signal"] == "normal"
        assert result["per"] == 16.0

    def test_overvalued(self):
        """20.5倍（≥20倍）→ overvalued."""
        result = calc_nikkei_per_signal(20.5)
        assert result["signal"] == "overvalued"

    def test_overvalued_boundary(self):
        """ちょうど20.0倍 → overvalued（境界は割高側に含む）."""
        result = calc_nikkei_per_signal(20.0)
        assert result["signal"] == "overvalued"

    def test_bubble(self):
        """26倍（≥25倍）→ bubble."""
        result = calc_nikkei_per_signal(26.0)
        assert result["signal"] == "bubble"

    def test_bubble_boundary(self):
        """ちょうど25.0倍 → bubble."""
        result = calc_nikkei_per_signal(25.0)
        assert result["signal"] == "bubble"

    def test_bubble_excludes_overvalued(self):
        """bubble シグナルのとき overvalued ではない（elif で除外）."""
        result = calc_nikkei_per_signal(27.0)
        assert result["signal"] == "bubble"
        assert result["signal"] != "overvalued"

    def test_cheap(self):
        """12.0倍（≤13倍）→ cheap."""
        result = calc_nikkei_per_signal(12.0)
        assert result["signal"] == "cheap"

    def test_cheap_boundary(self):
        """ちょうど13.0倍 → cheap（境界は割安側に含む）."""
        result = calc_nikkei_per_signal(13.0)
        assert result["signal"] == "cheap"

    def test_normal_upper_boundary(self):
        """19.9倍 → normal（20倍未満は正常）."""
        result = calc_nikkei_per_signal(19.9)
        assert result["signal"] == "normal"

    def test_none_unavailable(self):
        result = calc_nikkei_per_signal(None)
        assert result["signal"] == "unavailable"

    def test_zero_unavailable(self):
        result = calc_nikkei_per_signal(0)
        assert result["signal"] == "unavailable"

    def test_negative_unavailable(self):
        result = calc_nikkei_per_signal(-5.0)
        assert result["signal"] == "unavailable"

    def test_label_contains_per_value(self):
        result = calc_nikkei_per_signal(20.5)
        assert "20.5" in result["label"]
        assert "倍" in result["label"]

    def test_label_unavailable(self):
        result = calc_nikkei_per_signal(None)
        assert result["label"] == "データ不足"


# ---------------------------------------------------------------------------
# Date alignment (KIK-727)
# ---------------------------------------------------------------------------


def _days(n: int, start: date = date(2026, 1, 5)) -> list[date]:
    """n 営業日ぶんの連続日付（土日は考慮しない単純連番）。"""
    return [start + timedelta(days=i) for i in range(n)]


class TestAlignByDates:
    def test_intersection_only(self):
        d1 = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
        d2 = [date(2026, 1, 5), date(2026, 1, 7), date(2026, 1, 8)]
        dates, vals = align_by_dates([(d1, [1.0, 2.0, 3.0]), (d2, [10.0, 30.0, 40.0])])
        assert dates == ["2026-01-05", "2026-01-07"]
        assert vals == [[1.0, 3.0], [10.0, 30.0]]

    def test_empty_input(self):
        assert align_by_dates([]) == ([], [])

    def test_no_common_dates(self):
        dates, vals = align_by_dates(
            [([date(2026, 1, 5)], [1.0]), ([date(2026, 1, 6)], [2.0])]
        )
        assert dates == []

    def test_string_dates(self):
        dates, vals = align_by_dates(
            [(["2026-01-05", "2026-01-06"], [1.0, 2.0]),
             (["2026-01-06", "2026-01-07"], [20.0, 30.0])]
        )
        assert dates == ["2026-01-06"]
        assert vals == [[2.0], [20.0]]


class TestNikkeiUsdAlignment:
    def test_holiday_gap_changes_result(self):
        """USDJPY に日経の休場日が混ざると位置合わせは誤った基準日を使う。"""
        nk_dates = _days(25)
        nikkei = [40000.0 + i * 100 for i in range(25)]
        # USDJPY は日経が休んだ日を含む＝5日多い
        fx_dates = _days(30)
        usdjpy = [150.0] * 25 + [160.0] * 5  # 後半で急激な円安

        misaligned = calc_nikkei_usd(nikkei, usdjpy)
        aligned = calc_nikkei_usd(
            nikkei, usdjpy, nikkei_dates=nk_dates, usdjpy_dates=fx_dates
        )
        assert misaligned["aligned"] is False
        assert aligned["aligned"] is True
        # 位置合わせでは末尾5本が別日の 160.0 とペアになり値が壊れる
        assert misaligned["nikkei_usd_chg_pct"] != aligned["nikkei_usd_chg_pct"]

    def test_aligned_uses_matching_dates(self):
        d = _days(25)
        nikkei = [40000.0 + i * 100 for i in range(25)]
        usdjpy = [150.0] * 25
        r = calc_nikkei_usd(nikkei, usdjpy, nikkei_dates=d, usdjpy_dates=d)
        assert r["aligned"] is True
        assert r["as_of"] == d[-1].isoformat()
        # 全期間 150 固定なので日経の変化率と一致する
        expected = (nikkei[-1] - nikkei[-21]) / nikkei[-21] * 100
        assert r["nikkei_usd_chg_pct"] == pytest.approx(round(expected, 2))

    def test_backward_compatible_without_dates(self):
        r = calc_nikkei_usd(_trend(40000, 44000), _flat(150))
        assert r["aligned"] is False
        assert r["as_of"] is None
        assert r["signal"] in ("rising", "falling", "flat")

    def test_partial_dates_falls_back(self):
        d = _days(25)
        r = calc_nikkei_usd(_trend(40000, 44000), _flat(150), nikkei_dates=d)
        assert r["aligned"] is False

    def test_insufficient_overlap_returns_na(self):
        d1 = _days(25)
        d2 = _days(25, start=date(2027, 1, 5))  # 重なりゼロ
        r = calc_nikkei_usd(
            _flat(40000), _flat(150), nikkei_dates=d1, usdjpy_dates=d2
        )
        assert r["signal"] == "unavailable"


class TestJpUsAlignment:
    def test_stale_spx_changes_result(self):
        """米国市場が未終了で S&P500 だけ前営業日、という実運用ケース。"""
        nk_dates = _days(25)
        spx_dates = _days(24)  # 最新日が1日古い
        nikkei = [40000.0 + i * 100 for i in range(25)]
        usdjpy = [150.0] * 25
        spx = [7000.0 + i * 30 for i in range(24)]

        misaligned = calc_jp_us_relative(nikkei, usdjpy, spx)
        aligned = calc_jp_us_relative(
            nikkei, usdjpy, spx,
            nikkei_dates=nk_dates, usdjpy_dates=nk_dates, spx_dates=spx_dates,
        )
        assert misaligned["aligned"] is False
        assert aligned["aligned"] is True
        assert aligned["as_of"] == spx_dates[-1].isoformat()
        # 整合後は共通日付が24本になり、基準日が変わるので値が変わる
        assert misaligned["relative_pct"] != aligned["relative_pct"]

    def test_backward_compatible_without_dates(self):
        r = calc_jp_us_relative(_trend(40000, 44000), _flat(150), _trend(7000, 7100))
        assert r["aligned"] is False
        assert r["signal"] in ("japan", "us", "neutral")


class TestAlignmentExpectedValues:
    """整合後の値を式で固定する（KIK-727 レビュー M3）。

    `!=` だけでは「変わったこと」しか言えず、整合後の値が正しいかを
    保証できない。共通日付から基準 index を決めて期待値を算出する。
    """

    def test_stale_spx_uses_common_last_date(self):
        nk_dates, spx_dates = _days(25), _days(24)
        nikkei = [40000.0 + i * 100 for i in range(25)]
        usdjpy = [150.0] * 25
        spx = [7000.0 + i * 30 for i in range(24)]

        r = calc_jp_us_relative(
            nikkei, usdjpy, spx,
            nikkei_dates=nk_dates, usdjpy_dates=nk_dates, spx_dates=spx_dates,
        )
        # 共通日付は 24 本。最新は index 23、基準は index 3。
        exp_nk = (nikkei[23] / 150 - nikkei[3] / 150) / (nikkei[3] / 150) * 100
        exp_spx = (spx[23] - spx[3]) / spx[3] * 100
        assert r["as_of"] == spx_dates[-1].isoformat()
        assert r["nikkei_usd_chg_pct"] == pytest.approx(round(exp_nk, 2))
        assert r["spx_chg_pct"] == pytest.approx(round(exp_spx, 2))
        assert r["relative_pct"] == pytest.approx(round(exp_nk - exp_spx, 2))

    def test_alignment_can_flip_signal(self):
        """ずれが判断（signal）を変えることを示す。"""
        nk_dates = _days(25)
        # USDJPY は日経の休場日を5日含む＝末尾5本が別日とペアになる
        fx_dates = _days(30)
        nikkei = [40000.0] * 25
        usdjpy = [150.0] * 25 + [130.0] * 5  # 後半で急激な円高

        mis = calc_nikkei_usd(nikkei, usdjpy)
        ali = calc_nikkei_usd(
            nikkei, usdjpy, nikkei_dates=nk_dates, usdjpy_dates=fx_dates
        )
        assert mis["signal"] == "rising"   # 円高分を誤って取り込む
        assert ali["signal"] == "flat"     # 日経も為替も動いていない
        assert ali["nikkei_usd_chg_pct"] == pytest.approx(0.0)

    def test_holiday_gap_as_of_is_common_last_date(self):
        nk_dates, fx_dates = _days(25), _days(30)
        r = calc_nikkei_usd(
            [40000.0 + i * 100 for i in range(25)],
            [150.0] * 30,
            nikkei_dates=nk_dates, usdjpy_dates=fx_dates,
        )
        assert r["as_of"] == nk_dates[-1].isoformat()


class TestAlignmentBoundaries:
    """min_len の二段チェック（KIK-727 レビュー M1）。

    「生の長さは足りるが整合後に不足」というケースが要。片側の判定だけを
    消しても通ってしまう状態を防ぐ。
    """

    def test_overlap_exactly_min_len_ok(self):
        d1, d2 = _days(25), _days(25, start=date(2026, 1, 9))  # overlap = 21
        r = calc_nikkei_usd(_trend(40000, 44000), _flat(150),
                            nikkei_dates=d1, usdjpy_dates=d2)
        assert r["aligned"] is True
        assert r["signal"] != "unavailable"

    def test_overlap_one_short_returns_na(self):
        d1, d2 = _days(25), _days(25, start=date(2026, 1, 10))  # overlap = 20
        r = calc_nikkei_usd(_trend(40000, 44000), _flat(150),
                            nikkei_dates=d1, usdjpy_dates=d2)
        assert r["signal"] == "unavailable"
        # 「日付を渡したが重なり不足」と「日付未指定」を区別できること
        assert r["aligned"] is True

    def test_no_dates_reports_aligned_false_on_na(self):
        r = calc_nikkei_usd([1.0] * 25, [1.0] * 25, period=30)
        assert r["signal"] == "unavailable"
        assert r["aligned"] is False


class TestAlignByDatesEdgeCases:
    def test_tz_aware_timestamps_from_different_exchanges(self):
        """tz が違う Timestamp でも同じ暦日なら突き合わせる。

        get_price_history は yfinance の tz-aware index をそのまま返すため、
        df.index.tolist() を渡すのが最も自然な使い方。正規化しないと
        ^N225(Asia/Tokyo) と ^GSPC(America/New_York) の積集合が空になり、
        例外も警告もなく「データ不足」に落ちる。
        """
        pd = pytest.importorskip("pandas")
        jp = [pd.Timestamp("2026-01-05", tz="Asia/Tokyo"),
              pd.Timestamp("2026-01-06", tz="Asia/Tokyo")]
        us = [pd.Timestamp("2026-01-05", tz="America/New_York"),
              pd.Timestamp("2026-01-06", tz="America/New_York")]
        dates, vals = align_by_dates([(jp, [1.0, 2.0]), (us, [10.0, 20.0])])
        assert dates == ["2026-01-05", "2026-01-06"]
        assert vals == [[1.0, 2.0], [10.0, 20.0]]

    def test_naive_and_aware_mix(self):
        pd = pytest.importorskip("pandas")
        a = [pd.Timestamp("2026-01-05", tz="Asia/Tokyo")]
        b = [date(2026, 1, 5)]
        dates, vals = align_by_dates([(a, [1.0]), (b, [2.0])])
        assert dates == ["2026-01-05"]
        assert vals == [[1.0], [2.0]]

    def test_mismatched_lengths_keep_tail(self):
        """長さが違うときは先頭ではなく末尾を残す（latest-last 規約）。"""
        d = _days(5)
        # 値が3本しかない = 直近3日分とみなす
        dates, vals = align_by_dates([(d, [30.0, 40.0, 50.0]), (d, [1., 2., 3., 4., 5.])])
        assert dates == [x.isoformat() for x in d[-3:]]
        assert vals[0] == [30.0, 40.0, 50.0]
        assert vals[1] == [3.0, 4.0, 5.0]

    def test_duplicate_dates_last_wins(self):
        dates, vals = align_by_dates([
            ([date(2026, 1, 5), date(2026, 1, 5), date(2026, 1, 6)], [1.0, 9.0, 2.0]),
            ([date(2026, 1, 5), date(2026, 1, 6)], [10.0, 20.0]),
        ])
        assert dates == ["2026-01-05", "2026-01-06"]
        assert vals[0] == [9.0, 2.0]

    def test_empty_date_list_falls_back(self):
        """dates=[] は None と同じくフォールバックさせる。"""
        r = calc_nikkei_usd(_trend(40000, 44000), _flat(150),
                            nikkei_dates=[], usdjpy_dates=[])
        assert r["aligned"] is False
        assert r["signal"] != "unavailable"
