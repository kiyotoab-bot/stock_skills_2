"""Linear API client for action item management (KIK-472).

Creates Linear issues from proactive suggestions and health check alerts.
API key is read from LINEAR_API_KEY environment variable.
When LINEAR_ENABLED != "on", all functions return None/False (graceful degradation).
"""

import os
import sys
from typing import Optional

import requests

_API_URL = "https://api.linear.app/graphql"
_error_warned = False


def _get_api_key() -> Optional[str]:
    return os.environ.get("LINEAR_API_KEY")


def _get_team_id() -> Optional[str]:
    return os.environ.get("LINEAR_TEAM_ID")


def _get_project_id() -> Optional[str]:
    return os.environ.get("LINEAR_PROJECT_ID")


def is_available() -> bool:
    """Check if Linear integration is enabled and configured."""
    return (
        os.environ.get("LINEAR_ENABLED", "").lower() == "on"
        and bool(_get_api_key())
    )


def _graphql(query: str, variables: dict | None = None) -> Optional[dict]:
    """Execute a GraphQL request against Linear API.

    Returns the parsed JSON response data, or None on error.
    """
    global _error_warned
    api_key = _get_api_key()
    if not api_key:
        return None
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    try:
        resp = requests.post(_API_URL, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            if not _error_warned:
                print(
                    f"Warning: Linear API GraphQL error: {data['errors']}",
                    file=sys.stderr,
                )
                _error_warned = True
            return None
        return data.get("data")
    except requests.exceptions.HTTPError as e:
        if not _error_warned:
            print(f"Warning: Linear API HTTP error: {e}", file=sys.stderr)
            _error_warned = True
        return None
    except Exception as e:
        if not _error_warned:
            print(f"Warning: Linear API error: {e}", file=sys.stderr)
            _error_warned = True
        return None


def create_issue(
    title: str,
    description: str = "",
    priority: int = 3,
    labels: list[str] | None = None,
) -> Optional[dict]:
    """Create a Linear issue via GraphQL mutation.

    Args:
        title: Issue title.
        description: Markdown description.
        priority: 0=None, 1=Urgent, 2=High, 3=Normal, 4=Low.
        labels: Label names (not used in this initial implementation).

    Returns:
        {id, identifier, url} on success, None on failure or when disabled.
    """
    if not is_available():
        return None
    team_id = _get_team_id()
    if not team_id:
        return None

    mutation = """
    mutation IssueCreate($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue {
          id
          identifier
          url
        }
      }
    }
    """
    input_vars: dict = {
        "title": title,
        "description": description,
        "priority": priority,
        "teamId": team_id,
    }
    project_id = _get_project_id()
    if project_id:
        input_vars["projectId"] = project_id

    data = _graphql(mutation, {"input": input_vars})
    if not data:
        return None
    result = data.get("issueCreate", {})
    if not result.get("success"):
        return None
    issue = result.get("issue", {})
    return {
        "id": issue.get("id", ""),
        "identifier": issue.get("identifier", ""),
        "url": issue.get("url", ""),
    }


def find_issue_by_title(title_prefix: str) -> Optional[dict]:
    """Search for an existing issue by title prefix (dedup check).

    Returns {id, identifier, url, title} if found, None otherwise.
    """
    if not is_available():
        return None

    query = """
    query IssueSearch($query: String!) {
      issueSearch(query: $query, first: 1) {
        nodes {
          id
          identifier
          url
          title
        }
      }
    }
    """
    data = _graphql(query, {"query": title_prefix})
    if not data:
        return None
    nodes = data.get("issueSearch", {}).get("nodes", [])
    if not nodes:
        return None
    node = nodes[0]
    return {
        "id": node.get("id", ""),
        "identifier": node.get("identifier", ""),
        "url": node.get("url", ""),
        "title": node.get("title", ""),
    }


def update_issue(issue_id: str, state: str | None = None) -> bool:
    """Update a Linear issue state.

    Args:
        issue_id: Linear issue ID.
        state: State name to transition to (e.g. "Done", "In Progress").

    Returns:
        True on success, False on failure or when disabled.
    """
    if not is_available():
        return False
    if not state:
        return False

    mutation = """
    mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
      issueUpdate(id: $id, input: $input) {
        success
      }
    }
    """
    input_vars: dict = {}
    if state:
        input_vars["stateId"] = state

    data = _graphql(mutation, {"id": issue_id, "input": input_vars})
    if not data:
        return False
    return data.get("issueUpdate", {}).get("success", False)
