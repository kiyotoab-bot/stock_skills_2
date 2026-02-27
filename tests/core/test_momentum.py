"""Tests for detect_momentum_surge() in technicals.py (KIK-506)."""

import numpy as np
import pandas as pd
import pytest

from src.core.screening.technicals import detect_momentum_surge


def _make_hist(prices: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    """Create a minimal hist DataFrame for testing."""
    n = len(prices)
    if volumes is None:
        volumes = [1_000_000.0] * n
    return pd.DataFrame({
        "Close": prices,
        "Volume": volumes,
    })


def _make_uptrend_hist(
    n: int = 300,
    base: float = 100.0,
    daily_return: float = 0.001,
    surge_pct: float = 0.0,
    surge_days: int = 10,
    volume_base: float = 1_000_000.0,
    volume_surge_mult: float = 1.0,
) -> pd.DataFrame:
    """Generate a synthetic uptrend history with optional surge at the end."""
    prices = [base]
    for i in range(1, n):
        prices.append(prices[-1] * (1 + daily_return))

    # Apply surge at the end
    if surge_pct > 0 and surge_days > 0:
        surge_per_day = surge_pct / surge_days
        for i in range(n - surge_days, n):
            prices[i] = prices[i - 1] * (1 + surge_per_day) if i > 0 else prices[i]

    volumes = [volume_base] * n
    # Volume surge in last 5 days
    for i in range(n - 5, n):
        volumes[i] = volume_base * volume_surge_mult

    return pd.DataFrame({"Close": prices, "Volume": volumes})


class TestDetectMomentumSurgeBasic:
    """Basic detect_momentum_surge tests."""

    def test_insufficient_data_returns_none_level(self):
        """With < 50 data points, should return 'none' surge level."""
        hist = _make_hist([100.0] * 30)
        result = detect_momentum_surge(hist)
        assert result["surge_level"] == "none"
        assert result["surge_score"] == 0.0

    def test_flat_prices_return_none(self):
        """Flat prices should produce 'none' surge level."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist)
        assert result["surge_level"] == "none"

    def test_result_keys(self):
        """Result dict should have all expected keys."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist)
        expected_keys = {
            "ma50_deviation", "ma200_deviation", "volume_ratio", "rsi",
            "surge_level", "surge_score", "near_high", "new_high",
        }
        assert set(result.keys()) == expected_keys


class TestSurgeLevelClassification:
    """Test surge level classification based on MA50 deviation."""

    def test_accelerating(self):
        """MA50 deviation +12% should give 'accelerating'."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.12)
        assert result["surge_level"] == "accelerating"

    def test_surging(self):
        """MA50 deviation +20% should give 'surging'."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.20)
        assert result["surge_level"] == "surging"

    def test_overheated(self):
        """MA50 deviation +35% should give 'overheated'."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.35)
        assert result["surge_level"] == "overheated"

    def test_none_level(self):
        """MA50 deviation +3% should give 'none'."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.03)
        assert result["surge_level"] == "none"

    def test_boundary_accelerating(self):
        """MA50 deviation exactly +10% should give 'accelerating'."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.10)
        assert result["surge_level"] == "accelerating"

    def test_boundary_surging(self):
        """MA50 deviation exactly +15% should give 'surging'."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.15)
        assert result["surge_level"] == "surging"

    def test_boundary_overheated(self):
        """MA50 deviation exactly +30% should give 'overheated'."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.30)
        assert result["surge_level"] == "overheated"


class TestSurgeScore:
    """Test surge score component calculation."""

    def test_ma50_deviation_scoring(self):
        """Higher MA50 deviation should yield higher score."""
        hist = _make_hist([100.0] * 100)
        r1 = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.05)
        r2 = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.12)
        r3 = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.25)
        r4 = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.35)
        assert r1["surge_score"] < r2["surge_score"]
        assert r2["surge_score"] < r3["surge_score"]
        assert r3["surge_score"] <= r4["surge_score"]

    def test_near_high_adds_score(self):
        """Being near 52-week high should add to score."""
        hist = _make_hist([100.0] * 100)
        r_far = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.12, fifty_two_week_high_change_pct=-0.20)
        r_near = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.12, fifty_two_week_high_change_pct=-0.03)
        assert r_near["surge_score"] > r_far["surge_score"]

    def test_new_high_scores_higher_than_near(self):
        """New 52-week high should score higher than near high."""
        hist = _make_hist([100.0] * 100)
        r_near = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.12, fifty_two_week_high_change_pct=-0.03)
        r_new = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.12, fifty_two_week_high_change_pct=0.01)
        assert r_new["surge_score"] > r_near["surge_score"]

    def test_score_max_100(self):
        """Surge score should not exceed 100."""
        hist = _make_uptrend_hist(n=300, surge_pct=0.5, surge_days=10, volume_surge_mult=6.0)
        result = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.40, fifty_two_week_high_change_pct=0.05)
        assert result["surge_score"] <= 100.0


class TestPrecomputedValues:
    """Test that precomputed EquityQuery values are used."""

    def test_precomputed_ma50_deviation_used(self):
        """When fifty_day_avg_change_pct is provided, use it directly."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist, fifty_day_avg_change_pct=0.25)
        assert result["ma50_deviation"] == 0.25

    def test_precomputed_52wk_high_change_used(self):
        """When fifty_two_week_high_change_pct is provided, near_high should reflect it."""
        hist = _make_hist([100.0] * 100)
        r1 = detect_momentum_surge(hist, fifty_two_week_high_change_pct=-0.02)
        assert r1["near_high"] is True
        r2 = detect_momentum_surge(hist, fifty_two_week_high_change_pct=-0.10)
        assert r2["near_high"] is False


class TestNearHighNewHigh:
    """Test near_high and new_high flags."""

    def test_near_high_within_5pct(self):
        """Within 5% of 52-week high should set near_high=True."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist, fifty_two_week_high_change_pct=-0.04)
        assert result["near_high"] is True

    def test_not_near_high(self):
        """More than 5% below 52-week high should set near_high=False."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist, fifty_two_week_high_change_pct=-0.10)
        assert result["near_high"] is False

    def test_new_high(self):
        """At or above 52-week high should set new_high=True."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist, fifty_two_week_high_change_pct=0.02)
        assert result["new_high"] is True
        assert result["near_high"] is True

    def test_not_new_high(self):
        """Below 52-week high should set new_high=False."""
        hist = _make_hist([100.0] * 100)
        result = detect_momentum_surge(hist, fifty_two_week_high_change_pct=-0.01)
        assert result["new_high"] is False
        assert result["near_high"] is True  # within 5%


class TestVolumeRatio:
    """Test volume ratio calculation."""

    def test_volume_surge_detected(self):
        """High volume in last 5 days vs 20-day average should show ratio > 1."""
        volumes = [1_000_000.0] * 95 + [3_000_000.0] * 5
        hist = _make_hist([100.0] * 100, volumes)
        result = detect_momentum_surge(hist)
        assert result["volume_ratio"] > 1.0

    def test_flat_volume(self):
        """Flat volume should produce ratio near 1.0."""
        hist = _make_hist([100.0] * 100, [1_000_000.0] * 100)
        result = detect_momentum_surge(hist)
        assert abs(result["volume_ratio"] - 1.0) < 0.01
