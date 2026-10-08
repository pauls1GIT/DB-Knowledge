from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from kedb.application.dto import GroundedAnswer
from kedb.application.use_cases.grounded_answer import GenerateGroundedAnswer
from kedb.infrastructure.search.in_memory import InMemorySearch
from kedb.presentation.api import app as api_module


def test_resolve_returns_resolution_and_grounded_followup(monkeypatch):
    document = {"known_error_id": uuid4(), "article_version_id": uuid4(),
                "title": "Oracle timeout", "content": "ORA-12170 Oracle timeout",
                "resolution": "Restart the listener", "error_codes": ["ORA-12170"]}
    monkeypatch.setattr(api_module, "make_search_adapter", lambda: InMemorySearch([document]))
    calls = []
    class LLM:
        def structured(self, **kwargs):
            calls.append(kwargs)
            return GroundedAnswer(answer="Restart the listener", confidence=0.9, evidence=[])
    monkeypatch.setattr(api_module, "make_llm", lambda: LLM())
    client = TestClient(api_module.app)
    response = client.post("/api/tickets/resolve", json={"summary": "ORA-12170", "description": "Oracle timeout"})
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert candidates[0]["resolution"] == "Restart the listener"
    response = client.post("/api/tickets/grounded-answer", json={
        "question": "What should I restart?", "evidence": candidates,
        "history": [{"role": "user", "content": "Oracle timed out"}]})
    assert response.status_code == 200
    assert response.json()["answer"] == "Restart the listener"
    assert "user: Oracle timed out" in calls[0]["user"]
    assert "Restart the listener" in calls[0]["user"]


@pytest.mark.parametrize("body", [
    {"question": " ", "evidence": []},
    {"question": "Help", "evidence": []},
    {"question": "Help", "evidence": [{"title": "Missing resolution"}]},
])
def test_grounded_answer_requires_question_and_resolution(body):
    assert TestClient(api_module.app).post("/api/tickets/grounded-answer", json=body).status_code == 400


def test_grounded_use_case_rejects_empty_evidence():
    with pytest.raises(ValueError, match="published evidence"):
        GenerateGroundedAnswer(None).execute("Help", [])


def test_resolve_loads_published_resolution_for_index_results(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from kedb.domain import ArticleStatus
    document = {"known_error_id": uuid4(), "article_version_id": uuid4(),
                "title": "Oracle timeout", "content": "ORA-12170", "error_codes": ["ORA-12170"]}
    monkeypatch.setattr(api_module, "make_search_adapter", lambda: InMemorySearch([document]))
    monkeypatch.setattr(api_module, "db", SimpleNamespace(sessions=lambda: nullcontext(None)))
    version = SimpleNamespace(status=ArticleStatus.PUBLISHED, solution="Restore listener")
    monkeypatch.setattr(api_module, "SqlRepositories", lambda session: SimpleNamespace(get_version=lambda key: version))
    client = TestClient(api_module.app)
    body = {"summary": "ORA-12170", "description": ""}
    assert client.post("/api/tickets/resolve", json=body).json()["candidates"][0]["resolution"] == "Restore listener"
    version.status = ArticleStatus.DRAFT
    assert client.post("/api/tickets/resolve", json=body).json()["candidates"][0]["resolution"] == ""
