import httpx
import pytest
from fastapi.testclient import TestClient

from kedb.application.incidents import incidents_from_json, batch_items
from kedb.config import Settings
from kedb.infrastructure import jira
from kedb.infrastructure.lakebase import Database
from kedb.application.workflows.batch import BatchWorker
from kedb.presentation.api import app as api_module


TICKET = {"ticket_id": "OPS-1", "subject": "Timeout", "description": "HTTP 503",
          "resolution": "Restart", "status": "Resolved"}


@pytest.mark.parametrize("payload", [{}, [None], [{**TICKET, "subject": []}],
                                      [{**TICKET, "ticket_id": " "}], [{"ticket_id": "T"}]])
def test_json_rejects_invalid_records(payload):
    with pytest.raises(ValueError):
        incidents_from_json(payload)


def test_json_filters_and_deduplicates():
    items = batch_items(incidents_from_json([TICKET, TICKET, {**TICKET, "ticket_id": "OPS-2", "status": "Open"}]))
    assert len(items) == 1
    assert items[0]["error_code"] == "HTTP 503"


def test_jira_pagination_adf_and_custom_resolution(monkeypatch):
    import json
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.path == "/rest/api/3/search/jql"
        assert request.headers["authorization"].startswith("Basic ")
        assert "customfield_123" in body["fields"]
        if len(calls) == 2:
            assert body["nextPageToken"] == "page2"
            return httpx.Response(200, json={"issues": [], "isLast": True})
        return httpx.Response(200, json={"nextPageToken": "page2", "issues": [{
            "key": "OPS-1", "fields": {"summary": "Timeout", "description": {
                "type": "doc", "content": [{"type": "paragraph", "content": [
                    {"type": "text", "text": "HTTP 503"}]}]},
                "customfield_123": "Restart", "status": {"name": "Completed", "statusCategory": {"key": "done"}}}}]})
    real_client = httpx.Client
    monkeypatch.setattr(jira.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    settings = Settings(_env_file=None, jira_base_url="https://example.atlassian.net",
                        jira_email="user@example.com", jira_api_token="token",
                        jira_resolution_field="customfield_123")
    items = batch_items(jira.fetch_incidents(settings))
    assert len(calls) == 2
    assert items[0]["description"] == "HTTP 503"
    assert items[0]["resolution"] == "Restart"


def test_input_endpoints_and_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "db", Database(f"sqlite+pysqlite:///{tmp_path / 'input.db'}"))
    monkeypatch.setattr(BatchWorker, "start", lambda self: None)
    monkeypatch.setattr(BatchWorker, "stop", lambda self: None)
    with TestClient(api_module.app) as client:
        response = client.post("/api/batches/play", json={"tickets": [TICKET]})
        assert response.status_code == 200
        batch_id = response.json()["batch_id"]
        assert client.post(f"/api/batches/{batch_id}/pause").status_code == 200
        assert client.post(f"/api/batches/{batch_id}/resume").status_code == 200
        assert client.get(f"/api/batches/{batch_id}").json()["status"] == "RUNNING"
        assert client.post("/api/batches/play", json={"tickets": [{}]}).status_code == 400
        assert client.post("/api/batches/play", json={"source": "csv"}).status_code == 422
        monkeypatch.setattr(api_module, "fetch_incidents", lambda settings, jql: incidents_from_json([TICKET]))
        response = client.post("/api/batches/play", json={"source": "jira", "jql": "project = OPS"})
        assert response.status_code == 200
        assert client.get(f"/api/batches/{response.json()['batch_id']}").json()["total"] == 1
        def denied(*args):
            response = httpx.Response(401, request=httpx.Request("POST", "https://example.atlassian.net"))
            response.raise_for_status()
        monkeypatch.setattr(api_module, "fetch_incidents", denied)
        response = client.post("/api/batches/play", json={"source": "jira"})
        assert response.status_code == 502
        assert response.json()["detail"] == "Jira API returned HTTP 401"
