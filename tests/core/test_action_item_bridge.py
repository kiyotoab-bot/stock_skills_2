"""Tests for src/core/action_item_bridge.py (KIK-472)."""

from unittest.mock import MagicMock, patch

import pytest

from src.core.action_item_bridge import process_action_items


class TestProcessActionItems:
    def _exit_suggestions(self):
        return [
            {
                "emoji": "🚨",
                "title": "警戒銘柄の対応検討",
                "reason": "EXIT判定 — 7203.T の撤退を推奨",
                "command_hint": "stock-report 7203.T",
                "urgency": "high",
            }
        ]

    @patch("src.core.action_item_bridge._link_linear_to_neo4j")
    @patch("src.core.action_item_bridge._create_linear_issue", return_value=None)
    @patch("src.core.action_item_bridge._save_to_neo4j", return_value=True)
    @patch("src.core.action_item_bridge._is_duplicate_neo4j", return_value=False)
    def test_process_creates_neo4j_node(self, mock_dedup, mock_save, mock_linear, mock_link):
        results = process_action_items(self._exit_suggestions())
        assert len(results) == 1
        assert results[0]["neo4j_saved"] is True
        mock_save.assert_called_once()

    @patch("src.core.action_item_bridge._link_linear_to_neo4j")
    @patch("src.core.action_item_bridge._create_linear_issue")
    @patch("src.core.action_item_bridge._save_to_neo4j", return_value=True)
    @patch("src.core.action_item_bridge._is_duplicate_neo4j", return_value=False)
    def test_process_creates_linear_issue(self, mock_dedup, mock_save, mock_linear, mock_link):
        mock_linear.return_value = {
            "id": "issue-1",
            "identifier": "KIK-999",
            "url": "https://linear.app/issue/KIK-999",
        }
        results = process_action_items(self._exit_suggestions())
        assert len(results) == 1
        assert results[0]["linear_issue"] is not None
        assert results[0]["linear_issue"]["identifier"] == "KIK-999"
        mock_link.assert_called_once()

    @patch("src.core.action_item_bridge._link_linear_to_neo4j")
    @patch("src.core.action_item_bridge._create_linear_issue", return_value=None)
    @patch("src.core.action_item_bridge._save_to_neo4j", return_value=True)
    @patch("src.core.action_item_bridge._is_duplicate_neo4j", return_value=False)
    def test_process_skips_linear_when_disabled(self, mock_dedup, mock_save, mock_linear, mock_link):
        results = process_action_items(self._exit_suggestions())
        assert len(results) == 1
        assert results[0]["linear_issue"] is None
        mock_link.assert_not_called()

    @patch("src.core.action_item_bridge._save_to_neo4j")
    @patch("src.core.action_item_bridge._is_duplicate_neo4j", return_value=True)
    def test_dedup_skips_existing(self, mock_dedup, mock_save):
        results = process_action_items(self._exit_suggestions())
        assert len(results) == 0
        mock_save.assert_not_called()

    def test_graceful_degradation_empty_suggestions(self):
        results = process_action_items([])
        assert results == []

    @patch("src.core.action_item_bridge._create_linear_issue", return_value=None)
    @patch("src.core.action_item_bridge._save_to_neo4j", side_effect=Exception("boom"))
    @patch("src.core.action_item_bridge._is_duplicate_neo4j", return_value=False)
    def test_graceful_degradation_exception(self, mock_dedup, mock_save, mock_linear):
        """Even if save raises, process should not crash."""
        results = process_action_items(self._exit_suggestions())
        # Per-item exception is caught, item is skipped
        assert results == []

    def test_no_matching_items(self):
        """Non-matching suggestions produce no action items."""
        suggestions = [
            {
                "emoji": "💡",
                "title": "セクターリサーチ",
                "reason": "保有銘柄関連",
                "command_hint": "market-research",
                "urgency": "low",
            }
        ]
        results = process_action_items(suggestions)
        assert results == []


class TestProcessWithHealthData:
    @patch("src.core.action_item_bridge._link_linear_to_neo4j")
    @patch("src.core.action_item_bridge._create_linear_issue", return_value=None)
    @patch("src.core.action_item_bridge._save_to_neo4j", return_value=True)
    @patch("src.core.action_item_bridge._is_duplicate_neo4j", return_value=False)
    def test_process_with_health_data_exit(self, mock_dedup, mock_save, mock_linear, mock_link):
        health_data = {
            "positions": [
                {
                    "symbol": "NVDA",
                    "alert": {"level": "exit", "message": "EXIT判定"},
                },
            ]
        }
        results = process_action_items([], health_data=health_data)
        assert len(results) == 1
        assert results[0]["symbol"] == "NVDA"
        assert results[0]["neo4j_saved"] is True

    @patch("src.core.action_item_bridge._link_linear_to_neo4j")
    @patch("src.core.action_item_bridge._create_linear_issue", return_value=None)
    @patch("src.core.action_item_bridge._save_to_neo4j", return_value=True)
    @patch("src.core.action_item_bridge._is_duplicate_neo4j", return_value=False)
    def test_source_node_id_from_health_data(self, mock_dedup, mock_save, mock_linear, mock_link):
        """KIK-489: source_node_id should be passed to _save_to_neo4j when health_data is present."""
        health_data = {
            "date": "2026-02-26",
            "positions": [
                {
                    "symbol": "NVDA",
                    "alert": {"level": "exit", "message": "EXIT判定"},
                },
            ]
        }
        results = process_action_items([], health_data=health_data)
        assert len(results) == 1
        call_kwargs = mock_save.call_args[1]
        assert call_kwargs["source_node_id"] == "health_2026-02-26"

    @patch("src.core.action_item_bridge._link_linear_to_neo4j")
    @patch("src.core.action_item_bridge._create_linear_issue", return_value=None)
    @patch("src.core.action_item_bridge._save_to_neo4j", return_value=True)
    @patch("src.core.action_item_bridge._is_duplicate_neo4j", return_value=False)
    def test_no_source_node_id_without_health_data(self, mock_dedup, mock_save, mock_linear, mock_link):
        """KIK-489: source_node_id should be None when no health_data."""
        suggestions = [
            {
                "emoji": "🚨",
                "title": "警戒銘柄の対応検討",
                "reason": "EXIT判定 — 7203.T の撤退を推奨",
                "command_hint": "stock-report 7203.T",
                "urgency": "high",
            }
        ]
        results = process_action_items(suggestions)
        assert len(results) == 1
        call_kwargs = mock_save.call_args[1]
        assert call_kwargs["source_node_id"] is None
