"""Tests for grok_client.py research functions (KIK-367).

Tests for _call_grok_api, _parse_json_response, _is_japanese_stock,
_contains_japanese, search_stock_deep, search_industry, search_market.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.data.grok_client import (
    _call_grok_api,
    _parse_json_response,
    _is_japanese_stock,
    _contains_japanese,
    search_stock_deep,
    search_industry,
    search_market,
    EMPTY_STOCK_DEEP,
    EMPTY_INDUSTRY,
    EMPTY_MARKET,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_grok_response(text: str) -> MagicMock:
    """Build a mock HTTP response that returns *text* as API output."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": text}
                ],
            }
        ]
    }
    return mock_response


@pytest.fixture(autouse=True)
def _reset_error_warned():
    """Reset the module-level _error_warned flag before each test."""
    from src.data import grok_client
    grok_client._error_warned[0] = False
    yield


# ===================================================================
# _call_grok_api
# ===================================================================

class TestCallGrokApi:

    def test_no_api_key(self, monkeypatch):
        """Returns empty string when XAI_API_KEY is not set."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        result = _call_grok_api("test prompt")
        assert result == ""

    @patch("src.data.grok_client.requests.post")
    def test_successful_response(self, mock_post, monkeypatch):
        """Returns text content from a successful API response."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_post.return_value = _make_grok_response("Hello from Grok")

        result = _call_grok_api("test prompt")
        assert result == "Hello from Grok"

    @patch("src.data.grok_client.requests.post")
    def test_api_error(self, mock_post, monkeypatch):
        """Returns empty string on HTTP 500."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        result = _call_grok_api("test prompt")
        assert result == ""

    @patch("src.data.grok_client.requests.post")
    def test_timeout(self, mock_post, monkeypatch):
        """Returns empty string on timeout."""
        import requests as req
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_post.side_effect = req.exceptions.Timeout("Timed out")

        result = _call_grok_api("test prompt", timeout=1)
        assert result == ""

    @patch("src.data.grok_client.requests.post")
    def test_request_exception(self, mock_post, monkeypatch):
        """Returns empty string on general request exception."""
        import requests as req
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_post.side_effect = req.exceptions.ConnectionError("Connection refused")

        result = _call_grok_api("test prompt")
        assert result == ""


# ===================================================================
# _parse_json_response
# ===================================================================

class TestParseJsonResponse:

    def test_valid_json(self):
        """Parses a clean JSON string."""
        text = '{"key": "value", "count": 42}'
        result = _parse_json_response(text)
        assert result == {"key": "value", "count": 42}

    def test_json_with_surrounding_text(self):
        """Extracts JSON from text with surrounding content."""
        text = 'Here is the result: {"key": "value"} and more text'
        result = _parse_json_response(text)
        assert result == {"key": "value"}

    def test_invalid_json(self):
        """Returns empty dict for text with no valid JSON."""
        result = _parse_json_response("This is just plain text")
        assert result == {}

    def test_empty_string(self):
        """Returns empty dict for empty string."""
        result = _parse_json_response("")
        assert result == {}


# ===================================================================
# _is_japanese_stock
# ===================================================================

class TestIsJapaneseStock:

    def test_t_suffix(self):
        """7203.T is a Japanese stock."""
        assert _is_japanese_stock("7203.T") is True

    def test_s_suffix(self):
        """1234.S is a Japanese stock (Sapporo exchange)."""
        assert _is_japanese_stock("1234.S") is True

    def test_us_stock(self):
        """AAPL is not a Japanese stock."""
        assert _is_japanese_stock("AAPL") is False

    def test_sg_stock(self):
        """D05.SI is not a Japanese stock."""
        assert _is_japanese_stock("D05.SI") is False


# ===================================================================
# _contains_japanese
# ===================================================================

class TestContainsJapanese:

    def test_japanese_text(self):
        """Text with kanji returns True."""
        assert _contains_japanese("半導体") is True

    def test_english_text(self):
        """English-only text returns False."""
        assert _contains_japanese("semiconductor") is False

    def test_mixed(self):
        """Mixed text with Japanese chars returns True."""
        assert _contains_japanese("AI半導体") is True


# ===================================================================
# search_stock_deep
# ===================================================================

class TestSearchStockDeep:

    def test_no_api_key(self, monkeypatch):
        """Returns EMPTY_STOCK_DEEP when API key is not set."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        result = search_stock_deep("AAPL")
        assert result["recent_news"] == []
        assert result["catalysts"] == {"positive": [], "negative": []}
        assert result["x_sentiment"]["score"] == 0.0
        assert result["raw_response"] == ""

    @patch("src.data.grok_client.requests.post")
    def test_successful_response(self, mock_post, monkeypatch):
        """Parses a successful deep research response."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")

        json_content = json.dumps({
            "recent_news": ["Earnings beat expectations", "New product launch"],
            "catalysts": {
                "positive": ["AI revenue growth"],
                "negative": ["Trade war risk"],
            },
            "analyst_views": ["Buy rating from Goldman"],
            "x_sentiment": {
                "score": 0.7,
                "summary": "Bullish sentiment",
                "key_opinions": ["Strong buy signals"],
            },
            "competitive_notes": ["Market leader in segment"],
        })

        mock_post.return_value = _make_grok_response(json_content)

        result = search_stock_deep("AAPL", "Apple Inc.")
        assert len(result["recent_news"]) == 2
        assert result["catalysts"]["positive"] == ["AI revenue growth"]
        assert result["catalysts"]["negative"] == ["Trade war risk"]
        assert result["analyst_views"] == ["Buy rating from Goldman"]
        assert result["x_sentiment"]["score"] == 0.7
        assert result["x_sentiment"]["summary"] == "Bullish sentiment"
        assert result["competitive_notes"] == ["Market leader in segment"]

    @patch("src.data.grok_client.requests.post")
    def test_japanese_stock_prompt(self, mock_post, monkeypatch):
        """Japanese stock uses Japanese prompt."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_post.return_value = _make_grok_response("{}")

        search_stock_deep("7203.T", "Toyota")

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        prompt = payload["input"]
        assert "調査" in prompt or "7203.T" in prompt

    @patch("src.data.grok_client.requests.post")
    def test_us_stock_prompt(self, mock_post, monkeypatch):
        """US stock uses English prompt."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_post.return_value = _make_grok_response("{}")

        search_stock_deep("AAPL", "Apple Inc.")

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        prompt = payload["input"]
        assert "Research" in prompt

    @patch("src.data.grok_client.requests.post")
    def test_malformed_response(self, mock_post, monkeypatch):
        """Malformed JSON sets raw_response but leaves data empty."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_post.return_value = _make_grok_response("This is not JSON at all")

        result = search_stock_deep("AAPL")
        assert result["raw_response"] == "This is not JSON at all"
        assert result["recent_news"] == []
        assert result["catalysts"] == {"positive": [], "negative": []}


