"""Tests for src/data/band_walk.py."""

import pytest

from src.data.band_walk import (
    detect_band_walk_end,
    _ema,
    _macd_dead_cross,
    _parabolic_sar,
    _bands,
    CONSOLIDATION_MIN_BARS,
    MACD_WARMUP,
    MIN_BARS,
)


# ---------------------------------------------------------------------------
# Helpers — 合成系列でバンドウォークの各局面を作る
# ---------------------------------------------------------------------------

def _noisy_flat(value: float = 100.0, length: int = 60) -> list[float]:
    """σ が 0 にならない程度の微小変動を持つ横ばい系列。"""
    return [value + (1.0 if i % 2 else -1.0) for i in range(length)]


def _walk_up(base: list[float], bars: int = 8, step: float = 6.0) -> list[float]:
    """+2σ を明確に上抜けて歩き続ける区間（加速上昇）。"""
    out = list(base)
    for i in range(bars):
        out.append(out[-1] + step + i)
    return out


def _pullback(base: list[float], bars: int, ratio: float = 0.90,
              drift: float = -0.5) -> list[float]:
    """バンド内に落ちてから、中央線より上でほぼ横ばい（日柄調整）。"""
    out = list(base)
    level = out[-1] * ratio
    for k in range(bars):
        out.append(level + drift * k)
    return out


def _decline(base: list[float], bars: int, step: float = 6.0) -> list[float]:
    out = list(base)
    for _ in range(bars):
        out.append(out[-1] - step)
    return out


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

class TestGuards:
    def test_empty(self):
        assert detect_band_walk_end([])["signal"] == "unavailable"

    def test_too_short(self):
        assert detect_band_walk_end([100.0] * (MIN_BARS - 1))["signal"] == "unavailable"

    def test_none_in_closes(self):
        closes = _noisy_flat()
        closes[5] = None
        assert detect_band_walk_end(closes)["signal"] == "unavailable"

    def test_non_positive_close(self):
        closes = _noisy_flat()
        closes[5] = 0
        assert detect_band_walk_end(closes)["signal"] == "unavailable"

    def test_unavailable_payload_shape(self):
        r = detect_band_walk_end([])
        assert r["stage"] == 0
        assert r["bars_since_detach"] is None
        assert set(r["stages"]) == {
            "detach", "consolidation", "indicators", "reversion"
        }
        assert not any(r["stages"].values())

    def test_perfectly_flat_is_not_a_band_walk(self):
        """σ=0 でバンドが潰れても「+2σ到達」と誤判定しない。"""
        r = detect_band_walk_end([100.0] * 80)
        assert r["signal"] == "none"
        assert r["in_band_walk"] is False

    def test_mismatched_highs_lows_fall_back_to_closes(self):
        closes = _walk_up(_noisy_flat())
        r = detect_band_walk_end(closes, highs=[1.0, 2.0], lows=[0.5])
        assert r["signal"] != "unavailable"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

