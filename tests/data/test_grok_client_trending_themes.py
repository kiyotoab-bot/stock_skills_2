"""Tests for grok_client get_trending_themes (KIK-440)."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.data.grok_client import (
    _build_trending_themes_prompt,
    _parse_json_array_response,
    get_trending_themes,
    EMPTY_TRENDING_THEMES,
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
    from src.data import grok_client
    grok_client._error_warned[0] = False
    yield


# ===================================================================
# _parse_json_array_response
# ===================================================================

class TestParseJsonArrayResponse:
    def test_valid_array(self):
        result = _parse_json_array_response('[{"a": 1}, {"b": 2}]')
        assert len(result) == 2
        assert result[0]["a"] == 1

    def test_array_with_surrounding_text(self):
        result = _parse_json_array_response('Here are results: [{"x": 1}] done.')
        assert len(result) == 1

    def test_empty_array(self):
        result = _parse_json_array_response("[]")
        assert result == []

    def test_not_json(self):
        result = _parse_json_array_response("no json here")
        assert result == []

    def test_object_returns_empty(self):
        result = _parse_json_array_response('{"key": "value"}')
        assert result == []

    def test_malformed_json(self):
        result = _parse_json_array_response("[{broken")
        assert result == []


# ===================================================================
# _build_trending_themes_prompt
# ===================================================================

class TestBuildTrendingThemesPrompt:
    def test_japan(self):
        prompt = _build_trending_themes_prompt("japan")
        assert "日本市場" in prompt
        assert "ai" in prompt
        assert "defense" in prompt
        assert "JSON" in prompt

    def test_us(self):
        prompt = _build_trending_themes_prompt("us")
        assert "米国市場" in prompt

    def test_global_default(self):
        prompt = _build_trending_themes_prompt("global")
        assert "グローバル市場" in prompt

    def test_unknown_region(self):
        prompt = _build_trending_themes_prompt("kr")
        assert "KR市場" in prompt

    def test_contains_valid_theme_keys(self):
        prompt = _build_trending_themes_prompt("japan")
        for key in ["ai", "ev", "cloud-saas", "cybersecurity", "biotech",
                     "renewable-energy", "fintech", "defense", "healthcare"]:
            assert key in prompt


# ===================================================================
# get_trending_themes
# ===================================================================

class TestGetTrendingThemes:
    def test_no_api_key(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        result = get_trending_themes("japan")
        assert result["themes"] == []
        assert result["raw_response"] == ""

    @patch("src.data.grok_client.requests.post")
    def test_successful_array_response(self, mock_post, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        payload = [
            {"theme": "ai", "reason": "半導体需要拡大", "confidence": 0.9},
            {"theme": "defense", "reason": "地政学リスク", "confidence": 0.8},
        ]
        mock_post.return_value = _make_grok_response(json.dumps(payload))

        result = get_trending_themes("japan")
        assert len(result["themes"]) == 2
        assert result["themes"][0]["theme"] == "ai"
        assert result["themes"][0]["confidence"] == 0.9
        assert result["themes"][0]["reason"] == "半導体需要拡大"

    @patch("src.data.grok_client.requests.post")
    def test_successful_object_response(self, mock_post, monkeypatch):
        """Grok may return {themes: [...]} instead of a bare array."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        payload = {
            "themes": [
                {"theme": "ev", "reason": "EV sales up", "confidence": 0.7},
            ]
        }
        mock_post.return_value = _make_grok_response(json.dumps(payload))

        result = get_trending_themes("us")
        assert len(result["themes"]) == 1
        assert result["themes"][0]["theme"] == "ev"

    @patch("src.data.grok_client.requests.post")
    def test_confidence_sort_descending(self, mock_post, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        payload = [
            {"theme": "biotech", "reason": "r1", "confidence": 0.5},
            {"theme": "ai", "reason": "r2", "confidence": 0.9},
            {"theme": "ev", "reason": "r3", "confidence": 0.7},
        ]
        mock_post.return_value = _make_grok_response(json.dumps(payload))

        result = get_trending_themes("japan")
        confs = [t["confidence"] for t in result["themes"]]
        assert confs == [0.9, 0.7, 0.5]

    @patch("src.data.grok_client.requests.post")
    def test_empty_response(self, mock_post, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_post.return_value = _make_grok_response("")

        result = get_trending_themes("japan")
        assert result["themes"] == []

    @patch("src.data.grok_client.requests.post")
    def test_non_json_response(self, mock_post, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_post.return_value = _make_grok_response("Not JSON at all")

        result = get_trending_themes("japan")
        assert result["themes"] == []
        assert result["raw_response"] == "Not JSON at all"

    @patch("src.data.grok_client.requests.post")
    def test_unknown_themes_passthrough(self, mock_post, monkeypatch):
        """Unknown theme keys should be passed through (validation at script layer)."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        payload = [
            {"theme": "ai", "reason": "r1", "confidence": 0.9},
            {"theme": "quantum-computing", "reason": "r2", "confidence": 0.6},
        ]
        mock_post.return_value = _make_grok_response(json.dumps(payload))

        result = get_trending_themes("japan")
        themes = [t["theme"] for t in result["themes"]]
        assert "ai" in themes
        assert "quantum-computing" in themes

    @patch("src.data.grok_client.requests.post")
    def test_theme_key_normalized(self, mock_post, monkeypatch):
        """Theme keys should be lowercased and stripped."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        payload = [
            {"theme": " AI ", "reason": "r1", "confidence": 0.8},
        ]
        mock_post.return_value = _make_grok_response(json.dumps(payload))

        result = get_trending_themes("japan")
        assert result["themes"][0]["theme"] == "ai"

    @patch("src.data.grok_client.requests.post")
    def test_malformed_items_filtered(self, mock_post, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        payload = [
            {"theme": "ai", "reason": "ok", "confidence": 0.9},
            {"reason": "missing theme"},
            {"theme": 123, "reason": "bad type"},
            "not a dict",
        ]
        mock_post.return_value = _make_grok_response(json.dumps(payload))

        result = get_trending_themes("japan")
        assert len(result["themes"]) == 1
        assert result["themes"][0]["theme"] == "ai"

    @patch("src.data.grok_client.requests.post")
    def test_default_confidence(self, mock_post, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        payload = [
            {"theme": "ai", "reason": "r1"},
        ]
        mock_post.return_value = _make_grok_response(json.dumps(payload))

        result = get_trending_themes("japan")
        assert result["themes"][0]["confidence"] == 0.5

    @patch("src.data.grok_client.requests.post")
    def test_api_error_returns_empty(self, mock_post, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_post.return_value = mock_resp

        result = get_trending_themes("japan")
        assert result["themes"] == []
