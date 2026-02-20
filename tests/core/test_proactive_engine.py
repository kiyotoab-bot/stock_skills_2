"""Tests for src.core.proactive_engine (KIK-435).

All graph/JSON dependencies are mocked — no real Neo4j or file I/O required.
"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    from src.core.proactive_engine import ProactiveEngine
    return ProactiveEngine()


def _date_str(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


# ---------------------------------------------------------------------------
# TestProactiveEngineTimeTriggersHealth
# ---------------------------------------------------------------------------

class TestProactiveEngineTimeTriggersHealth:
    def test_stale_health_check_triggers_suggestion(self, engine):
        """Health check >14d old → suggests running it."""
        with patch(
            "src.data.graph_query.get_last_health_check_date",
            return_value=_date_str(20),
        ):
            result = engine._check_time_triggers()
        titles = [s["title"] for s in result]
        assert "ヘルスチェックの実施" in titles

    def test_fresh_health_check_no_trigger(self, engine):
        """Health check within 7d → no health suggestion."""
        with patch(
            "src.data.graph_query.get_last_health_check_date",
            return_value=_date_str(5),
        ):
            result = engine._check_time_triggers()
        titles = [s["title"] for s in result]
        assert "ヘルスチェックの実施" not in titles

    def test_no_health_check_triggers_suggestion(self, engine):
        """No health check record (None) → suggests running it with medium urgency."""
        with patch(
            "src.data.graph_query.get_last_health_check_date",
            return_value=None,
        ):
            result = engine._check_time_triggers()
        hc = next((s for s in result if s["title"] == "ヘルスチェックの実施"), None)
        assert hc is not None
        assert hc["urgency"] == "medium"

    def test_very_stale_health_check_is_high_urgency(self, engine):
        """>30d since last health check → urgency=high."""
        with patch(
            "src.data.graph_query.get_last_health_check_date",
            return_value=_date_str(35),
        ):
            result = engine._check_time_triggers()
        hc = next((s for s in result if s["title"] == "ヘルスチェックの実施"), None)
        assert hc is not None
        assert hc["urgency"] == "high"


# ---------------------------------------------------------------------------
# TestProactiveEngineTimeTriggersThesis
# ---------------------------------------------------------------------------

class TestProactiveEngineTimeTriggersThesis:
    def test_old_thesis_note_triggers_suggestion(self, engine):
        """Thesis note >90d old → suggest review."""
        mock_notes = [{"symbol": "AAPL", "days_old": 100}]
        with patch(
            "src.data.graph_query.get_old_thesis_notes",
            return_value=mock_notes,
        ), patch(
            "src.data.graph_query.get_last_health_check_date",
            return_value=_date_str(3),
        ):
            result = engine._check_time_triggers()
        titles = [s["title"] for s in result]
        assert any("投資テーゼを見直す" in t for t in titles)

    def test_fresh_thesis_note_no_trigger(self, engine):
        """No old thesis notes → no thesis suggestion."""
        with patch(
            "src.data.graph_query.get_old_thesis_notes",
            return_value=[],
        ), patch(
            "src.data.graph_query.get_last_health_check_date",
            return_value=_date_str(3),
        ):
            result = engine._check_time_triggers()
        titles = [s["title"] for s in result]
        assert not any("投資テーゼを見直す" in t for t in titles)


# ---------------------------------------------------------------------------
# TestProactiveEngineTimeTriggersEarnings
# ---------------------------------------------------------------------------

class TestProactiveEngineTimeTriggersEarnings:
    def test_upcoming_earnings_triggers_suggestion(self, engine):
        """Earnings event within 7d → high urgency suggestion."""
        ev_date = (date.today() + timedelta(days=3)).isoformat()
        mock_events = [{"date": ev_date, "text": "トヨタ7203.T 決算発表"}]
        with patch(
            "src.data.graph_query.get_upcoming_events",
            return_value=mock_events,
        ), patch(
            "src.data.graph_query.get_last_health_check_date",
            return_value=_date_str(3),
        ), patch(
            "src.data.graph_query.get_old_thesis_notes",
            return_value=[],
        ):
            result = engine._check_time_triggers()
        earnings = next(
            (s for s in result if "決算イベント" in s["title"]), None
        )
        assert earnings is not None
        assert earnings["urgency"] == "high"

    def test_no_upcoming_events_no_trigger(self, engine):
        """No upcoming events → no earnings suggestion."""
        with patch(
            "src.data.graph_query.get_upcoming_events",
            return_value=[],
        ), patch(
            "src.data.graph_query.get_last_health_check_date",
            return_value=_date_str(3),
        ), patch(
            "src.data.graph_query.get_old_thesis_notes",
            return_value=[],
        ):
            result = engine._check_time_triggers()
        titles = [s["title"] for s in result]
        assert not any("決算イベント" in t for t in titles)

    def test_earnings_title_contains_date(self, engine):
        """Earnings suggestion should include the event date in reason."""
        ev_date = (date.today() + timedelta(days=2)).isoformat()
        mock_events = [{"date": ev_date, "text": "NVDA 決算"}]
        with patch(
            "src.data.graph_query.get_upcoming_events",
            return_value=mock_events,
        ), patch(
            "src.data.graph_query.get_last_health_check_date",
            return_value=_date_str(3),
        ), patch(
            "src.data.graph_query.get_old_thesis_notes",
            return_value=[],
        ):
            result = engine._check_time_triggers()
        earnings = next((s for s in result if "決算イベント" in s["title"]), None)
        assert earnings is not None
        assert ev_date in earnings["reason"]


# ---------------------------------------------------------------------------
# TestProactiveEngineStateTriggers
# ---------------------------------------------------------------------------

class TestProactiveEngineStateTriggers:
    def test_recurring_pick_triggers_suggestion(self, engine):
        """Stock appearing 3+ times in screening → suggest deeper analysis."""
        mock_picks = [{"symbol": "NVDA", "count": 5}]
        with patch(
            "src.data.graph_query.get_recurring_picks",
            return_value=mock_picks,
        ), patch(
            "src.data.graph_query.get_concern_notes",
            return_value=[],
        ):
            result = engine._check_state_triggers()
        titles = [s["title"] for s in result]
        assert any("NVDA" in t and "詳細分析" in t for t in titles)

    def test_single_pick_no_trigger(self, engine):
        """Stock with count < 3 → not returned by mock (empty list)."""
        with patch(
            "src.data.graph_query.get_recurring_picks",
            return_value=[],
        ), patch(
            "src.data.graph_query.get_concern_notes",
            return_value=[],
        ):
            result = engine._check_state_triggers()
        titles = [s["title"] for s in result]
        assert not any("詳細分析" in t for t in titles)

    def test_concern_note_triggers_suggestion(self, engine):
        """Concern note exists → suggest re-review."""
        mock_concerns = [{"symbol": "7203.T", "days_old": 15}]
        with patch(
            "src.data.graph_query.get_recurring_picks",
            return_value=[],
        ), patch(
            "src.data.graph_query.get_concern_notes",
            return_value=mock_concerns,
        ):
            result = engine._check_state_triggers()
        concern = next(
            (s for s in result if "懸念メモ" in s["title"]), None
        )
        assert concern is not None
        assert "7203.T" in concern["title"]

    def test_no_concern_note_no_trigger(self, engine):
        """No concern notes → no concern suggestion."""
        with patch(
            "src.data.graph_query.get_recurring_picks",
            return_value=[],
        ), patch(
            "src.data.graph_query.get_concern_notes",
            return_value=[],
        ):
            result = engine._check_state_triggers()
        titles = [s["title"] for s in result]
        assert not any("懸念メモ" in t for t in titles)


# ---------------------------------------------------------------------------
# TestProactiveEngineContextualTriggers
# ---------------------------------------------------------------------------

class TestProactiveEngineContextualTriggers:
    def test_sector_match_triggers_suggestion(self, engine):
        """Research sector matches held stock → low urgency suggestion."""
        mock_research = [{"id": "r1", "type": "Research", "target": "Technology", "summary": "..."}]
        mock_holdings = [{"symbol": "AAPL", "sector": "Technology"}]
        with patch(
            "src.data.graph_query.get_industry_research_for_linking",
            return_value=mock_research,
        ), patch(
            "src.data.graph_query.get_current_holdings",
            return_value=mock_holdings,
        ):
            result = engine._check_contextual_triggers(sector="Technology")
        assert len(result) == 1
        assert result[0]["urgency"] == "low"
        assert "Technology" in result[0]["title"]

    def test_no_sector_no_trigger(self, engine):
        """Empty sector → skip contextual check entirely."""
        result = engine._check_contextual_triggers(sector="")
        assert result == []

    def test_sector_not_in_holdings_no_trigger(self, engine):
        """Research sector present but not held → no suggestion."""
        mock_research = [{"id": "r1", "type": "Research", "target": "Healthcare", "summary": "..."}]
        mock_holdings = [{"symbol": "AAPL", "sector": "Technology"}]
        with patch(
            "src.data.graph_query.get_industry_research_for_linking",
            return_value=mock_research,
        ), patch(
            "src.data.graph_query.get_current_holdings",
            return_value=mock_holdings,
        ):
            result = engine._check_contextual_triggers(sector="Healthcare")
        assert result == []


# ---------------------------------------------------------------------------
# TestFormatSuggestions
# ---------------------------------------------------------------------------

class TestFormatSuggestions:
    def test_format_empty_returns_empty_string(self):
        from src.core.proactive_engine import format_suggestions
        assert format_suggestions([]) == ""

    def test_format_suggestions_contains_titles(self):
        from src.core.proactive_engine import format_suggestions
        suggestions = [
            {
                "emoji": "📋",
                "title": "ヘルスチェックの実施",
                "reason": "20日経過",
                "command_hint": "portfolio health",
                "urgency": "medium",
            }
        ]
        output = format_suggestions(suggestions)
        assert "ヘルスチェックの実施" in output
        assert "portfolio health" in output
        assert "次のアクション提案" in output

    def test_get_suggestions_returns_max_3(self):
        """get_suggestions() never returns more than 3 items."""
        from src.core.proactive_engine import get_suggestions

        # Inject many triggers via patches
        mock_hc = _date_str(60)
        mock_thesis = [{"symbol": "AAPL", "days_old": 120}, {"symbol": "NVDA", "days_old": 100}]
        ev_date = (date.today() + timedelta(days=2)).isoformat()
        mock_events = [{"symbol": "7203.T", "event_date": ev_date}]
        mock_picks = [{"symbol": "TSM", "count": 5}]
        mock_concerns = [{"symbol": "MSFT", "days_old": 10}]

        with patch("src.data.graph_query.get_last_health_check_date", return_value=mock_hc), \
             patch("src.data.graph_query.get_old_thesis_notes", return_value=mock_thesis), \
             patch("src.data.graph_query.get_upcoming_events", return_value=mock_events), \
             patch("src.data.graph_query.get_recurring_picks", return_value=mock_picks), \
             patch("src.data.graph_query.get_concern_notes", return_value=mock_concerns):
            result = get_suggestions()

        assert len(result) <= 3
