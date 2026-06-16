import logging

import requests

from app.config import settings

logger = logging.getLogger("clipcast")

LINEAR_API_URL = "https://api.linear.app/graphql"

_ISSUE_CREATE_MUTATION = """
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue {
      identifier
      url
    }
  }
}
"""


class LinearError(Exception):
    """Raised when a bug report cannot be filed to Linear."""


def create_bug_report(title: str, description: str) -> dict:
    """Create a Linear issue and return its identifier and url.

    Raises LinearError if Linear is not configured or the API call fails.
    """
    if not settings.linear_api_key or not settings.linear_team_id:
        raise LinearError("Linear integration is not configured")

    issue_input: dict = {
        "teamId": settings.linear_team_id,
        "title": title,
        "description": description,
    }
    if settings.linear_project_id:
        issue_input["projectId"] = settings.linear_project_id

    try:
        response = requests.post(
            LINEAR_API_URL,
            headers={
                "Authorization": settings.linear_api_key,
                "Content-Type": "application/json",
            },
            json={"query": _ISSUE_CREATE_MUTATION, "variables": {"input": issue_input}},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Linear request failed: %s", exc)
        raise LinearError("Could not reach Linear") from exc

    body = response.json()
    if body.get("errors"):
        logger.error("Linear returned errors: %s", body["errors"])
        raise LinearError("Linear rejected the bug report")

    result = body.get("data", {}).get("issueCreate", {})
    if not result.get("success") or not result.get("issue"):
        raise LinearError("Linear did not create the issue")

    return result["issue"]
