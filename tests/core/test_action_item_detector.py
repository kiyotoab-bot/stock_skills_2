"""Tests for src/core/action_item_detector.py (KIK-472)."""

import pytest

from src.core.action_item_detector import detect_action_items


class TestDetectFromSuggestions:
    def test_detect_exit_suggestion(self):
        suggestions = [
            {
                "emoji": "🚨",
                "title": "警戒銘柄の対応検討",
                "reason": "EXIT判定 — 7203.T の撤退を推奨",
                "command_hint": "screen-stocks --preset alpha",
                "urgency": "high",
            }
        ]
        items = detect_action_items(suggestions)
        assert len(items) == 1
        assert items[0]["trigger_type"] == "exit"
        assert items[0]["priority"] == 2
        assert "売却検討" in items[0]["title"]

    def test_detect_earnings_suggestion(self):
        suggestions = [
            {
                "emoji": "📅",
                "title": "決算イベントが近い",
                "reason": "2026-03-01 に決算発表予定",
                "command_hint": "market-research market",
                "urgency": "high",
            }
        ]
        items = detect_action_items(suggestions)
        assert len(items) == 1
        assert items[0]["trigger_type"] == "earnings"
        assert items[0]["priority"] == 2

    def test_detect_thesis_review(self):
        suggestions = [
            {
                "emoji": "🔄",
                "title": "7203.Tの投資テーゼを見直す",
                "reason": "テーゼ記録から120日経過（要再検証）",
                "command_hint": "investment-note list --symbol 7203.T",
                "urgency": "medium",
            }
        ]
        items = detect_action_items(suggestions)
        assert len(items) == 1
        assert items[0]["trigger_type"] == "thesis_review"
        assert items[0]["priority"] == 3
        assert items[0]["symbol"] == "7203.T"

    def test_detect_concern_suggestion(self):
        suggestions = [
            {
                "emoji": "⚠️",
                "title": "AAPLの懸念メモを再確認",
                "reason": "30日前に懸念を記録済み",
                "command_hint": "investment-note list --symbol AAPL",
                "urgency": "medium",
            }
        ]
        items = detect_action_items(suggestions)
        assert len(items) == 1
        assert items[0]["trigger_type"] == "concern"
        assert items[0]["symbol"] == "AAPL"

    def test_empty_suggestions(self):
        assert detect_action_items([]) == []

    def test_no_matching_pattern(self):
        suggestions = [
            {
                "emoji": "💡",
                "title": "Technologyセクターの最新リサーチがあります",
                "reason": "保有銘柄のセクターに関連する直近リサーチを検出",
                "command_hint": "market-research industry Technology",
                "urgency": "low",
            }
        ]
        items = detect_action_items(suggestions)
        assert items == []


class TestDetectFromHealthData:
    def test_detect_from_health_data(self):
        health_data = {
            "positions": [
                {
                    "symbol": "7203.T",
                    "alert": {"level": "exit", "message": "利益減少+低PER"},
                },
                {
                    "symbol": "AAPL",
                    "alert": {"level": "healthy", "message": "問題なし"},
                },
            ]
        }
        items = detect_action_items([], health_data=health_data)
        assert len(items) == 1
        assert items[0]["trigger_type"] == "exit"
        assert items[0]["symbol"] == "7203.T"
        assert items[0]["urgency"] == "high"

    def test_health_data_dedup_with_suggestions(self):
        """EXIT from health_data should not duplicate EXIT from suggestions."""
        suggestions = [
            {
                "emoji": "🚨",
                "title": "警戒銘柄の対応検討",
                "reason": "EXIT判定 — 7203.T の撤退を推奨",
                "command_hint": "stock-report 7203.T",
                "urgency": "high",
            }
        ]
        health_data = {
            "positions": [
                {
                    "symbol": "7203.T",
                    "alert": {"level": "exit", "message": "EXIT判定"},
                },
            ]
        }
        items = detect_action_items(suggestions, health_data=health_data)
        # Both map to action_<date>_exit_7203.T but dedup should keep only one
        exit_items = [i for i in items if i["trigger_type"] == "exit"]
        assert len(exit_items) == 1

    def test_health_data_no_exit(self):
        health_data = {
            "positions": [
                {"symbol": "AAPL", "alert": {"level": "healthy", "message": "OK"}},
            ]
        }
        items = detect_action_items([], health_data=health_data)
        assert items == []

    def test_health_data_none(self):
        items = detect_action_items([], health_data=None)
        assert items == []

    def test_health_data_empty_positions(self):
        items = detect_action_items([], health_data={"positions": []})
        assert items == []

    def test_health_data_no_alert_dict(self):
        """Positions without alert dict should be skipped."""
        health_data = {
            "positions": [
                {"symbol": "AAPL", "alert": "not a dict"},
            ]
        }
        items = detect_action_items([], health_data=health_data)
        assert items == []