class TestDetection:
    def test_no_band_walk_on_sideways(self):
        r = detect_band_walk_end(_noisy_flat(length=80))
        assert r["signal"] == "none"
        assert r["stage"] == 0

    def test_ongoing_band_walk(self):
        r = detect_band_walk_end(_walk_up(_noisy_flat()))
        assert r["in_band_walk"] is True
        assert r["signal"] == "band_walk"
        assert r["stage"] == 0

    def test_detach_only_is_stage1(self):
        """剥離直後（日柄調整の本数に満たない）は 1/4 工程。"""
        r = detect_band_walk_end(_pullback(_walk_up(_noisy_flat()), bars=1))
        assert r["signal"] == "ending"
        assert r["stage"] == 1
        assert r["stages"]["detach"] is True
        assert r["stages"]["consolidation"] is False
        assert r["bars_since_detach"] == 0

    def test_consolidation_reaches_stage2(self):
        """中央線を割らず横ばいが規定本数続くと工程2まで進む。"""
        r = detect_band_walk_end(
            _pullback(_walk_up(_noisy_flat()), bars=CONSOLIDATION_MIN_BARS + 1)
        )
        assert r["stages"]["consolidation"] is True
        assert r["stage"] == 2
        assert r["bars_since_detach"] >= CONSOLIDATION_MIN_BARS

    def test_full_sequence_ends(self):
        """剥離 → 日柄調整 → 指標転換 → 中央線まで戻ると 4/4 で ended。"""
        closes = _decline(_pullback(_walk_up(_noisy_flat()), bars=4), bars=10)
        r = detect_band_walk_end(closes)
        assert r["stages"] == {
            "detach": True,
            "consolidation": True,
            "indicators": True,
            "reversion": True,
        }
        assert r["stage"] == 4
        assert r["signal"] == "ended"
        assert "4/4" in r["label"]

    def test_order_matters_skipping_consolidation_caps_stage(self):
        """日柄調整を挟まず直落した場合、後続工程が揃っても stage は 1 で止まる。"""
        r = detect_band_walk_end(_decline(_walk_up(_noisy_flat()), bars=12))
        assert r["stages"]["reversion"] is True
        assert r["stages"]["indicators"] is True
        assert r["stages"]["consolidation"] is False
        assert r["stage"] == 1
        assert r["signal"] == "ending"

    def test_straight_decline_is_not_consolidation(self):
        """一定ペースの下落は「横ばい」ではない（レンジ%の閾値で弾く）。"""
        r = detect_band_walk_end(_decline(_walk_up(_noisy_flat()), bars=5))
        assert r["stages"]["consolidation"] is False

    def test_bars_since_detach_counts_up(self):
        base = _walk_up(_noisy_flat())
        r1 = detect_band_walk_end(_pullback(base, bars=1))
        r4 = detect_band_walk_end(_pullback(base, bars=4))
        assert r4["bars_since_detach"] > r1["bars_since_detach"]

    def test_lookback_limits_search(self):
        """古いバンドウォークは lookback の外なら拾わない。"""
        closes = _pullback(_walk_up(_noisy_flat()), bars=30)
        assert detect_band_walk_end(closes, lookback=5)["signal"] == "none"
        assert detect_band_walk_end(closes, lookback=60)["signal"] != "none"

    def test_window_parameter_is_honoured(self):
        closes = _walk_up(_noisy_flat(length=80))
        assert detect_band_walk_end(closes, window=20)["signal"] != "unavailable"
        assert detect_band_walk_end(closes, window=25)["signal"] != "unavailable"

    def test_wider_sigma_is_harder_to_touch(self):
        """σ を広げると +σ 到達が起きにくくなる。"""
        closes = _walk_up(_noisy_flat(length=80), bars=4, step=3.0)
        assert detect_band_walk_end(closes, sigma=1.0)["signal"] != "none"
        assert detect_band_walk_end(closes, sigma=6.0)["signal"] == "none"


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------

class TestIndicators:
    def test_ema_shorter_than_period(self):
        assert _ema([1.0, 2.0], 5) == [None, None]

    def test_ema_flat_series_equals_value(self):
        out = _ema([10.0] * 20, 5)
        assert out[4] == pytest.approx(10.0)
        assert out[-1] == pytest.approx(10.0)

    def test_bands_zero_sigma_window_is_none(self):
        mid, upper = _bands([100.0] * 30, window=25, sigma=2.0)
        assert mid[-1] == pytest.approx(100.0)
        assert upper[-1] is None

    def test_bands_upper_above_mid(self):
        mid, upper = _bands(_noisy_flat(length=30), window=25, sigma=2.0)
        assert upper[-1] > mid[-1]

    def test_macd_dead_cross_on_reversal(self):
        """横ばい → 上昇 → 下落 の転換でデッドクロスを拾う。"""
        flat = _noisy_flat(length=40)
        up = [flat[-1] + i * 4 for i in range(1, 26)]
        down = [up[-1] - i * 4 for i in range(1, 21)]
        assert _macd_dead_cross(flat + up + down, since=len(flat) + len(up)) is True

    def test_macd_no_dead_cross_on_pure_uptrend(self):
        """一本調子の上昇でデッドクロスを出さない（シード過渡現象を除外する）。"""
        assert _macd_dead_cross([100.0 + i * 2 for i in range(80)], since=30) is False

    def test_macd_ignores_warmup_region(self):
        """ウォームアップ内のクロスは since を 0 にしても拾わない。"""
        assert _macd_dead_cross([100.0 + i * 2 for i in range(80)], since=0) is False

    def test_macd_insufficient_data(self):
        assert _macd_dead_cross([100.0] * 10, since=0) is False

    def test_macd_warmup_is_beyond_slow_period(self):
        assert MACD_WARMUP > 26

    def test_sar_too_short(self):
        assert _parabolic_sar([1.0, 2.0], [0.5, 1.5]) == [None, None]

    def test_sar_flips_above_price_after_downtrend(self):
        highs = [100.0 + i for i in range(20)] + [120.0 - i * 3 for i in range(20)]
        lows = [h - 2 for h in highs]
        sar = _parabolic_sar(highs, lows)
        closes = [(h + low) / 2 for h, low in zip(highs, lows)]
        assert sar[-1] > closes[-1]

    def test_sar_below_price_during_uptrend(self):
        highs = [100.0 + i * 2 for i in range(40)]
        lows = [h - 2 for h in highs]
        sar = _parabolic_sar(highs, lows)
        closes = [(h + low) / 2 for h, low in zip(highs, lows)]
        assert sar[-1] < closes[-1]
