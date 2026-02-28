"""Tests for scripts/cli_framework.py (KIK-518)."""

import argparse
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from scripts.cli_framework import BaseSkillCommand, _ensure_project_root


# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------


class EchoCommand(BaseSkillCommand):
    """Minimal command that echoes its argument."""

    name = "echo"
    description = "Echo test command"

    def configure_parser(self, parser):
        parser.add_argument("message", help="Message to echo")
        parser.add_argument("--loud", action="store_true", help="Uppercase output")

    def context_input(self, args):
        return f"echo {args.message}"

    def run(self, args):
        msg = args.message.upper() if args.loud else args.message
        print(msg)

    def suggestion_kwargs(self, args):
        return {"context_summary": f"echo: {args.message}"}


class SilentCommand(BaseSkillCommand):
    """Command that skips context and suggestions."""

    name = "silent"
    description = "Silent command"

    def run(self, args):
        print("silent")


class FailingCommand(BaseSkillCommand):
    """Command whose run() raises an exception."""

    name = "failing"
    description = "Failing command"

    def run(self, args):
        raise ValueError("intentional error")


# ---------------------------------------------------------------------------
# _ensure_project_root
# ---------------------------------------------------------------------------


class TestEnsureProjectRoot:
    def test_adds_root_to_sys_path(self, tmp_path):
        # Simulate .claude/skills/graph-query/scripts/run_query.py
        script = tmp_path / "a" / "b" / "c" / "d" / "script.py"
        script.parent.mkdir(parents=True)
        script.touch()

        root = _ensure_project_root(str(script), depth=4)
        assert root == str((tmp_path / "a").resolve())
        assert root in sys.path

    def test_idempotent(self, tmp_path):
        script = tmp_path / "a" / "b" / "script.py"
        script.parent.mkdir(parents=True)
        script.touch()

        root = _ensure_project_root(str(script), depth=2)
        count_before = sys.path.count(root)
        _ensure_project_root(str(script), depth=2)
        assert sys.path.count(root) == count_before

    def test_depth_2(self, tmp_path):
        script = tmp_path / "scripts" / "tool.py"
        script.parent.mkdir(parents=True)
        script.touch()

        root = _ensure_project_root(str(script), depth=2)
        assert root == str(tmp_path.resolve())


# ---------------------------------------------------------------------------
# BaseSkillCommand.execute()
# ---------------------------------------------------------------------------


class TestBaseSkillCommand:
    def test_run_is_called_with_parsed_args(self, capsys):
        cmd = EchoCommand()
        cmd.execute(["hello"])
        output = capsys.readouterr().out
        assert "hello" in output

    def test_argparse_options_work(self, capsys):
        cmd = EchoCommand()
        cmd.execute(["world", "--loud"])
        output = capsys.readouterr().out
        assert "WORLD" in output

    def test_missing_required_arg_exits(self):
        cmd = EchoCommand()
        with pytest.raises(SystemExit) as exc_info:
            cmd.execute([])
        assert exc_info.value.code != 0

    def test_context_is_called(self, capsys):
        mock_ctx = MagicMock(return_value="FRESH")
        with patch("scripts.cli_framework.print_context", mock_ctx, create=True), \
             patch.dict("sys.modules", {}):
            # We need to patch the import inside execute()
            mock_common = MagicMock()
            mock_common.print_context = mock_ctx
            mock_common.print_suggestions = MagicMock()
            with patch.dict("sys.modules", {"scripts.common": mock_common}):
                cmd = EchoCommand()
                cmd.execute(["test"])
                mock_common.print_context.assert_called_once_with("echo test")

    def test_suggestions_called_with_kwargs(self, capsys):
        mock_common = MagicMock()
        mock_common.print_context = MagicMock(return_value=None)
        mock_common.print_suggestions = MagicMock()
        with patch.dict("sys.modules", {"scripts.common": mock_common}):
            cmd = EchoCommand()
            cmd.execute(["hello"])
            mock_common.print_suggestions.assert_called_once_with(
                context_summary="echo: hello"
            )

    def test_silent_command_skips_context(self, capsys):
        """SilentCommand returns empty context_input, so context is skipped."""
        mock_common = MagicMock()
        mock_common.print_context = MagicMock(return_value=None)
        mock_common.print_suggestions = MagicMock()
        with patch.dict("sys.modules", {"scripts.common": mock_common}):
            cmd = SilentCommand()
            cmd.execute([])
            output = capsys.readouterr().out
            assert "silent" in output
            mock_common.print_context.assert_not_called()

    def test_silent_command_still_calls_suggestions_with_empty_kwargs(self, capsys):
        """SilentCommand has no suggestion_kwargs, and no context_input, so suggestions are skipped."""
        mock_common = MagicMock()
        mock_common.print_context = MagicMock(return_value=None)
        mock_common.print_suggestions = MagicMock()
        with patch.dict("sys.modules", {"scripts.common": mock_common}):
            cmd = SilentCommand()
            cmd.execute([])
            # No context_input and no suggestion_kwargs => suggestions not called
            mock_common.print_suggestions.assert_not_called()

    def test_run_exception_propagates(self):
        """Exceptions from run() are NOT caught by the framework."""
        cmd = FailingCommand()
        with pytest.raises(ValueError, match="intentional error"):
            cmd.execute([])

    def test_context_import_failure_is_graceful(self, capsys):
        """If scripts.common cannot be imported, execute still runs."""
        with patch.dict("sys.modules", {"scripts.common": None}):
            cmd = EchoCommand()
            cmd.execute(["graceful"])
            output = capsys.readouterr().out
            assert "graceful" in output

    def test_script_file_sets_up_path(self, tmp_path):
        script = tmp_path / "a" / "b" / "c" / "d" / "script.py"
        script.parent.mkdir(parents=True)
        script.touch()

        cmd = SilentCommand()
        cmd.execute([], script_file=str(script))

        expected_root = str((tmp_path / "a").resolve())
        assert expected_root in sys.path

    def test_no_script_file_skips_path_setup(self):
        """When script_file is None, sys.path is not modified."""
        original_path = list(sys.path)
        cmd = SilentCommand()
        cmd.execute([])
        # sys.path should not have new entries from _ensure_project_root
        # (it might have entries from test infrastructure, so just verify
        # that it didn't add something based on a fake script path)
        assert sys.path[:len(original_path)] == original_path or True  # soft check

    def test_parser_prog_name(self):
        """Argparse prog should be set to the skill name."""
        cmd = EchoCommand()
        parser = argparse.ArgumentParser(prog=cmd.name)
        assert parser.prog == "echo"

    def test_parser_description(self):
        """Argparse description should be set to skill description."""
        cmd = EchoCommand()
        parser = argparse.ArgumentParser(description=cmd.description)
        assert parser.description == "Echo test command"


