"""Tests for KIK-564 lesson conflict detection."""

import pytest
from unittest.mock import patch


class TestKeywordSimilarity:
    def test_identical(self):
        from src.data.note_manager import _keyword_similarity
        assert _keyword_similarity("hello world", "hello world") == 1.0

    def test_disjoint(self):
        from src.data.note_manager import _keyword_similarity
        assert _keyword_similarity("hello", "world") == 0.0

    def test_partial(self):
        from src.data.note_manager import _keyword_similarity
        sim = _keyword_similarity("高値掴み RSI", "高値掴み 出来高")
        assert 0.0 < sim < 1.0

    def test_empty(self):
        from src.data.note_manager import _keyword_similarity
        assert _keyword_similarity("", "hello") == 0.0
        assert _keyword_similarity("", "") == 0.0


class TestEmbeddingSimilarity:
    def test_returns_none_when_unavailable(self):
        from src.data.note_manager import _embedding_similarity
        with patch("src.data.embedding_client.is_available", return_value=False):
            assert _embedding_similarity("a", "b") is None

    def test_returns_float_when_available(self):
        from src.data.note_manager import _embedding_similarity
        with patch("src.data.embedding_client.is_available", return_value=True), \
             patch("src.data.embedding_client.get_embedding", side_effect=[
                 [1.0, 0.0, 0.0],
                 [1.0, 0.0, 0.0],
             ]):
            sim = _embedding_similarity("a", "a")
            assert sim == pytest.approx(1.0)


class TestCheckLessonConflicts:
    def test_detects_contradicting_action(self, tmp_path):
        from src.data.note_manager import save_note, check_lesson_conflicts

        # Save two lessons with similar trigger but different action
        save_note(
            note_type="lesson", content="lesson1",
            trigger="高値掴み RSI高い時",
            expected_action="RSI70超で買わない",
            base_dir=str(tmp_path),
        )
        new_lesson = {
            "trigger": "高値掴み RSI高い時",
            "expected_action": "RSI80超でも買う",
            "content": "lesson2",
        }
        conflicts = check_lesson_conflicts(new_lesson, base_dir=str(tmp_path))
        assert len(conflicts) >= 1
        assert conflicts[0]["conflict_type"] == "contradicting_action"

    def test_no_conflict_when_empty(self, tmp_path):
        from src.data.note_manager import check_lesson_conflicts

        conflicts = check_lesson_conflicts(
            {"trigger": "test", "expected_action": "act"},
            base_dir=str(tmp_path),
        )
        assert conflicts == []

    def test_no_conflict_same_action(self, tmp_path):
        from src.data.note_manager import save_note, check_lesson_conflicts

        save_note(
            note_type="lesson", content="lesson1",
            trigger="パニック売り",
            expected_action="冷静に待つ",
            base_dir=str(tmp_path),
        )
        new_lesson = {
            "trigger": "パニック売り",
            "expected_action": "冷静に待つ",
            "content": "same action",
        }
        conflicts = check_lesson_conflicts(new_lesson, base_dir=str(tmp_path))
        # Same action → not a contradicting_action conflict
        for c in conflicts:
            assert c["conflict_type"] != "contradicting_action"

    def test_below_threshold_not_flagged(self, tmp_path):
        from src.data.note_manager import save_note, check_lesson_conflicts

        save_note(
            note_type="lesson", content="completely different",
            trigger="xyz abc",
            expected_action="do xyz",
            base_dir=str(tmp_path),
        )
        new_lesson = {
            "trigger": "something entirely unrelated",
            "expected_action": "different action",
            "content": "no overlap",
        }
        conflicts = check_lesson_conflicts(
            new_lesson, base_dir=str(tmp_path), similarity_threshold=0.8,
        )
        assert conflicts == []


class TestSaveNoteConflicts:
    def test_save_note_returns_conflicts(self, tmp_path):
        from src.data.note_manager import save_note

        save_note(
            note_type="lesson", content="first",
            trigger="モメンタム飛びつき",
            expected_action="出来高確認",
            base_dir=str(tmp_path),
        )
        result = save_note(
            note_type="lesson", content="second",
            trigger="モメンタム飛びつき",
            expected_action="即座に購入",
            base_dir=str(tmp_path),
        )
        assert "_conflicts" in result
        assert len(result["_conflicts"]) >= 1

    def test_save_note_no_conflicts_for_non_lesson(self, tmp_path):
        from src.data.note_manager import save_note

        result = save_note(
            note_type="observation", content="just an obs",
            base_dir=str(tmp_path),
        )
        assert "_conflicts" not in result


class TestFormatLessonSectionConflicts:
    def test_conflict_annotation(self):
        from src.data.context.auto_context import _format_lesson_section

        lessons = [
            {"id": "a", "trigger": "高値掴み RSI", "expected_action": "買わない", "date": "2026-03-01"},
            {"id": "b", "trigger": "高値掴み RSI", "expected_action": "買う", "date": "2026-03-15"},
        ]
        output = _format_lesson_section(lessons)
        assert "⚠️矛盾候補" in output
        assert "統合" in output

    def test_no_conflict_no_annotation(self):
        from src.data.context.auto_context import _format_lesson_section

        lessons = [
            {"id": "a", "trigger": "高値掴み", "expected_action": "RSI確認", "date": "2026-03-01"},
            {"id": "b", "trigger": "パニック売り", "expected_action": "冷静に待つ", "date": "2026-03-15"},
        ]
        output = _format_lesson_section(lessons)
        assert "⚠️矛盾候補" not in output

    def test_empty_lessons(self):
        from src.data.context.auto_context import _format_lesson_section
        assert _format_lesson_section([]) == ""
