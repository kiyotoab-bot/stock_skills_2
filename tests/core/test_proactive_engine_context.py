"""Tests for ProactiveEngine._check_context_triggers (KIK-465)."""

import pytest

from src.core.proactive_engine import ProactiveEngine, _CONTEXT_PATTERNS


@pytest.fixture
def engine():
    return ProactiveEngine()


class TestCheckContextTriggers:
    """Tests for _check_context_triggers method."""

    def test_empty_context_returns_empty(self, engine):
        assert engine._check_context_triggers("") == []

    def test_none_context_returns_empty(self, engine):
        assert engine._check_context_triggers() == []

    def test_no_match_returns_empty(self, engine):
        assert engine._check_context_triggers("全く関係ないテキスト") == []

    def test_energy_keywords_trigger(self, engine):
        for kw in ["エネルギー", "原油", "石油", "天然ガス", "energy", "oil"]:
            results = engine._check_context_triggers(f"セクター: {kw}関連")
            assert len(results) >= 1
            titles = [r["title"] for r in results]
            assert "エネルギーセクターの確認" in titles

    def test_tech_weak_keywords_trigger(self, engine):
        for kw in ["テック軟調", "ハイテク下落", "テクノロジー下落", "tech decline"]:
            results = engine._check_context_triggers(kw)
            assert len(results) >= 1
            titles = [r["title"] for r in results]
            assert "テック銘柄のリスク確認" in titles

    def test_gold_keywords_trigger(self, engine):
        for kw in ["金急騰", "金価格", "ゴールド", "gold"]:
            results = engine._check_context_triggers(kw)
            assert len(results) >= 1
            titles = [r["title"] for r in results]
            assert "コモディティ関連の影響確認" in titles

    def test_rate_keywords_trigger(self, engine):
        for kw in ["利上げ", "金利上昇", "rate hike", "利下げ", "金利低下"]:
            results = engine._check_context_triggers(kw)
            assert len(results) >= 1
            titles = [r["title"] for r in results]
            assert "金利変動のPF影響確認" in titles

    def test_earnings_keywords_trigger(self, engine):
        for kw in ["決算", "好決算", "悪決算", "earnings", "上方修正", "下方修正"]:
            results = engine._check_context_triggers(kw)
            assert len(results) >= 1
            titles = [r["title"] for r in results]
            assert "決算関連銘柄のフォローアップ" in titles

    def test_health_warning_trigger(self, engine):
        for kw in ["警戒", "EXIT", "損切り", "バリュートラップ", "デッドクロス"]:
            results = engine._check_context_triggers(kw)
            assert len(results) >= 1
            titles = [r["title"] for r in results]
            assert "警戒銘柄の対応検討" in titles

    def test_screening_result_trigger(self, engine):
        for kw in ["スクリーニング完了", "銘柄発見", "上位ランクイン"]:
            results = engine._check_context_triggers(kw)
            assert len(results) >= 1
            titles = [r["title"] for r in results]
            assert "上位銘柄の詳細分析" in titles

    def test_max_two_context_triggers(self, engine):
        """Even if many patterns match, at most 2 are returned."""
        # Combine keywords from multiple patterns to trigger many matches
        context = "エネルギー 決算 利上げ 警戒 gold スクリーニング完了"
        results = engine._check_context_triggers(context)
        assert len(results) <= 2

    def test_case_insensitive_matching(self, engine):
        results_lower = engine._check_context_triggers("energy sector report")
        results_upper = engine._check_context_triggers("ENERGY sector report")
        assert len(results_lower) == len(results_upper)
        assert len(results_lower) >= 1

    def test_result_structure(self, engine):
        results = engine._check_context_triggers("決算発表あり")
        assert len(results) >= 1
        r = results[0]
        assert "emoji" in r
        assert "title" in r
        assert "reason" in r
        assert "command_hint" in r
        assert "urgency" in r
        assert r["urgency"] == "low"

    def test_reason_includes_context_prefix(self, engine):
        results = engine._check_context_triggers("決算発表あり")
        assert results[0]["reason"].startswith("実行結果に関連:")

    def test_reason_truncates_long_context(self, engine):
        long_context = "決算" + "x" * 200
        results = engine._check_context_triggers(long_context)
        assert len(results[0]["reason"]) < 200  # truncated at 60 chars of context

    def test_context_integrated_in_get_suggestions(self, engine, monkeypatch):
        """Context triggers appear in get_suggestions output."""
        # Stub out other trigger methods to isolate context triggers
        monkeypatch.setattr(engine, "_check_time_triggers", lambda: [])
        monkeypatch.setattr(engine, "_check_state_triggers", lambda s="": [])
        monkeypatch.setattr(engine, "_check_contextual_triggers", lambda s="": [])

        results = engine.get_suggestions(context="決算発表あり")
        assert len(results) >= 1
        assert results[0]["title"] == "決算関連銘柄のフォローアップ"


class TestContextPatterns:
    """Verify _CONTEXT_PATTERNS structure is valid."""

    def test_all_patterns_have_required_keys(self):
        required_keys = {"keywords", "emoji", "title", "command_hint"}
        for key, pattern in _CONTEXT_PATTERNS.items():
            assert required_keys.issubset(pattern.keys()), f"Pattern '{key}' missing keys"

    def test_all_patterns_have_nonempty_keywords(self):
        for key, pattern in _CONTEXT_PATTERNS.items():
            assert len(pattern["keywords"]) > 0, f"Pattern '{key}' has empty keywords"

    def test_pattern_count(self):
        assert len(_CONTEXT_PATTERNS) == 7
