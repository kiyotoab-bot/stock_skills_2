"""Tests for print_context() and print_suggestions() in scripts/common.py (KIK-465)."""

import signal
from unittest.mock import MagicMock, patch

import pytest

from scripts.common import print_context, print_suggestions, _CONTEXT_TIMEOUT


class TestPrintContext:
    """Tests for print_context()."""

    def test_returns_none_when_no_input(self):
        assert print_context("") is None

    def test_returns_none_when_empty_string(self):
        assert print_context("") is None

    def test_returns_none_when_auto_context_unavailable(self):
        with patch.dict("sys.modules", {"src.data.auto_context": None}):
            assert print_context("test input") is None

    def test_returns_action_label_on_success(self):
        mock_result = {
            "context_markdown": "## Context\nSome context data",
            "action_label": "FRESH",
        }
        with patch("scripts.common.get_context", create=True):
            # Patch the lazy import inside print_context
            with patch.dict("sys.modules", {}):
                mock_module = MagicMock()
                mock_module.get_context.return_value = mock_result
                with patch.dict("sys.modules", {"src.data.auto_context": mock_module}):
                    result = print_context("report 7203.T")
                    assert result == "FRESH"

    def test_prints_context_markdown(self, capsys):
        mock_result = {
            "context_markdown": "## Context Output",
            "action_label": "RECENT",
        }
        mock_module = MagicMock()
        mock_module.get_context.return_value = mock_result
        with patch.dict("sys.modules", {"src.data.auto_context": mock_module}):
            result = print_context("screen japan")
            assert result == "RECENT"
            captured = capsys.readouterr()
            assert "## Context Output" in captured.out

    def test_returns_none_when_no_context_markdown(self):
        mock_module = MagicMock()
        mock_module.get_context.return_value = {"context_markdown": "", "action_label": "NONE"}
        with patch.dict("sys.modules", {"src.data.auto_context": mock_module}):
            assert print_context("test") is None

    def test_returns_none_when_result_is_none(self):
        mock_module = MagicMock()
        mock_module.get_context.return_value = None
        with patch.dict("sys.modules", {"src.data.auto_context": mock_module}):
            assert print_context("test") is None

    def test_handles_exception_gracefully(self):
        mock_module = MagicMock()
        mock_module.get_context.side_effect = RuntimeError("Neo4j down")
        with patch.dict("sys.modules", {"src.data.auto_context": mock_module}):
            assert print_context("test") is None

    def test_timeout_value(self):
        assert _CONTEXT_TIMEOUT == 10


class TestPrintSuggestions:
    """Tests for print_suggestions()."""

    def test_no_output_when_no_suggestions(self, capsys):
        mock_engine = MagicMock()
        mock_engine.get_suggestions.return_value = []
        mock_format = MagicMock(return_value="")
        with patch.dict("sys.modules", {"src.core.proactive_engine": MagicMock(
            get_suggestions=lambda **kw: [],
            format_suggestions=lambda s: "",
        )}):
            print_suggestions()
            captured = capsys.readouterr()
            assert captured.out == ""

    def test_prints_suggestions_on_success(self, capsys):
        suggestions = [
            {"emoji": "📋", "title": "ヘルスチェック", "reason": "14日経過",
             "command_hint": "portfolio health", "urgency": "medium"},
        ]
        formatted = "\n---\n💡 **次のアクション提案** (1件)\n\n1. 📋 **ヘルスチェック**\n   14日経過\n   → `portfolio health` を実行してください\n"
        mock_mod = MagicMock()
        mock_mod.get_suggestions.return_value = suggestions
        mock_mod.format_suggestions.return_value = formatted
        with patch.dict("sys.modules", {"src.core.proactive_engine": mock_mod}):
            print_suggestions(symbol="7203.T", context_summary="レポート生成")
            captured = capsys.readouterr()
            assert "ヘルスチェック" in captured.out

    def test_handles_import_error_gracefully(self, capsys):
        with patch.dict("sys.modules", {"src.core.proactive_engine": None}):
            # Should not raise
            print_suggestions(symbol="AAPL")
            captured = capsys.readouterr()
            assert captured.out == ""

    def test_handles_exception_gracefully(self, capsys):
        mock_mod = MagicMock()
        mock_mod.get_suggestions.side_effect = RuntimeError("Neo4j down")
        with patch.dict("sys.modules", {"src.core.proactive_engine": mock_mod}):
            print_suggestions(context_summary="test")
            captured = capsys.readouterr()
            assert captured.out == ""

    def test_passes_context_summary_to_engine(self):
        mock_mod = MagicMock()
        mock_mod.get_suggestions.return_value = []
        mock_mod.format_suggestions.return_value = ""
        with patch.dict("sys.modules", {"src.core.proactive_engine": mock_mod}):
            print_suggestions(
                symbol="NVDA",
                sector="Technology",
                context_summary="スクリーニング完了: alpha japan 10銘柄",
            )
            mock_mod.get_suggestions.assert_called_once_with(
                context="スクリーニング完了: alpha japan 10銘柄",
                symbol="NVDA",
                sector="Technology",
            )
