"""Tests for src/data/screen_annotator.py (KIK-418/419)."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.screen_annotator import (
    MARKER_CONCERN,
    MARKER_LESSON,
    MARKER_WATCH,
    _build_markers,
    _build_note_summary,
    _load_notes_from_json,
    _load_sells_from_json,
    annotate_results,
    get_notes_for_symbols,
    get_recent_sells,
)


# ---------------------------------------------------------------------------
# _build_markers
# ---------------------------------------------------------------------------


class TestBuildMarkers:
    def test_concern_marker(self):
        notes = [{"type": "concern", "content": "利益減少傾向"}]
        assert _build_markers(notes) == MARKER_CONCERN

    def test_lesson_marker(self):
        notes = [{"type": "lesson", "content": "損切りが遅かった"}]
        assert _build_markers(notes) == MARKER_LESSON

    def test_watch_marker_with_keyword(self):
        notes = [{"type": "observation", "content": "今回は見送りが良いかも"}]
        assert _build_markers(notes) == MARKER_WATCH

    def test_observation_without_keyword_no_marker(self):
        notes = [{"type": "observation", "content": "良い決算だった"}]
        assert _build_markers(notes) == ""

    def test_multiple_markers(self):
        notes = [
            {"type": "concern", "content": "リスク高い"},
            {"type": "lesson", "content": "学び"},
        ]
        result = _build_markers(notes)
        assert MARKER_CONCERN in result
        assert MARKER_LESSON in result

    def test_no_duplicate_markers(self):
        notes = [
            {"type": "concern", "content": "懸念1"},
            {"type": "concern", "content": "懸念2"},
        ]
        result = _build_markers(notes)
        assert result.count(MARKER_CONCERN) == 1

    def test_empty_notes(self):
        assert _build_markers([]) == ""


# ---------------------------------------------------------------------------
# _build_note_summary
# ---------------------------------------------------------------------------


class TestBuildNoteSummary:
    def test_short_content(self):
        notes = [{"type": "concern", "content": "利益減少"}]
        assert "[concern] 利益減少" in _build_note_summary(notes)

    def test_long_content_truncated(self):
        notes = [{"type": "lesson", "content": "A" * 60}]
        result = _build_note_summary(notes)
        assert "..." in result
        assert len(result) < 80

    def test_max_notes_limit(self):
        notes = [
            {"type": "concern", "content": "懸念1"},
            {"type": "lesson", "content": "学び1"},
            {"type": "concern", "content": "懸念2"},
        ]
        result = _build_note_summary(notes, max_notes=2)
        assert "懸念2" not in result

    def test_empty(self):
        assert _build_note_summary([]) == ""


# ---------------------------------------------------------------------------
# get_recent_sells
# ---------------------------------------------------------------------------


class TestGetRecentSells:
    def test_neo4j_returns_data(self):
        with patch("src.data.graph_query.get_recent_sells_batch", return_value={"7203.T": "2025-01-15"}):
            result = get_recent_sells(days=90)
        assert result == {"7203.T": "2025-01-15"}

    def test_neo4j_unavailable_falls_to_json(self):
        """When Neo4j returns empty, falls back to JSON."""
        with patch("src.data.graph_query.get_recent_sells_batch", return_value={}):
            with patch("src.data.screen_annotator._load_sells_from_json", return_value={"AAPL": "2025-02-01"}):
                result = get_recent_sells(days=90)
        assert result == {"AAPL": "2025-02-01"}

    def test_neo4j_exception_falls_to_json(self):
        """When Neo4j raises, falls back to JSON."""
        with patch("src.data.graph_query.get_recent_sells_batch", side_effect=Exception("No Neo4j")):
            with patch("src.data.screen_annotator._load_sells_from_json", return_value={"AAPL": "2025-02-01"}):
                result = get_recent_sells(days=90)
        assert result == {"AAPL": "2025-02-01"}

    def test_empty_when_no_data(self):
        with patch("src.data.graph_query.get_recent_sells_batch", return_value={}):
            with patch("src.data.screen_annotator._load_sells_from_json", return_value={}):
                result = get_recent_sells()
        assert result == {}


# ---------------------------------------------------------------------------
# _load_sells_from_json
# ---------------------------------------------------------------------------


class TestLoadSellsFromJson:
    def test_reads_sell_records(self, tmp_path, monkeypatch):
        trade_dir = tmp_path / "data" / "history" / "trade"
        trade_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)

        sell = {"trade_type": "sell", "date": "2025-02-10", "symbol": "7203.T"}
        (trade_dir / "sell.json").write_text(json.dumps(sell), encoding="utf-8")

        result = _load_sells_from_json("2025-01-01")
        assert result == {"7203.T": "2025-02-10"}

    def test_ignores_buy_records(self, tmp_path, monkeypatch):
        trade_dir = tmp_path / "data" / "history" / "trade"
        trade_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)

        buy = {"trade_type": "buy", "date": "2025-02-10", "symbol": "AAPL"}
        (trade_dir / "buy.json").write_text(json.dumps(buy), encoding="utf-8")

        result = _load_sells_from_json("2025-01-01")
        assert result == {}

    def test_respects_cutoff(self, tmp_path, monkeypatch):
        trade_dir = tmp_path / "data" / "history" / "trade"
        trade_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)

        old_sell = {"trade_type": "sell", "date": "2024-01-01", "symbol": "OLD"}
        (trade_dir / "old.json").write_text(json.dumps(old_sell), encoding="utf-8")

        result = _load_sells_from_json("2025-01-01")
        assert result == {}

    def test_no_trade_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _load_sells_from_json("2025-01-01")
        assert result == {}


# ---------------------------------------------------------------------------
# get_notes_for_symbols
# ---------------------------------------------------------------------------


class TestGetNotesForSymbols:
    def test_empty_symbols(self):
        assert get_notes_for_symbols([]) == {}

    def test_json_fallback(self):
        mock_notes = [
            {"symbol": "7203.T", "type": "concern", "content": "利益減少", "date": "2025-01-01"},
            {"symbol": "AAPL", "type": "lesson", "content": "損切り遅い", "date": "2025-01-02"},
            {"symbol": "7203.T", "type": "thesis", "content": "テーゼ", "date": "2025-01-01"},
        ]
        with patch("src.data.screen_annotator._load_notes_from_json") as mock_json:
            mock_json.return_value = {
                "7203.T": [{"type": "concern", "content": "利益減少", "date": "2025-01-01"}],
                "AAPL": [{"type": "lesson", "content": "損切り遅い", "date": "2025-01-02"}],
            }
            with patch(
                "src.data.screen_annotator.get_notes_for_symbols_batch",
                side_effect=Exception("No Neo4j"),
                create=True,
            ):
                result = get_notes_for_symbols(["7203.T", "AAPL"])
        assert "7203.T" in result
        assert "AAPL" in result


# ---------------------------------------------------------------------------
# _load_notes_from_json
# ---------------------------------------------------------------------------


class TestLoadNotesFromJson:
    def test_loads_matching_notes(self):
        mock_notes = [
            {"symbol": "7203.T", "type": "concern", "content": "Bad", "date": "2025-01-01"},
            {"symbol": "7203.T", "type": "thesis", "content": "Good", "date": "2025-01-01"},
            {"symbol": "AAPL", "type": "lesson", "content": "Learn", "date": "2025-01-02"},
            {"symbol": "MSFT", "type": "concern", "content": "Not included", "date": "2025-01-03"},
        ]
        with patch("src.data.note_manager.load_notes", return_value=mock_notes):
            result = _load_notes_from_json(["7203.T", "AAPL"], ["concern", "lesson"])
        assert "7203.T" in result
        assert len(result["7203.T"]) == 1  # Only concern, not thesis
        assert result["7203.T"][0]["type"] == "concern"
        assert "AAPL" in result
        assert "MSFT" not in result


# ---------------------------------------------------------------------------
# annotate_results
# ---------------------------------------------------------------------------


class TestAnnotateResults:
    def test_excludes_sold_stocks(self):
        results = [
            {"symbol": "7203.T", "name": "Toyota"},
            {"symbol": "AAPL", "name": "Apple"},
        ]
        with patch("src.data.screen_annotator.get_recent_sells", return_value={"AAPL": "2025-02-01"}):
            with patch("src.data.screen_annotator.get_notes_for_symbols", return_value={}):
                annotated, excluded = annotate_results(results)
        assert excluded == 1
        assert len(annotated) == 1
        assert annotated[0]["symbol"] == "7203.T"

    def test_adds_note_markers(self):
        results = [{"symbol": "7203.T", "name": "Toyota"}]
        notes = {"7203.T": [{"type": "concern", "content": "利益減少", "date": "2025-01-01"}]}
        with patch("src.data.screen_annotator.get_recent_sells", return_value={}):
            with patch("src.data.screen_annotator.get_notes_for_symbols", return_value=notes):
                annotated, excluded = annotate_results(results)
        assert excluded == 0
        assert MARKER_CONCERN in annotated[0]["_note_markers"]

    def test_empty_results(self):
        annotated, excluded = annotate_results([])
        assert annotated == []
        assert excluded == 0

    def test_graceful_degradation_on_sell_error(self):
        results = [{"symbol": "7203.T"}]
        with patch("src.data.screen_annotator.get_recent_sells", side_effect=Exception("fail")):
            with patch("src.data.screen_annotator.get_notes_for_symbols", return_value={}):
                annotated, excluded = annotate_results(results)
        assert len(annotated) == 1
        assert excluded == 0

    def test_graceful_degradation_on_notes_error(self):
        results = [{"symbol": "7203.T"}]
        with patch("src.data.screen_annotator.get_recent_sells", return_value={}):
            with patch("src.data.screen_annotator.get_notes_for_symbols", side_effect=Exception("fail")):
                annotated, excluded = annotate_results(results)
        assert len(annotated) == 1
        assert annotated[0]["_note_markers"] == ""

    def test_mixed_sold_and_noted(self):
        results = [
            {"symbol": "SOLD1"},
            {"symbol": "NOTED"},
            {"symbol": "CLEAN"},
        ]
        sells = {"SOLD1": "2025-02-01"}
        notes = {"NOTED": [{"type": "lesson", "content": "学び", "date": "2025-01-01"}]}
        with patch("src.data.screen_annotator.get_recent_sells", return_value=sells):
            with patch("src.data.screen_annotator.get_notes_for_symbols", return_value=notes):
                annotated, excluded = annotate_results(results)
        assert excluded == 1
        assert len(annotated) == 2
        assert annotated[0]["symbol"] == "NOTED"
        assert MARKER_LESSON in annotated[0]["_note_markers"]
        assert annotated[1]["symbol"] == "CLEAN"
        assert annotated[1]["_note_markers"] == ""

    def test_no_symbols_in_results(self):
        results = [{"name": "NoSymbol"}]
        annotated, excluded = annotate_results(results)
        assert len(annotated) == 1
        assert excluded == 0
