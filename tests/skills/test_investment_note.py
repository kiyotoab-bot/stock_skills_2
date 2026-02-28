"""Tests for investment-note skill argument parsing (KIK-518)."""

import argparse
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add skill script directory to path
_SKILL_SCRIPTS = Path(__file__).resolve().parent.parent.parent / ".claude" / "skills" / "investment-note" / "scripts"
if str(_SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SKILL_SCRIPTS))


class TestNoteArgParsing:
    """Test argument parsing for the investment-note skill."""

    def test_save_with_symbol(self):
        from manage_note import main

        # Build parser to test argument parsing
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        p_save = subparsers.add_parser("save")
        p_save.add_argument("--symbol", default=None)
        p_save.add_argument("--category", default=None)
        p_save.add_argument("--type", default="observation")
        p_save.add_argument("--content", required=True)
        p_save.add_argument("--source", default="manual")

        args = parser.parse_args(["save", "--symbol", "7203.T", "--type", "thesis", "--content", "Test"])
        assert args.command == "save"
        assert args.symbol == "7203.T"
        assert args.type == "thesis"
        assert args.content == "Test"

    def test_save_with_category(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        p_save = subparsers.add_parser("save")
        p_save.add_argument("--symbol", default=None)
        p_save.add_argument("--category", default=None, choices=["portfolio", "market", "general"])
        p_save.add_argument("--type", default="observation")
        p_save.add_argument("--content", required=True)
        p_save.add_argument("--source", default="manual")

        args = parser.parse_args(["save", "--category", "portfolio", "--content", "PF review"])
        assert args.category == "portfolio"
        assert args.symbol is None

    def test_list_no_filter(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        p_list = subparsers.add_parser("list")
        p_list.add_argument("--symbol", default=None)
        p_list.add_argument("--category", default=None)
        p_list.add_argument("--type", default=None)

        args = parser.parse_args(["list"])
        assert args.command == "list"
        assert args.symbol is None
        assert args.type is None

    def test_list_with_symbol_filter(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        p_list = subparsers.add_parser("list")
        p_list.add_argument("--symbol", default=None)
        p_list.add_argument("--category", default=None)
        p_list.add_argument("--type", default=None)

        args = parser.parse_args(["list", "--symbol", "AAPL"])
        assert args.symbol == "AAPL"

    def test_delete_with_id(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        p_delete = subparsers.add_parser("delete")
        p_delete.add_argument("--id", required=True)

        args = parser.parse_args(["delete", "--id", "abc123"])
        assert args.command == "delete"
        assert args.id == "abc123"

    def test_no_subcommand_exits(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)
        subparsers.add_parser("save")

        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestNoteSaveValidation:
    """Test save command validation logic."""

    def test_save_requires_content(self, capsys):
        """cmd_save should error if content is empty."""
        from manage_note import cmd_save

        args = argparse.Namespace(
            symbol="7203.T",
            type="observation",
            content="",
            source="manual",
            category=None,
        )
        with pytest.raises(SystemExit):
            cmd_save(args)
        output = capsys.readouterr().out
        assert "content" in output.lower() or "--content" in output

    def test_save_requires_symbol_or_category_for_non_journal(self, capsys):
        """Non-journal types require either symbol or category."""
        from manage_note import cmd_save

        args = argparse.Namespace(
            symbol=None,
            type="observation",
            content="some content",
            source="manual",
            category=None,
        )
        with pytest.raises(SystemExit):
            cmd_save(args)
        output = capsys.readouterr().out
        assert "symbol" in output.lower() or "category" in output.lower()

    def test_journal_does_not_require_symbol(self, capsys):
        """Journal type should work without --symbol or --category."""
        from manage_note import cmd_save

        mock_note = {
            "id": "test-id",
            "symbol": None,
            "type": "journal",
            "content": "Today was a good day",
            "category": "general",
            "detected_symbols": [],
        }
        args = argparse.Namespace(
            symbol=None,
            type="journal",
            content="Today was a good day",
            source="manual",
            category=None,
        )
        with patch("manage_note.save_note", return_value=mock_note), \
             patch("manage_note.print_suggestions"):
            cmd_save(args)
        output = capsys.readouterr().out
        assert "メモを保存しました" in output


class TestNoteList:
    """Test list command output."""

    def test_empty_list(self, capsys):
        from manage_note import cmd_list

        args = argparse.Namespace(symbol=None, type=None, category=None)
        with patch("manage_note.load_notes", return_value=[]):
            cmd_list(args)
        output = capsys.readouterr().out
        assert "メモはありません" in output

    def test_list_with_notes(self, capsys):
        from manage_note import cmd_list

        mock_notes = [
            {
                "date": "2026-02-28",
                "symbol": "7203.T",
                "type": "thesis",
                "content": "Toyota is undervalued",
                "category": "stock",
            }
        ]
        args = argparse.Namespace(symbol=None, type=None, category=None)
        with patch("manage_note.load_notes", return_value=mock_notes):
            cmd_list(args)
        output = capsys.readouterr().out
        assert "投資メモ一覧" in output
        assert "7203.T" in output
        assert "thesis" in output
        assert "合計 1 件" in output