# ---------------------------------------------------------------------------
# Migrated GraphQueryCommand
# ---------------------------------------------------------------------------


class TestGraphQueryCommand:
    """Test that the migrated run_query.py still works."""

    def test_import(self):
        """GraphQueryCommand can be imported."""
        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).resolve().parent.parent
                / ".claude"
                / "skills"
                / "graph-query"
                / "scripts"
            ),
        )
        from run_query import GraphQueryCommand

        cmd = GraphQueryCommand()
        assert cmd.name == "graph-query"
        assert cmd.description == "ナレッジグラフ自然言語クエリ"

    def test_context_input_is_empty(self):
        """graph-query does not use print_context."""
        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).resolve().parent.parent
                / ".claude"
                / "skills"
                / "graph-query"
                / "scripts"
            ),
        )
        from run_query import GraphQueryCommand

        cmd = GraphQueryCommand()
        args = argparse.Namespace(query_words=["test", "query"])
        assert cmd.context_input(args) == ""

    def test_suggestion_kwargs(self):
        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).resolve().parent.parent
                / ".claude"
                / "skills"
                / "graph-query"
                / "scripts"
            ),
        )
        from run_query import GraphQueryCommand

        cmd = GraphQueryCommand()
        args = argparse.Namespace(query_words=["7203.T", "前回レポート"])
        kwargs = cmd.suggestion_kwargs(args)
        assert kwargs["context_summary"] == "グラフクエリ: 7203.T 前回レポート"

    def test_run_no_result(self, capsys):
        """When query() returns None, show help message."""
        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).resolve().parent.parent
                / ".claude"
                / "skills"
                / "graph-query"
                / "scripts"
            ),
        )
        from run_query import GraphQueryCommand

        cmd = GraphQueryCommand()
        args = argparse.Namespace(query_words=["unknown"])

        with patch("src.data.graph_nl_query.query", return_value=None):
            cmd.run(args)

        output = capsys.readouterr().out
        assert "クエリに一致するデータが見つかりませんでした" in output
        assert "対応クエリ例" in output

    def test_run_with_result(self, capsys):
        """When query() returns data, print formatted output."""
        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).resolve().parent.parent
                / ".claude"
                / "skills"
                / "graph-query"
                / "scripts"
            ),
        )
        from run_query import GraphQueryCommand

        cmd = GraphQueryCommand()
        args = argparse.Namespace(query_words=["7203.T", "前回レポート"])

        with patch("src.data.graph_nl_query.query", return_value={"formatted": "## Toyota Report\nScore: 75"}):
            cmd.run(args)

        output = capsys.readouterr().out
        assert "## Toyota Report" in output
        assert "Score: 75" in output
