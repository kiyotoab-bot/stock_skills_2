"""Tests for src.output.screening_summary_formatter (KIK-452)."""

import pytest
from src.output.screening_summary_formatter import format_screening_summary


# ===================================================================
# Empty / no-data cases
# ===================================================================

class TestEmptyOutput:
    def test_returns_empty_string_when_no_data_and_no_llm(self):
        context = {"has_data": False, "sector_research": {}, "symbol_notes": {}, "symbol_themes": {}}
        result = format_screening_summary(context)
        assert result == ""

    def test_returns_empty_string_when_has_data_false_and_no_llm(self):
        context = {
            "has_data": False,
            "sector_research": {"Technology": {"summaries": [], "catalysts_pos": [], "catalysts_neg": []}},
        }
        result = format_screening_summary(context)
        assert result == ""

    def test_returns_output_when_no_data_but_llm_text_provided(self):
        context = {"has_data": False, "sector_research": {}, "symbol_notes": {}, "symbol_themes": {}}
        result = format_screening_summary(context, llm_text="テスト サマリー")
        assert "テスト サマリー" in result


# ===================================================================
# Sector research section
# ===================================================================

class TestSectorResearchSection:
    def _make_context(self, pos=None, neg=None):
        return {
            "has_data": True,
            "sector_research": {
                "Technology": {
                    "summaries": ["AI需要拡大"],
                    "catalysts_pos": pos or [],
                    "catalysts_neg": neg or [],
                }
            },
            "symbol_notes": {},
            "symbol_themes": {},
        }

    def test_positive_catalysts_shown(self):
        ctx = self._make_context(pos=["AI需要増", "設備投資"])
        result = format_screening_summary(ctx)
        assert "ポジティブ" in result
        assert "AI需要増" in result
        assert "設備投資" in result

    def test_negative_catalysts_shown(self):
        ctx = self._make_context(neg=["地政学リスク", "競合増加"])
        result = format_screening_summary(ctx)
        assert "ネガティブ" in result
        assert "地政学リスク" in result

    def test_max_3_catalysts_shown(self):
        ctx = self._make_context(pos=["a", "b", "c", "d", "e"])
        result = format_screening_summary(ctx)
        # Should show at most 3 (joined with 、)
        # "a、b、c" should appear but "d" and "e" should not
        assert "a" in result
        assert "b" in result
        assert "c" in result
        # 4th item should NOT appear
        assert "d" not in result

    def test_sector_header_shown(self):
        ctx = self._make_context(pos=["x"])
        result = format_screening_summary(ctx)
        assert "Technology" in result
        assert "セクタートレンド" in result

    def test_no_section_for_empty_catalysts(self):
        ctx = self._make_context()
        # has_data=True but no catalysts in section
        result = format_screening_summary(ctx)
        # Should still show header but no catalyst lines
        assert "Technology" in result
        assert "ポジティブ" not in result
        assert "ネガティブ" not in result


# ===================================================================
# Symbol notes section
# ===================================================================

class TestSymbolNotesSection:
    def _make_context(self, notes):
        return {
            "has_data": True,
            "sector_research": {},
            "symbol_notes": notes,
            "symbol_themes": {},
        }

    def test_thesis_note_shown(self):
        ctx = self._make_context({"NVDA": [{"type": "thesis", "content": "AI長期成長株", "date": "2026-01-15"}]})
        result = format_screening_summary(ctx)
        assert "NVDA" in result
        assert "テーゼ" in result
        assert "AI長期成長株" in result

    def test_concern_note_shown(self):
        ctx = self._make_context({"AAPL": [{"type": "concern", "content": "競合増加が心配", "date": "2026-02-01"}]})
        result = format_screening_summary(ctx)
        assert "AAPL" in result
        assert "懸念" in result

    def test_date_shown_in_note(self):
        ctx = self._make_context({"NVDA": [{"type": "thesis", "content": "テーゼ内容", "date": "2026-01-15"}]})
        result = format_screening_summary(ctx)
        assert "2026-01-15" in result

    def test_long_content_truncated_to_80_chars(self):
        long_content = "A" * 100
        ctx = self._make_context({"NVDA": [{"type": "thesis", "content": long_content, "date": ""}]})
        result = format_screening_summary(ctx)
        # Should not appear in full; should be truncated
        assert "A" * 100 not in result
        assert "..." in result

    def test_max_2_notes_per_symbol(self):
        notes = [
            {"type": "thesis", "content": "note1", "date": ""},
            {"type": "concern", "content": "note2", "date": ""},
            {"type": "observation", "content": "note3", "date": ""},
        ]
        ctx = self._make_context({"NVDA": notes})
        result = format_screening_summary(ctx)
        assert "note1" in result
        assert "note2" in result
        assert "note3" not in result


# ===================================================================
# Symbol themes section
# ===================================================================

class TestSymbolThemesSection:
    def test_themes_shown(self):
        ctx = {
            "has_data": True,
            "sector_research": {},
            "symbol_notes": {},
            "symbol_themes": {"NVDA": ["AI", "半導体"]},
        }
        result = format_screening_summary(ctx)
        assert "NVDA" in result
        assert "AI" in result
        assert "半導体" in result
        assert "テーマ" in result


# ===================================================================
# LLM summary section
# ===================================================================

class TestLLMSummarySection:
    def test_llm_text_shown_when_provided(self):
        ctx = {"has_data": True, "sector_research": {}, "symbol_notes": {}, "symbol_themes": {}}
        result = format_screening_summary(ctx, llm_text="これはAI統合サマリーです。")
        assert "これはAI統合サマリーです。" in result
        assert "AI統合サマリー" in result

    def test_llm_text_not_shown_when_empty(self):
        ctx = {
            "has_data": True,
            "sector_research": {"Technology": {"summaries": [], "catalysts_pos": ["x"], "catalysts_neg": []}},
            "symbol_notes": {},
            "symbol_themes": {},
        }
        result = format_screening_summary(ctx, llm_text="")
        assert "AI統合サマリー" not in result

    def test_llm_text_whitespace_stripped(self):
        ctx = {"has_data": True, "sector_research": {}, "symbol_notes": {}, "symbol_themes": {}}
        result = format_screening_summary(ctx, llm_text="  サマリーテキスト  ")
        assert "サマリーテキスト" in result
        # Leading/trailing whitespace should be stripped
        assert "  サマリーテキスト  " not in result


# ===================================================================
# Section header and markdown structure
# ===================================================================

class TestMarkdownStructure:
    def test_contains_section_header(self):
        ctx = {
            "has_data": True,
            "sector_research": {"Technology": {"summaries": [], "catalysts_pos": ["x"], "catalysts_neg": []}},
            "symbol_notes": {},
            "symbol_themes": {},
        }
        result = format_screening_summary(ctx)
        assert "グラフコンテキスト" in result
        assert "---" in result

    def test_returns_string(self):
        ctx = {"has_data": True, "sector_research": {}, "symbol_notes": {}, "symbol_themes": {}}
        result = format_screening_summary(ctx, llm_text="test")
        assert isinstance(result, str)
