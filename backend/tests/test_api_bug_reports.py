import json

import responses

from app.services.linear import LINEAR_API_URL


def _configure_linear(test_settings, monkeypatch):
    test_settings.linear_api_key = "lin_test_key"
    test_settings.linear_team_id = "team-123"
    test_settings.linear_project_id = "project-456"
    monkeypatch.setattr("app.services.linear.settings", test_settings)
    monkeypatch.setattr("app.routers.bug_reports.settings", test_settings)


def test_bug_reports_disabled_by_default(client):
    assert client.get("/api/bug-reports/enabled").json() == {"enabled": False}


def test_submit_bug_report_not_configured(client):
    response = client.post("/api/bug-reports", json={"title": "It broke"})
    assert response.status_code == 503


@responses.activate
def test_submit_bug_report_creates_issue(client, test_settings, monkeypatch):
    _configure_linear(test_settings, monkeypatch)
    responses.add(
        responses.POST,
        LINEAR_API_URL,
        json={
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {"identifier": "MY-7", "url": "https://linear.app/issue/MY-7"},
                }
            }
        },
    )

    response = client.post(
        "/api/bug-reports",
        json={
            "title": "Feed 500s",
            "description": "Opening the feed throws a 500.",
            "page_url": "https://clipcast.example/podcast/abc",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"identifier": "MY-7", "url": "https://linear.app/issue/MY-7"}

    sent = json.loads(responses.calls[0].request.body)
    issue_input = sent["variables"]["input"]
    assert issue_input["teamId"] == "team-123"
    assert issue_input["projectId"] == "project-456"
    assert issue_input["title"] == "Feed 500s"
    assert "https://clipcast.example/podcast/abc" in issue_input["description"]
    assert responses.calls[0].request.headers["Authorization"] == "lin_test_key"


@responses.activate
def test_submit_bug_report_linear_error(client, test_settings, monkeypatch):
    _configure_linear(test_settings, monkeypatch)
    responses.add(
        responses.POST,
        LINEAR_API_URL,
        json={"errors": [{"message": "Invalid team"}]},
    )

    response = client.post("/api/bug-reports", json={"title": "Whatever"})
    assert response.status_code == 503


def test_submit_bug_report_requires_title(client):
    assert client.post("/api/bug-reports", json={"title": ""}).status_code == 422