# ===================================================================
# search_industry
# ===================================================================

class TestSearchIndustry:

    def test_no_api_key(self, monkeypatch):
        """Returns EMPTY_INDUSTRY when API key is not set."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        result = search_industry("半導体")
        assert result["trends"] == []
        assert result["key_players"] == []
        assert result["raw_response"] == ""

    @patch("src.data.grok_client.requests.post")
    def test_successful_response(self, mock_post, monkeypatch):
        """Parses a successful industry research response."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")

        json_content = json.dumps({
            "trends": ["AI chip demand surging"],
            "key_players": [
                {"name": "TSMC", "ticker": "TSM", "note": "Foundry leader"}
            ],
            "growth_drivers": ["Data center expansion"],
            "risks": ["Geopolitical tension"],
            "regulatory": ["US export controls"],
            "investor_focus": ["CAPEX cycle"],
        })

        mock_post.return_value = _make_grok_response(json_content)

        result = search_industry("semiconductor")
        assert result["trends"] == ["AI chip demand surging"]
        assert len(result["key_players"]) == 1
        assert result["key_players"][0]["name"] == "TSMC"
        assert result["growth_drivers"] == ["Data center expansion"]
        assert result["risks"] == ["Geopolitical tension"]
        assert result["regulatory"] == ["US export controls"]
        assert result["investor_focus"] == ["CAPEX cycle"]

    @patch("src.data.grok_client.requests.post")
    def test_japanese_theme(self, mock_post, monkeypatch):
        """Japanese theme uses Japanese prompt."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_post.return_value = _make_grok_response("{}")

        search_industry("半導体")

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        prompt = payload["input"]
        assert "半導体" in prompt
        assert "業界" in prompt or "テーマ" in prompt

    @patch("src.data.grok_client.requests.post")
    def test_english_theme(self, mock_post, monkeypatch):
        """English theme uses English prompt."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_post.return_value = _make_grok_response("{}")

        search_industry("semiconductor")

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        prompt = payload["input"]
        assert "Research" in prompt


# ===================================================================
# search_market
# ===================================================================

class TestSearchMarket:

    def test_no_api_key(self, monkeypatch):
        """Returns EMPTY_MARKET when API key is not set."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        result = search_market("日経平均")
        assert result["price_action"] == ""
        assert result["macro_factors"] == []
        assert result["sentiment"]["score"] == 0.0
        assert result["raw_response"] == ""

    @patch("src.data.grok_client.requests.post")
    def test_successful_response(self, mock_post, monkeypatch):
        """Parses a successful market research response."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")

        json_content = json.dumps({
            "price_action": "Nikkei rose 1.5% on strong earnings",
            "macro_factors": ["BOJ rate decision", "Yen weakness"],
            "sentiment": {"score": 0.4, "summary": "Cautiously optimistic"},
            "upcoming_events": ["GDP release on Friday"],
            "sector_rotation": ["From defensive to cyclical"],
        })

        mock_post.return_value = _make_grok_response(json_content)

        result = search_market("日経平均")
        assert result["price_action"] == "Nikkei rose 1.5% on strong earnings"
        assert len(result["macro_factors"]) == 2
        assert result["sentiment"]["score"] == 0.4
        assert result["sentiment"]["summary"] == "Cautiously optimistic"
        assert result["upcoming_events"] == ["GDP release on Friday"]
        assert result["sector_rotation"] == ["From defensive to cyclical"]
