"""Tests for provisional CV3 — KIK-755.

9104.T 商船三井では**購入前に**仮のストップを置いて CV3 を埋め、
それで conviction 3/3 が成立して配分上限が 15%→25% に緩和された。
ストップは簿価×0.85 に依存するので購入前の値は必ず置き換わる。
実体が未確定の exit 条件を上限緩和の根拠にしない。

独立レビュー（Gemini, 2026-08-11）の指摘:
「実体性のない仮の値で CV3 を形式的に埋め、上限緩和の口実に使うのは
  conviction 制度の形骸化」
"""

import pytest

from src.data.concentration import (
    check_concentration,
    classify_conviction,
    max_additional_shares,
    _is_provisional_stop,
)


CFG = {"concentration": {
    "basis": "equity",
    "single_stock": {"normal": {"warn": 12, "limit": 15},
                     "conviction": {"warn": 20, "limit": 25}},
    "top3_stocks": {"warn": 60, "limit": 70},
    "sector": {"warn": 35, "limit": 45},
}}


def _notes(symbol, exit_content, thesis="会社予想（J-Quants）で検証済み"):
    return [
        {"symbol": symbol, "type": "thesis", "content": thesis},
        {"symbol": symbol, "type": "exit-rule", "content": exit_content},
    ]


class TestProvisionalDetection:
    @pytest.mark.parametrize("marker", ["仮設定", "仮の値", "仮ストップ",
                                        "再算定必須", "暫定"])
    def test_markers_are_detected(self, marker):
        notes = [{"type": "exit-rule", "content": f"ストップ¥5,787（{marker}）"}]
        assert _is_provisional_stop(notes, {}) is True

    def test_confirmed_stop_is_not_provisional(self):
        notes = [{"type": "exit-rule", "content": "ストップ ¥4,350。算定済み"}]
        assert _is_provisional_stop(notes, {}) is False

    def test_marker_in_other_note_type_is_ignored(self):
        """thesis に「暫定」と書いてあっても exit 条件が仮になるわけではない。"""
        notes = [{"type": "thesis", "content": "暫定的な見立てだが強気"}]
        assert _is_provisional_stop(notes, {}) is False

    def test_no_exit_rule_note_is_not_provisional(self):
        assert _is_provisional_stop([], {}) is False


class TestTierAssignment:
    def test_provisional_stop_yields_provisional_tier(self):
        notes = _notes("9104.T", "【ストップ仮設定】発注日に再算定必須")
        r = classify_conviction("9104.T", notes, {"9104.T": {"stop": 5787.0}})
        assert r["tier"] == "conviction_provisional"
        assert r["provisional"] is True
        assert all(r["criteria"].values())   # 3/3 は満たしている

    def test_confirmed_stop_yields_full_conviction(self):
        notes = _notes("7751.T", "ストップ ¥4,350。取得後に算定済み")
        r = classify_conviction("7751.T", notes, {"7751.T": {"stop": 4350.0}})
        assert r["tier"] == "conviction"
        assert r["provisional"] is False

    def test_override_wins_over_provisional(self):
        """無条件保有は仮ストップの有無に関係なく override のまま。"""
        notes = [
            {"symbol": "7453.T", "type": "thesis",
             "content": "conviction_override。無条件保有"},
            {"symbol": "7453.T", "type": "exit-rule", "content": "仮設定"},
        ]
        r = classify_conviction("7453.T", notes, {})
        assert r["tier"] == "conviction_override"

    def test_incomplete_criteria_stays_normal(self):
        notes = [{"symbol": "X", "type": "exit-rule", "content": "仮設定"}]
        r = classify_conviction("X", notes, {"X": {"stop": 100.0}})
        assert r["tier"] == "normal"


class TestLimitsAreNotRelaxed:
    """本題: 仮認定で上限が緩まないこと。"""

    def _stock(self, tier, value=1_237_200):
        pos = [{"symbol": "9104.T", "value": value,
                "sector": "Industrials", "tier": tier}]
        return check_concentration(pos, CFG, denominator=6_348_953)["stocks"][0]

    def test_provisional_uses_normal_limit(self):
        assert self._stock("conviction_provisional")["limit"] == 15

    def test_full_conviction_uses_relaxed_limit(self):
        assert self._stock("conviction")["limit"] == 25

    def test_provisional_flags_what_conviction_would_pass(self):
        """19.5% は conviction なら green、仮認定なら red。"""
        assert self._stock("conviction")["level"] == "green"
        assert self._stock("conviction_provisional")["level"] == "red"

    def test_provisional_matches_normal_exactly(self):
        prov = self._stock("conviction_provisional")
        norm = self._stock("normal")
        assert (prov["limit"], prov["level"]) == (norm["limit"], norm["level"])

    def test_additional_shares_capped_at_normal(self):
        pos = [{"symbol": "9104.T", "value": 600_000, "sector": "Industrials"}]
        prov = max_additional_shares("9104.T", 6186, pos, tier="conviction_provisional",
                                     config=CFG, denominator=6_348_953)
        conv = max_additional_shares("9104.T", 6186, pos, tier="conviction",
                                     config=CFG, denominator=6_348_953)
        norm = max_additional_shares("9104.T", 6186, pos, tier="normal",
                                     config=CFG, denominator=6_348_953)
        assert prov["shares"] == norm["shares"]
        assert prov["shares"] < conv["shares"]
