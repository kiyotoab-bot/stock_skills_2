"""Tests for graph-query skill script (KIK-518)."""

import argparse
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add skill script directory to path
_SKILL_SCRIPTS = Path(__file__).resolve().parent.parent.parent / ".claude" / "skills" / "graph-query" / "scripts"
if str(_SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SKILL_SCRIPTS))


class TestGraphQueryArgParsing:
    """Test argument parsing for the graph-query skill."""

    def test_single_word_query(self):
        from run_query import GraphQueryCommand

        cmd = GraphQueryCommand()
        parser = argparse.ArgumentParser()
        cmd.configure_parser(parser)
        args = parser.parse_args(["市況"])
        assert args.query_words == ["市況"]

    def test_multi_word_query(self):
        from run_query import GraphQueryCommand

        cmd = GraphQueryCommand()
        parser = argparse.ArgumentParser()
        cmd.configure_parser(parser)
        args = parser.parse_args(["7203.T", "前回レポート"])
        assert args.query_words == ["7203.T", "前回レポート"]

    def test_no_args_exits(self):
        from run_query import GraphQueryCommand

        cmd = GraphQueryCommand()
        with pytest.raises(SystemExit):
            cmd.execute([])


class TestGraphQueryRun:
    """Test run() with mocked dependencies."""

    def test_no_result_shows_help(self, capsys):
        from run_query import GraphQueryCommand

        cmd = GraphQueryCommand()
        args = argparse.Namespace(query_words=["unknown"])

        with patch("src.data.graph_nl_query.query", return_value=None):
            cmd.run(args)

        output = capsys.readouterr().out
        assert "クエリに一致するデータが見つかりませんでした" in output
        assert "対応クエリ例" in output
        assert "7203.T" in output

    def test_result_prints_formatted(self, capsys):
        from run_query import GraphQueryCommand

        cmd = GraphQueryCommand()
        args = argparse.Namespace(query_words=["7203.T", "取引履歴"])

        mock_result = {
            "formatted": "## 取引履歴\n- 2024-01-15: BOUGHT 100株 @2850"
        }
        with patch("src.data.graph_nl_query.query", return_value=mock_result):
            cmd.run(args)

        output = capsys.readouterr().out
        assert "## 取引履歴" in output
        assert "BOUGHT" in output


class TestGraphQuerySuggestions:
    """Test suggestion_kwargs()."""

    def test_short_query(self):
        from run_query import GraphQueryCommand

        cmd = GraphQueryCommand()
        args = argparse.Namespace(query_words=["AAPL"])
        kwargs = cmd.suggestion_kwargs(args)
        assert kwargs["context_summary"] == "グラフクエリ: AAPL"

    def test_long_query_truncated(self):
        from run_query import GraphQueryCommand

        cmd = GraphQueryCommand()
        long_words = [f"word{i}" for i in range(20)]
        args = argparse.Namespace(query_words=long_words)
        kwargs = cmd.suggestion_kwargs(args)
        assert len(kwargs["context_summary"]) <= len("グラフクエリ: ") + 60
