from fastapi.testclient import TestClient
from kedb.presentation.api import app as api_module
from kedb.infrastructure.lakebase import Database
from kedb.infrastructure.search.in_memory import InMemorySearch
from kedb.infrastructure import notifications
from kedb.config import Settings
from uuid import uuid4


def test_webhook_reporter_top_three_retry_and_manual_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "db", Database(f"sqlite+pysqlite:///{tmp_path / 'test.db'}"))
    monkeypatch.setattr(api_module, "settings", Settings(_env_file=None, jira_webhook_token="secret", kedb_email_delivery="smtp"))
    docs = [dict(known_error_id=uuid4(), article_version_id=uuid4(), title="timeout",
                 content="timeout", resolution="retry") for _ in range(5)]
    monkeypatch.setattr(api_module, "make_search_adapter", lambda: InMemorySearch(docs))
    sent = []
    def send(settings, issue, recipient, candidates):
        sent.append((recipient, candidates))
    monkeypatch.setattr(notifications, "send_candidates", send)
    body = {"webhookEvent": "jira:issue_created", "issue": {"key": "T-1", "fields": {
        "summary": "timeout", "description": "timeout", "reporter": {"emailAddress": "reporter@example.com"}}}}
    headers = {"X-Jira-Webhook-Token": "secret"}
    with TestClient(api_module.app) as client:
        assert client.post("/api/jira/webhook", json=body).status_code == 401
        result = client.post("/api/jira/webhook", json=body, headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["candidate_count"] == 3
        assert sent[0][0] == "reporter@example.com"
        assert len(sent[0][1]) == 3
        assert client.post("/api/jira/webhook", json=body, headers=headers).json()["status"] == "already_sent"
        assert len(sent) == 1
        body["issue"]["key"] = "T-2"
        def fail(*args):
            raise OSError("SMTP unavailable")
        monkeypatch.setattr(notifications, "send_candidates", fail)
        assert client.post("/api/jira/webhook", json=body, headers=headers).status_code == 503
        monkeypatch.setattr(notifications, "send_candidates", send)
        assert client.post("/api/jira/webhook", json=body, headers=headers).json()["status"] == "sent"
        body["issue"]["fields"]["reporter"] = {}
        assert client.post("/api/jira/webhook", json=body, headers=headers).status_code == 422
        tickets = client.get("/api/jira/issues").json()
        assert len(tickets) == 2
        ticket_id = tickets[0]["id"]
        assert client.delete(f"/api/jira/issues/{ticket_id}").status_code == 200
        assert client.get(f"/api/jira/issues/{ticket_id}").status_code == 404


def test_jira_delivery_returns_candidates_without_smtp_or_reporter_email(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "db", Database(f"sqlite+pysqlite:///{tmp_path / 'jira.db'}"))
    monkeypatch.setattr(api_module, "settings", Settings(_env_file=None, jira_webhook_token="secret"))
    monkeypatch.setattr(notifications, "send_candidates", lambda *a: (_ for _ in ()).throw(AssertionError("SMTP called")))
    docs = [dict(known_error_id=uuid4(), article_version_id=uuid4(), title="timeout <script>",
                 content="timeout", resolution="Retry safely") for _ in range(5)]
    monkeypatch.setattr(api_module, "make_search_adapter", lambda: InMemorySearch(docs))
    with TestClient(api_module.app) as client:
        body = {"webhookEvent": "jira:issue_created", "issue": {"key": "T-3", "fields": {"summary": "timeout"}}}
        headers = {"X-Jira-Webhook-Token": "secret"}
        for _ in range(2):
            response = client.post("/api/jira/webhook", json=body, headers=headers)
            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "candidates_ready"
            assert result["candidate_count"] == 3
            assert "Retry safely" in result["email_body"]
            assert "<script>" not in result["email_body_html"]
        monkeypatch.setattr(api_module, "make_search_adapter", lambda: InMemorySearch([]))
        result = client.post("/api/jira/webhook", json=body, headers=headers).json()
        assert result["candidate_count"] == 0
        assert "No similar" in result["email_body"]
