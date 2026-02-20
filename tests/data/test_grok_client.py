"""Tests for src/data/grok_client.py (KIK-359)."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.data.grok_client import (
    is_available,
    search_x_sentiment,
    _build_sentiment_prompt,
    get_error_status,
    reset_error_state,
)


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_with_key(self, monkeypatch):
        """Returns True when XAI_API_KEY is set."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        assert is_available() is True

    def test_without_key(self, monkeypatch):
        """Returns False when XAI_API_KEY is not set."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        assert is_available() is False

    def test_empty_key(self, monkeypatch):
        """Returns False when XAI_API_KEY is empty string."""
        monkeypatch.setenv("XAI_API_KEY", "")
        assert is_available() is False


# ---------------------------------------------------------------------------
# _build_sentiment_prompt
# ---------------------------------------------------------------------------

class TestBuildSentimentPrompt:
    def test_basic_prompt(self):
        """Prompt includes symbol."""
        prompt = _build_sentiment_prompt("AAPL")
        assert "AAPL" in prompt
        assert "sentiment" in prompt.lower()

    def test_with_company_name(self):
        """Prompt includes company name."""
        prompt = _build_sentiment_prompt("7203.T", "Toyota")
        assert "Toyota" in prompt
        assert "7203.T" in prompt


# ---------------------------------------------------------------------------
# search_x_sentiment
# ---------------------------------------------------------------------------

class TestSearchXSentiment:
    def test_no_api_key(self, monkeypatch):
        """Returns empty result when API key is not set."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        result = search_x_sentiment("AAPL")
        assert result["positive"] == []
        assert result["negative"] == []
        assert result["sentiment_score"] == 0.0
        assert result["raw_response"] == ""

    @patch("src.data.grok_client.requests.post")
    def test_successful_response(self, mock_post, monkeypatch):
        """Parses a successful Grok API response."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")

        json_content = json.dumps({
            "positive": ["Strong earnings beat", "AI growth momentum"],
            "negative": ["China market weakness"],
            "sentiment_score": 0.6,
        })

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": json_content}
                    ],
                }
            ]
        }
        mock_post.return_value = mock_response

        result = search_x_sentiment("AAPL", "Apple Inc.")
        assert len(result["positive"]) == 2
        assert len(result["negative"]) == 1
        assert result["sentiment_score"] == 0.6
        assert result["raw_response"] == json_content

    @patch("src.data.grok_client.requests.post")
    def test_api_error(self, mock_post, monkeypatch):
        """Returns empty result on API error (graceful degradation)."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        result = search_x_sentiment("AAPL")
        assert result["positive"] == []
        assert result["sentiment_score"] == 0.0

    @patch("src.data.grok_client.requests.post")
    def test_timeout(self, mock_post, monkeypatch):
        """Returns empty result on timeout."""
        import requests as req
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_post.side_effect = req.exceptions.Timeout("Timed out")

        result = search_x_sentiment("AAPL", timeout=1)
        assert result["positive"] == []

    @patch("src.data.grok_client.requests.post")
    def test_malformed_json_response(self, mock_post, monkeypatch):
        """Handles malformed JSON in response."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "This is not JSON at all"}
                    ],
                }
            ]
        }
        mock_post.return_value = mock_response

        result = search_x_sentiment("AAPL")
        assert result["raw_response"] == "This is not JSON at all"
        assert result["positive"] == []

    @patch("src.data.grok_client.requests.post")
    def test_sentiment_score_clamping(self, mock_post, monkeypatch):
        """Sentiment score is clamped to [-1, 1]."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")

        json_content = json.dumps({
            "positive": [],
            "negative": [],
            "sentiment_score": 5.0,  # Out of range
        })

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": json_content}
                    ],
                }
            ]
        }
        mock_post.return_value = mock_response

        result = search_x_sentiment("AAPL")
        assert result["sentiment_score"] == 1.0

    @patch("src.data.grok_client.requests.post")
    def test_empty_output(self, mock_post, monkeypatch):
        """Returns empty result when API returns no output."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"output": []}
        mock_post.return_value = mock_response

        result = search_x_sentiment("AAPL")
        assert result["positive"] == []


# ---------------------------------------------------------------------------
# get_error_status (KIK-431)
# ---------------------------------------------------------------------------

class TestGetErrorStatus:
    """Tests for error state tracking (KIK-431)."""

    def setup_method(self):
        """Reset error state before each test."""
        reset_error_state()

    def test_not_configured(self, monkeypatch):
        """Status is not_configured when XAI_API_KEY is absent."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        search_x_sentiment("AAPL")
        status = get_error_status()
        assert status["status"] == "not_configured"
        assert status["status_code"] is None

    @patch("src.data.grok_client.requests.post")
    def test_auth_error(self, mock_post, monkeypatch):
        """Status is auth_error on HTTP 401."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_post.return_value = mock_response

        search_x_sentiment("AAPL")
        status = get_error_status()
        assert status["status"] == "auth_error"
        assert status["status_code"] == 401

    @patch("src.data.grok_client.requests.post")
    def test_rate_limited(self, mock_post, monkeypatch):
        """Status is rate_limited on HTTP 429."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_post.return_value = mock_response

        search_x_sentiment("AAPL")
        status = get_error_status()
        assert status["status"] == "rate_limited"
        assert status["status_code"] == 429

    @patch("src.data.grok_client.requests.post")
    def test_other_error(self, mock_post, monkeypatch):
        """Status is other_error on non-200/401/429 responses."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        search_x_sentiment("AAPL")
        status = get_error_status()
        assert status["status"] == "other_error"
        assert status["status_code"] == 500

    @patch("src.data.grok_client.requests.post")
    def test_timeout(self, mock_post, monkeypatch):
        """Status is timeout on request timeout."""
        import requests as req
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_post.side_effect = req.exceptions.Timeout("Timed out")

        search_x_sentiment("AAPL", timeout=1)
        status = get_error_status()
        assert status["status"] == "timeout"
        assert status["status_code"] is None

    @patch("src.data.grok_client.requests.post")
    def test_ok(self, mock_post, monkeypatch):
        """Status is ok on a successful call."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": '{"positive":[],"negative":[],"sentiment_score":0}'}],
                }
            ]
        }
        mock_post.return_value = mock_response

        search_x_sentiment("AAPL")
        status = get_error_status()
        assert status["status"] == "ok"
        assert status["status_code"] == 200

    def test_reset_error_state(self, monkeypatch):
        """reset_error_state() clears all state fields."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        search_x_sentiment("AAPL")
        assert get_error_status()["status"] == "not_configured"

        reset_error_state()
        status = get_error_status()
        assert status["status"] == "ok"
        assert status["status_code"] is None
        assert status["message"] == ""
