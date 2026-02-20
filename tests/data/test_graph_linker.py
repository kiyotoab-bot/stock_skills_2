"""Tests for src.data.graph_linker (KIK-434).

No real API or Neo4j connections -- all external calls are mocked.
"""

import pytest
from unittest.mock import MagicMock, patch


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Ensure ANTHROPIC_API_KEY is unset by default."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def linker():
    from src.data.graph_linker import AIGraphLinker
    return AIGraphLinker()


@pytest.fixture
def sample_candidates():
    return [
        {"id": "report_2026-01-01_AAPL", "type": "Report", "summary": "score=72.5 割安"},
        {"id": "report_2026-01-01_NVDA", "type": "Report", "summary": "score=55.0 やや割安"},
        {"id": "note_2026-01-15_AAPL", "type": "Note", "summary": "AAPLの懸念事項"},
    ]


@pytest.fixture
def sample_new_node():
    return {
        "id": "research_2026-02-01_industry_AI",
        "type": "Research",
        "target": "AI",
        "summary": "AI CapEx $6500億超、Blackwell 需要が爆発的",
    }


# ===================================================================
# TestAIGraphLinkerIsAvailable
# ===================================================================

class TestAIGraphLinkerIsAvailable:
    def test_returns_true_when_api_key_set(self, monkeypatch, linker):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        assert linker.is_available() is True

    def test_returns_false_when_no_api_key(self, linker):
        assert linker.is_available() is False


# ===================================================================
# TestAIGraphLinkerLinkOnSave
# ===================================================================

class TestAIGraphLinkerLinkOnSave:
    def test_returns_empty_when_no_api_key(self, linker, sample_new_node, sample_candidates):
        result = linker.link_on_save(sample_new_node, sample_candidates)
        assert result == []

    def test_returns_empty_when_no_candidates(self, monkeypatch, linker, sample_new_node):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        result = linker.link_on_save(sample_new_node, [])
        assert result == []

    def test_calls_llm_and_parses_response(
        self, monkeypatch, linker, sample_new_node, sample_candidates
    ):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        llm_response = (
            '[{"rel_type":"INFLUENCES","to_id":"candidate_0","confidence":0.85,"reason":"AI業界の成長がAAPLに影響"}]'
        )
        with patch.object(linker, "_call_llm", return_value=llm_response):
            result = linker.link_on_save(sample_new_node, sample_candidates)
        assert len(result) == 1
        assert result[0]["rel_type"] == "INFLUENCES"
        assert result[0]["to_id"] == "report_2026-01-01_AAPL"
        assert result[0]["confidence"] == pytest.approx(0.85)


# ===================================================================
# TestParseRelationships
# ===================================================================

class TestParseRelationships:
    def test_valid_json_returns_relationships(self, linker, sample_candidates):
        raw = '[{"rel_type":"INFLUENCES","to_id":"candidate_1","confidence":0.80,"reason":"テスト"}]'
        result = linker._parse_relationships(raw, sample_candidates)
        assert len(result) == 1
        assert result[0]["rel_type"] == "INFLUENCES"
        assert result[0]["to_id"] == "report_2026-01-01_NVDA"

    def test_invalid_json_returns_empty(self, linker, sample_candidates):
        result = linker._parse_relationships("not json at all", sample_candidates)
        assert result == []

    def test_empty_array_returns_empty(self, linker, sample_candidates):
        result = linker._parse_relationships("[]", sample_candidates)
        assert result == []

    def test_filters_low_confidence(self, linker, sample_candidates):
        raw = '[{"rel_type":"INFLUENCES","to_id":"candidate_0","confidence":0.5,"reason":"低信頼度"}]'
        result = linker._parse_relationships(raw, sample_candidates)
        assert result == []

    def test_filters_unknown_rel_type(self, linker, sample_candidates):
        raw = '[{"rel_type":"UNKNOWN_TYPE","to_id":"candidate_0","confidence":0.9,"reason":"不明"}]'
        result = linker._parse_relationships(raw, sample_candidates)
        assert result == []

    def test_maps_candidate_index_to_node_id(self, linker, sample_candidates):
        raw = '[{"rel_type":"CONTEXT_OF","to_id":"candidate_2","confidence":0.75,"reason":"コンテキスト"}]'
        result = linker._parse_relationships(raw, sample_candidates)
        assert len(result) == 1
        assert result[0]["to_id"] == "note_2026-01-15_AAPL"

    def test_out_of_range_candidate_index_skipped(self, linker, sample_candidates):
        raw = '[{"rel_type":"INFLUENCES","to_id":"candidate_99","confidence":0.9,"reason":"範囲外"}]'
        result = linker._parse_relationships(raw, sample_candidates)
        assert result == []

    def test_multiple_relationships_returned(self, linker, sample_candidates):
        raw = (
            '[{"rel_type":"INFLUENCES","to_id":"candidate_0","confidence":0.85,"reason":"理由1"},'
            '{"rel_type":"INFORMS","to_id":"candidate_1","confidence":0.70,"reason":"理由2"}]'
        )
        result = linker._parse_relationships(raw, sample_candidates)
        assert len(result) == 2

    def test_json_wrapped_in_text_extracted(self, linker, sample_candidates):
        """LLM may include text before/after the JSON array."""
        raw = 'こちらが結果です:\n[{"rel_type":"SUPPORTS","to_id":"candidate_0","confidence":0.75,"reason":"支持"}]\n以上です。'
        result = linker._parse_relationships(raw, sample_candidates)
        assert len(result) == 1
        assert result[0]["rel_type"] == "SUPPORTS"


# ===================================================================
# TestLinkHelpers
# ===================================================================

class TestLinkHelpers:
    def test_link_research_no_api_key_returns_zero(self):
        from src.data.graph_linker import link_research
        count = link_research("research_2026-01-01_industry_AI", "industry", "AI", "要約")
        assert count == 0

    def test_link_note_no_symbol_returns_zero(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        from src.data.graph_linker import link_note
        count = link_note("note_123", None, "observation", "内容")
        assert count == 0

    def test_link_report_no_api_key_returns_zero(self):
        from src.data.graph_linker import link_report
        count = link_report("report_2026-01-01_AAPL", "AAPL", "Technology", 72.5, "割安")
        assert count == 0
