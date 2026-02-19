"""Tests for src/data/perplexity_client.py (KIK-426)."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.data.perplexity_client import (
    is_available,
    search_stock,
    search_industry,
    search_market,
    search_business,
    _call_api,
    _parse_json_response,
    _build_stock_messages,
    _build_industry_messages,
    _build_market_messages,
    _build_business_messages,
    _error_warned,
    EMPTY_STOCK,
    EMPTY_INDUSTRY,
    EMPTY_MARKET,
    EMPTY_BUSINESS,
)


@pytest.fixture(autouse=True)
def _reset_error_warned():
    """Reset module-level _error_warned before each test."""
    _error_warned[0] = False
    yield


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_with_key(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
        assert is_available() is True

    def test_without_key(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        assert is_available() is False

    def test_empty_key(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "")
        assert is_available() is False


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    def test_valid_json(self):
        text = 'Some text {"key": "value"} more text'
        assert _parse_json_response(text) == {"key": "value"}

    def test_invalid_json(self):
        assert _parse_json_response("no json here") == {}

    def test_empty_string(self):
        assert _parse_json_response("") == {}

    def test_nested_json(self):
        text = '{"a": {"b": [1, 2]}}'
        result = _parse_json_response(text)
        assert result["a"]["b"] == [1, 2]


# ---------------------------------------------------------------------------
# _build_*_messages
# ---------------------------------------------------------------------------

class TestBuildMessages:
    def test_stock_messages_english(self):
        msgs = _build_stock_messages("AAPL", "Apple Inc.")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert "AAPL" in msgs[0]["content"]
        assert "Apple Inc." in msgs[0]["content"]

    def test_stock_messages_japanese(self):
        msgs = _build_stock_messages("7203.T", "トヨタ自動車")
        assert "7203.T" in msgs[0]["content"]
        assert "トヨタ自動車" in msgs[0]["content"]
        assert "JSON" in msgs[0]["content"]

    def test_industry_messages_japanese(self):
        msgs = _build_industry_messages("半導体")
        assert "半導体" in msgs[0]["content"]

    def test_industry_messages_english(self):
        msgs = _build_industry_messages("semiconductor")
        assert "semiconductor" in msgs[0]["content"]

    def test_market_messages(self):
        msgs = _build_market_messages("日経平均")
        assert "日経平均" in msgs[0]["content"]

    def test_business_messages_english(self):
        msgs = _build_business_messages("AAPL", "Apple Inc.")
        assert "AAPL" in msgs[0]["content"]

    def test_business_messages_japanese(self):
        msgs = _build_business_messages("7751.T", "キヤノン")
        assert "7751.T" in msgs[0]["content"]


# ---------------------------------------------------------------------------
# _call_api
# ---------------------------------------------------------------------------

class TestCallApi:
    @patch("src.data.perplexity_client.requests.post")
    def test_successful_response(self, mock_post, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {"message": {"content": "Hello world"}}
            ],
            "citations": ["https://example.com/1", "https://example.com/2"],
        }
        mock_post.return_value = mock_response

        result = _call_api([{"role": "user", "content": "test"}])
        assert result["text"] == "Hello world"
        assert len(result["citations"]) == 2

    @patch("src.data.perplexity_client.requests.post")
    def test_api_error(self, mock_post, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        result = _call_api([{"role": "user", "content": "test"}])
        assert result["text"] == ""
        assert result["citations"] == []

    @patch("src.data.perplexity_client.requests.post")
    def test_timeout(self, mock_post, monkeypatch):
        import requests as req
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
        mock_post.side_effect = req.exceptions.Timeout("Timed out")

        result = _call_api([{"role": "user", "content": "test"}], timeout=1)
        assert result["text"] == ""

    def test_no_api_key(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        result = _call_api([{"role": "user", "content": "test"}])
        assert result["text"] == ""

    @patch("src.data.perplexity_client.requests.post")
    def test_no_citations(self, mock_post, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "text"}}],
        }
        mock_post.return_value = mock_response

        result = _call_api([{"role": "user", "content": "test"}])
        assert result["text"] == "text"
        assert result["citations"] == []

    @patch("src.data.perplexity_client.requests.post")
    def test_error_warned_suppression(self, mock_post, monkeypatch):
        """Second error is suppressed (no duplicate warning)."""
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        _call_api([{"role": "user", "content": "test1"}])
        assert _error_warned[0] is True

        # Second call should not re-warn
        _call_api([{"role": "user", "content": "test2"}])
        assert _error_warned[0] is True


# ---------------------------------------------------------------------------
# search_stock
# ---------------------------------------------------------------------------

class TestSearchStock:
    def test_no_api_key(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        result = search_stock("AAPL")
        assert result["summary"] == ""
        assert result["citations"] == []
        assert result["recent_developments"] == []

    @patch("src.data.perplexity_client._call_api")
    def test_successful_response(self, mock_call, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")

        json_content = json.dumps({
            "summary": "AAPL is doing well",
            "recent_developments": ["New iPhone launch", "AI features"],
            "analyst_consensus": "Buy",
            "risks_and_concerns": ["China tariffs"],
            "catalysts": ["WWDC 2025"],
        })

        mock_call.return_value = {
            "text": json_content,
            "citations": ["https://example.com"],
        }

        result = search_stock("AAPL", "Apple Inc.")
        assert result["summary"] == "AAPL is doing well"
        assert len(result["recent_developments"]) == 2
        assert result["analyst_consensus"] == "Buy"
        assert result["citations"] == ["https://example.com"]

    @patch("src.data.perplexity_client._call_api")
    def test_malformed_json(self, mock_call, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")

        mock_call.return_value = {
            "text": "Not JSON at all",
            "citations": [],
        }

        result = search_stock("AAPL")
        assert result["raw_response"] == "Not JSON at all"
        assert result["summary"] == ""

    @patch("src.data.perplexity_client._call_api")
    def test_empty_response(self, mock_call, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")

        mock_call.return_value = {"text": "", "citations": []}

        result = search_stock("AAPL")
        assert result == EMPTY_STOCK


# ---------------------------------------------------------------------------
# search_industry
# ---------------------------------------------------------------------------

class TestSearchIndustry:
    @patch("src.data.perplexity_client._call_api")
    def test_successful_response(self, mock_call, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")

        json_content = json.dumps({
            "overview": "Semiconductor industry overview",
            "trends": ["AI chips", "Edge computing"],
            "key_players": ["TSMC", "Intel"],
            "growth_outlook": "Strong growth expected",
            "risks": ["Geopolitics"],
        })

        mock_call.return_value = {
            "text": json_content,
            "citations": ["https://example.com/semi"],
        }

        result = search_industry("半導体")
        assert result["overview"] == "Semiconductor industry overview"
        assert len(result["trends"]) == 2
        assert result["citations"] == ["https://example.com/semi"]


# ---------------------------------------------------------------------------
# search_market
# ---------------------------------------------------------------------------

class TestSearchMarket:
    @patch("src.data.perplexity_client._call_api")
    def test_successful_response(self, mock_call, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")

        json_content = json.dumps({
            "summary": "Market overview",
            "key_drivers": ["BOJ decision", "USD/JPY"],
            "sentiment": "Cautiously optimistic",
            "outlook": "Moderate growth",
            "risks": ["Inflation"],
        })

        mock_call.return_value = {
            "text": json_content,
            "citations": ["https://example.com/market"],
        }

        result = search_market("日経平均")
        assert result["summary"] == "Market overview"
        assert len(result["key_drivers"]) == 2
        assert result["sentiment"] == "Cautiously optimistic"


# ---------------------------------------------------------------------------
# search_business
# ---------------------------------------------------------------------------

class TestSearchBusiness:
    @patch("src.data.perplexity_client._call_api")
    def test_successful_response(self, mock_call, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")

        json_content = json.dumps({
            "overview": "Canon is a diversified company",
            "segments": [
                {"name": "Printing", "revenue_share": "55%", "description": "Printers"}
            ],
            "revenue_model": "Hardware + consumables",
            "competitive_position": "Market leader in printing",
            "growth_strategy": ["Medical expansion"],
            "risks": ["Print market decline"],
        })

        mock_call.return_value = {
            "text": json_content,
            "citations": ["https://example.com/canon"],
        }

        result = search_business("7751.T", "Canon Inc.")
        assert result["overview"] == "Canon is a diversified company"
        assert len(result["segments"]) == 1
        assert result["segments"][0]["name"] == "Printing"
        assert result["competitive_position"] == "Market leader in printing"

    @patch("src.data.perplexity_client._call_api")
    def test_uses_deep_research_model(self, mock_call, monkeypatch):
        """search_business should use sonar-deep-research model."""
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")

        mock_call.return_value = {"text": "", "citations": []}

        search_business("AAPL")
        call_args = mock_call.call_args
        assert call_args[1]["model"] == "sonar-deep-research"

    def test_no_api_key(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        result = search_business("AAPL")
        assert result["overview"] == ""
        assert result["citations"] == []
