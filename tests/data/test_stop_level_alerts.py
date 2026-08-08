"""Tests for stop-loss level extraction and stop alerts (KIK-728).

Until KIK-728, ``detect_alerts`` ignored the ``stop_loss`` recorded in notes
entirely, so stop monitoring was fully manual.
"""

import json

import numpy as np
import pytest

from src.data.morning_summary import detect_alerts, _daily_sigma
from src.data.note_manager import get_stop_levels


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(tmp_path, fname, note):
    (tmp_path / fname).write_text(
        json.dumps([note], ensure_ascii=False), encoding="utf-8"
    )


def _series(base: float, sigma: float, n: int = 120, seed: int = 0) -> list[float]:
    """Deterministic price series with a target daily log-return sigma."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, sigma, n)
    return list(base * np.exp(np.cumsum(rets)))


# ---------------------------------------------------------------------------
# get_stop_levels
# ---------------------------------------------------------------------------

class TestGetStopLevels:
    def test_picks_latest_note_per_symbol(self, tmp_path):
        _write(tmp_path, "a.json", {
            "symbol": "6701.T", "type": "exit-rule", "date": "2026-08-03",
            "timestamp": "2026-08-03T20:00:00", "stop_loss": "4212",
        })
        _write(tmp_path, "b.json", {
            "symbol": "6701.T", "type": "exit-rule", "date": "2026-08-04",
            "timestamp": "2026-08-04T18:00:00", "stop_loss": "4091",
        })
        got = get_stop_levels(base_dir=str(tmp_path))
        assert got["6701.T"]["stop"] == 4091.0

    def test_same_date_broken_by_timestamp(self, tmp_path):
        """load_notes sorts by date only; same-day revisions must use timestamp."""
        _write(tmp_path, "a.json", {
            "symbol": "8031.T", "type": "exit-rule", "date": "2026-08-04",
            "timestamp": "2026-08-04T09:00:00", "stop_loss": "4651",
        })
        _write(tmp_path, "b.json", {
            "symbol": "8031.T", "type": "exit-rule", "date": "2026-08-04",
            "timestamp": "2026-08-04T19:00:00", "stop_loss": "4497",
        })
        got = get_stop_levels(base_dir=str(tmp_path))
        assert got["8031.T"]["stop"] == 4497.0

    def test_conviction_override_revokes_older_stop(self, tmp_path):
        """7453.T: a newer conviction thesis must not resurrect an old stop."""
        _write(tmp_path, "a.json", {
            "symbol": "7453.T", "type": "exit-rule", "date": "2026-07-03",
            "timestamp": "2026-07-03T10:00:00", "stop_loss": "3282",
        })
        _write(tmp_path, "b.json", {
            "symbol": "7453.T", "type": "thesis", "date": "2026-08-03",
            "timestamp": "2026-08-03T23:00:00", "conviction_override": True,
        })
        got = get_stop_levels(base_dir=str(tmp_path))
        assert got["7453.T"]["conviction"] is True
        assert got["7453.T"]["stop"] is None

    def test_older_conviction_does_not_revoke_newer_stop(self, tmp_path):
        _write(tmp_path, "a.json", {
            "symbol": "X.T", "type": "thesis", "date": "2026-01-01",
            "timestamp": "2026-01-01T10:00:00", "conviction_override": True,
        })
        _write(tmp_path, "b.json", {
            "symbol": "X.T", "type": "exit-rule", "date": "2026-08-04",
            "timestamp": "2026-08-04T10:00:00", "stop_loss": "500",
        })
        got = get_stop_levels(base_dir=str(tmp_path))
        assert got["X.T"]["conviction"] is False
        assert got["X.T"]["stop"] == 500.0

    def test_freetext_stop_returned_as_none_not_dropped(self, tmp_path):
        """Legacy free-text stops must surface, not vanish from monitoring."""
        _write(tmp_path, "a.json", {
            "symbol": "9364.T", "type": "exit-rule", "date": "2026-07-15",
            "timestamp": "2026-07-15T10:00:00",
            "stop_loss": "終値ベース トレーリング 5063(高値更新で切り上がる)",
        })
        got = get_stop_levels(base_dir=str(tmp_path))
        assert "9364.T" in got
        assert got["9364.T"]["stop"] is None
        assert "5063" in got["9364.T"]["raw"]

    def test_notes_without_stop_loss_ignored(self, tmp_path):
        _write(tmp_path, "a.json", {
            "symbol": "A.T", "type": "exit-rule", "date": "2026-08-01",
            "timestamp": "2026-08-01T10:00:00",
        })
        assert get_stop_levels(base_dir=str(tmp_path)) == {}

    def test_empty_dir(self, tmp_path):
        assert get_stop_levels(base_dir=str(tmp_path)) == {}


# ---------------------------------------------------------------------------
# _daily_sigma
# ---------------------------------------------------------------------------

class TestDailySigma:
    def test_recovers_known_sigma(self):
        closes = _series(1000.0, 0.02, n=200, seed=1)
        sd = _daily_sigma(closes)
        assert sd is not None
        assert 0.015 < sd < 0.026

    def test_too_short_returns_none(self):
        assert _daily_sigma([100.0] * 10) is None

    def test_flat_series_returns_none(self):
        assert _daily_sigma([100.0] * 100) is None

    def test_non_positive_prices_return_none(self):
        assert _daily_sigma([100.0] * 60 + [0.0]) is None


# ---------------------------------------------------------------------------
# detect_alerts — stop integration
# ---------------------------------------------------------------------------

class TestStopAlerts:
    positions = [{"symbol": "A.T", "cost_price": 1000.0}]

    def _run(self, price, stop, sigma=0.02, conviction=False, raw="x"):
        closes = _series(price, sigma, n=150, seed=3)
        closes[-1] = price
        return detect_alerts(
            self.positions,
            {"A.T": {"price": price}},
            {"A.T": closes},
            stop_levels={"A.T": {
                "stop": stop, "raw": raw, "conviction": conviction,
            }},
        )

    def test_price_below_stop_is_critical(self):
        types = {a["type"]: a for a in self._run(950.0, 1000.0)}
        assert types["stop_hit"]["severity"] == "CRITICAL"

    def test_price_equal_to_stop_is_hit(self):
        assert "stop_hit" in {a["type"] for a in self._run(1000.0, 1000.0)}

    def test_within_one_sigma_is_noise_zone_warn(self):
        # sigma=2%/day; stop 1% below price -> 0.5 sigma
        types = {a["type"]: a for a in self._run(1000.0, 990.0, sigma=0.02)}
        assert types["stop_noise_zone"]["severity"] == "WARN"

    def test_between_one_and_two_sigma_is_info(self):
        # stop 3% below price with sigma=2% -> 1.5 sigma
        types = {a["type"]: a for a in self._run(1000.0, 970.0, sigma=0.02)}
        assert types["stop_near"]["severity"] == "INFO"

    def test_far_stop_produces_no_stop_alert(self):
        # stop 20% below price with sigma=2% -> 10 sigma
        got = {a["type"] for a in self._run(1000.0, 800.0, sigma=0.02)}
        assert not got & {"stop_hit", "stop_noise_zone", "stop_near"}

    def test_same_percent_differs_by_volatility(self):
        """The whole point of sigma units: the same -3% classifies differently.

        A percent-based rule would flag both identically; in sigma units the
        calm name is a safe 3.0 sigma away while the volatile one sits inside
        a single day's noise.
        """
        stop_types = {"stop_hit", "stop_noise_zone", "stop_near"}
        calm = {a["type"] for a in self._run(1000.0, 970.0, sigma=0.01)}
        wild = {a["type"] for a in self._run(1000.0, 970.0, sigma=0.032)}
        assert not calm & stop_types        # 3.0 sigma -> beyond alert range
        assert "stop_noise_zone" in wild    # 0.94 sigma -> noise

    def test_conviction_symbol_never_alerts(self):
        got = {a["type"] for a in self._run(500.0, 1000.0, conviction=True)}
        assert not got & {"stop_hit", "stop_noise_zone", "stop_near", "stop_unparsed"}

    def test_unparsed_stop_raises_warn(self):
        types = {a["type"]: a for a in self._run(1000.0, None, raw="高値-8%")}
        assert types["stop_unparsed"]["severity"] == "WARN"
        assert "高値-8%" in types["stop_unparsed"]["message"]

    def test_no_stop_levels_arg_is_backward_compatible(self):
        closes = _series(1000.0, 0.02, n=150, seed=4)
        got = detect_alerts(self.positions, {"A.T": {"price": 1000.0}}, {"A.T": closes})
        assert not {a["type"] for a in got} & {
            "stop_hit", "stop_noise_zone", "stop_near", "stop_unparsed"
        }

    def test_stop_hit_survives_state_change_filter(self):
        """A live stop breach must be reported every day, not just on day 1."""
        prev = [{"symbol": "A.T", "type": "stop_hit"}]
        closes = _series(950.0, 0.02, n=150, seed=5)
        closes[-1] = 950.0
        got = detect_alerts(
            self.positions, {"A.T": {"price": 950.0}}, {"A.T": closes},
            prev_alerts=prev,
            stop_levels={"A.T": {"stop": 1000.0, "raw": "1000", "conviction": False}},
        )
        assert "stop_hit" in {a["type"] for a in got}
