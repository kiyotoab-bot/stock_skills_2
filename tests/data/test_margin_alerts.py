"""Tests for margin-ratio (信用倍率) alerts (KIK-732).

需給は週次ルーティンの Step 3c に定義されていたが、2026-08-06 まで一度も
実行されておらず、保有の 8031.T 三井物産が信用倍率 38.5倍（買い残が売り残の38倍）
だったことに気づいていなかった。値動きとバリュエーションだけを見ていると
完全に抜ける軸なので、日次のアラートに組み込む。
"""

import numpy as np
import pytest

from src.data.morning_summary import detect_alerts


def _series(base: float, sigma: float, n: int = 150, seed: int = 7) -> list[float]:
    rng = np.random.default_rng(seed)
    return list(base * np.exp(np.cumsum(rng.normal(0.0, sigma, n))))


class TestMarginAlerts:
    positions = [{"symbol": "A.T", "cost_price": 1000.0}]

    def _run(self, ratio=None, wow=None, available=True):
        closes = _series(1000.0, 0.015)
        closes[-1] = 1000.0
        margins = {"A.T": {
            "available": available, "margin_ratio": ratio,
            "wow_change_pct": wow, "date": "2026-07-31",
        }}
        return detect_alerts(
            self.positions, {"A.T": {"price": 1000.0}}, {"A.T": closes},
            margins=margins,
        )

    def test_mitsui_case_is_warn(self):
        """8031.T の実測値 38.5倍。"""
        types = {a["type"]: a for a in self._run(ratio=38.5)}
        assert types["margin_extreme"]["severity"] == "WARN"
        assert "38.5" in types["margin_extreme"]["message"]

    def test_nec_case_is_info(self):
        """6701.T の実測値 20.29倍 — 重いが極端ではない。"""
        types = {a["type"]: a for a in self._run(ratio=20.29)}
        assert types["margin_heavy"]["severity"] == "INFO"
        assert "margin_extreme" not in types

    def test_ryohin_case_is_silent(self):
        """7453.T の実測値 1.56倍 — 需給良好なので何も出さない。"""
        got = {a["type"] for a in self._run(ratio=1.56)}
        assert not got & {"margin_heavy", "margin_extreme"}

    @pytest.mark.parametrize("ratio,expect", [
        (14.9, None), (15.0, "margin_heavy"), (29.9, "margin_heavy"),
        (30.0, "margin_extreme"), (100.0, "margin_extreme"),
    ])
    def test_thresholds(self, ratio, expect):
        got = {a["type"] for a in self._run(ratio=ratio)}
        margin_types = got & {"margin_heavy", "margin_extreme"}
        assert margin_types == ({expect} if expect else set())

    def test_surge_is_independent_of_level(self):
        """買い残が低水準でも、急増していれば拾う。"""
        got = {a["type"] for a in self._run(ratio=2.0, wow=60.0)}
        assert "margin_surge" in got
        assert not got & {"margin_heavy", "margin_extreme"}

    def test_surge_threshold(self):
        assert "margin_surge" not in {a["type"] for a in self._run(ratio=2.0, wow=49.9)}
        assert "margin_surge" in {a["type"] for a in self._run(ratio=2.0, wow=50.0)}

    def test_extreme_and_surge_can_both_fire(self):
        got = {a["type"] for a in self._run(ratio=38.5, wow=60.0)}
        assert {"margin_extreme", "margin_surge"} <= got

    def test_unavailable_margin_is_silent(self):
        got = {a["type"] for a in self._run(ratio=38.5, available=False)}
        assert not got & {"margin_heavy", "margin_extreme", "margin_surge"}

    @pytest.mark.parametrize("ratio", [None, 0, -1])
    def test_missing_or_nonpositive_ratio_is_silent(self, ratio):
        got = {a["type"] for a in self._run(ratio=ratio)}
        assert not got & {"margin_heavy", "margin_extreme"}

    def test_no_margins_arg_is_backward_compatible(self):
        closes = _series(1000.0, 0.015)
        got = detect_alerts(self.positions, {"A.T": {"price": 1000.0}}, {"A.T": closes})
        assert not {a["type"] for a in got} & {
            "margin_heavy", "margin_extreme", "margin_surge"
        }

    def test_margin_alerts_are_state_change_filtered(self):
        """週次データなので毎日同じ値が続く。連日出し続けない。"""
        prev = [{"symbol": "A.T", "type": "margin_extreme"}]
        got = {a["type"] for a in detect_alerts(
            self.positions, {"A.T": {"price": 1000.0}},
            {"A.T": _series(1000.0, 0.015)},
            prev_alerts=prev,
            margins={"A.T": {"available": True, "margin_ratio": 38.5, "date": "2026-07-31"}},
        )}
        assert "margin_extreme" not in got
