"""Tests for src/data/linear_client.py (KIK-472)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.data import linear_client


class TestIsAvailable:
    def test_is_available_when_enabled(self, monkeypatch):
        monkeypatch.setenv("LINEAR_ENABLED", "on")
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test_key")
        assert linear_client.is_available() is True

    def test_is_available_when_disabled(self, monkeypatch):
        monkeypatch.setenv("LINEAR_ENABLED", "off")
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test_key")
        assert linear_client.is_available() is False

    def test_is_available_no_key(self, monkeypatch):
        monkeypatch.setenv("LINEAR_ENABLED", "on")
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        assert linear_client.is_available() is False

    def test_is_available_default_disabled(self, monkeypatch):
        monkeypatch.delenv("LINEAR_ENABLED", raising=False)
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test_key")
        assert linear_client.is_available() is False


class TestCreateIssue:
    def test_create_issue_success(self, monkeypatch):
        monkeypatch.setenv("LINEAR_ENABLED", "on")
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test_key")
        monkeypatch.setenv("LINEAR_TEAM_ID", "team-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": "issue-abc",
                        "identifier": "KIK-999",
                        "url": "https://linear.app/team/issue/KIK-999",
                    },
                }
            }
        }

        with patch("src.data.linear_client.requests.post", return_value=mock_response) as mock_post:
            result = linear_client.create_issue(
                title="[Action] 7203.T 売却検討",
                description="EXIT判定",
                priority=2,
            )
            assert result is not None
            assert result["id"] == "issue-abc"
            assert result["identifier"] == "KIK-999"
            assert result["url"] == "https://linear.app/team/issue/KIK-999"
            mock_post.assert_called_once()

    def test_create_issue_api_error(self, monkeypatch):
        monkeypatch.setenv("LINEAR_ENABLED", "on")
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test_key")
        monkeypatch.setenv("LINEAR_TEAM_ID", "team-123")
        # Reset warned flag
        linear_client._error_warned = False

        import requests as _req

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = _req.exceptions.HTTPError("500")

        with patch("src.data.linear_client.requests.post", return_value=mock_response):
            result = linear_client.create_issue(title="test", priority=3)
            assert result is None

    def test_create_issue_disabled(self, monkeypatch):
        monkeypatch.setenv("LINEAR_ENABLED", "off")
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test_key")

        with patch("src.data.linear_client.requests.post") as mock_post:
            result = linear_client.create_issue(title="test")
            assert result is None
            mock_post.assert_not_called()

    def test_create_issue_no_team_id(self, monkeypatch):
        monkeypatch.setenv("LINEAR_ENABLED", "on")
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test_key")
        monkeypatch.delenv("LINEAR_TEAM_ID", raising=False)

        result = linear_client.create_issue(title="test")
        assert result is None

    def test_create_issue_with_project_id(self, monkeypatch):
        monkeypatch.setenv("LINEAR_ENABLED", "on")
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test_key")
        monkeypatch.setenv("LINEAR_TEAM_ID", "team-123")
        monkeypatch.setenv("LINEAR_PROJECT_ID", "project-456")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {"id": "i1", "identifier": "KIK-1", "url": "https://example.com"},
                }
            }
        }

        with patch("src.data.linear_client.requests.post", return_value=mock_response) as mock_post:
            result = linear_client.create_issue(title="test")
            assert result is not None
            # Verify projectId was included in variables
            call_args = mock_post.call_args
            payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
            variables = payload.get("variables", {})
            assert variables.get("input", {}).get("projectId") == "project-456"


class TestFindIssueByTitle:
    def test_find_issue_by_title(self, monkeypatch):
        monkeypatch.setenv("LINEAR_ENABLED", "on")
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test_key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "issueSearch": {
                    "nodes": [
                        {
                            "id": "issue-abc",
                            "identifier": "KIK-100",
                            "url": "https://linear.app/issue/KIK-100",
                            "title": "[Action] 7203.T 売却検討",
                        }
                    ]
                }
            }
        }

        with patch("src.data.linear_client.requests.post", return_value=mock_response):
            result = linear_client.find_issue_by_title("[Action] 7203.T")
            assert result is not None
            assert result["identifier"] == "KIK-100"

    def test_find_issue_not_found(self, monkeypatch):
        monkeypatch.setenv("LINEAR_ENABLED", "on")
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test_key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": {"issueSearch": {"nodes": []}}
        }

        with patch("src.data.linear_client.requests.post", return_value=mock_response):
            result = linear_client.find_issue_by_title("[Action] nonexistent")
            assert result is None


class TestUpdateIssue:
    def test_update_issue_disabled(self, monkeypatch):
        monkeypatch.setenv("LINEAR_ENABLED", "off")
        assert linear_client.update_issue("id-1", state="Done") is False

    def test_update_issue_no_state(self, monkeypatch):
        monkeypatch.setenv("LINEAR_ENABLED", "on")
        monkeypatch.setenv("LINEAR_API_KEY", "key")
        assert linear_client.update_issue("id-1", state=None) is False
