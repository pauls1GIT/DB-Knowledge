from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from kedb.application.dto import GroundedAnswer
from kedb.infrastructure.search.in_memory import InMemorySearch
from kedb.presentation.api import app as api_module


def test_resolve_chat_refreshes_retrieval_and_resets_conversation():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    source = Path("src/kedb/presentation/streamlit/app.py").read_text(encoding="utf-8")
    render = source[source.index("def render_resolve_ticket()"):source.index("def render_search_kedb()")]
    harness = '''
import streamlit as st
def api(method, path, json):
    st.session_state.setdefault("calls", []).append((path, json))
    if path.endswith("/resolve"):
        return {"candidates": []}
    return {"answer": "Please describe the error."}
'''
    app = AppTest.from_string(harness + render + "\nrender_resolve_ticket()\n").run()
    app.chat_input[0].set_value("Connection failed").run()
    app.chat_input[0].set_value("Actually, disk is full").run()
    assert not app.exception
    calls = app.session_state["calls"]
    assert [body["summary"] for path, body in calls if path.endswith("/resolve")] == [
        "Connection failed", "Actually, disk is full"]
    assert len(calls[-1][1]["history"]) == 2
    assert len(app.session_state["resolve_messages"]) == 4
    app.button(key="new_resolve_chat").click().run()
    assert not app.exception
    assert app.session_state["resolve_messages"] == []
    assert "resolve_candidates" not in app.session_state


def test_resolve_returns_resolution_and_grounded_followup(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    monkeypatch.setattr(api_module, "db", SimpleNamespace(sessions=lambda: nullcontext(None)))
    monkeypatch.setattr(api_module, "SqlRepositories", lambda session: SimpleNamespace(get_version=lambda key: None))
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
])
def test_grounded_answer_requires_question(body):
    assert TestClient(api_module.app).post("/api/tickets/grounded-answer", json=body).status_code == 400


@pytest.mark.parametrize("evidence", [[], [{"title": "Missing resolution"}]])
def test_grounded_answer_allows_conversation_without_new_evidence(monkeypatch, evidence):
    calls = []

    class LLM:
        def structured(self, **kwargs):
            calls.append(kwargs)
            return GroundedAnswer(answer="Which error do you see?", confidence=0.0, evidence=[])

    monkeypatch.setattr(api_module, "make_llm", lambda: LLM())
    response = TestClient(api_module.app).post("/api/tickets/grounded-answer", json={
        "question": "Help", "evidence": evidence,
        "history": [{"role": "user", "content": "My connection failed"}],
    })
    assert response.status_code == 200
    assert response.json()["evidence"] == []
    assert "No new KEDB articles" in calls[0]["user"]
    assert "My connection failed" in calls[0]["user"]
    assert "Never invent technical details" in calls[0]["system"]


def test_resolve_loads_published_resolution_for_index_results(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from kedb.domain import ArticleStatus
    document = {"known_error_id": uuid4(), "article_version_id": uuid4(),
                "title": "Oracle timeout", "content": "ORA-12170", "error_codes": ["ORA-12170"]}
    monkeypatch.setattr(api_module, "make_search_adapter", lambda: InMemorySearch([document]))
    monkeypatch.setattr(api_module, "db", SimpleNamespace(sessions=lambda: nullcontext(None)))
    version = SimpleNamespace(status=ArticleStatus.PUBLISHED, solution="Restore listener", root_cause="Listener stopped")
    monkeypatch.setattr(api_module, "SqlRepositories", lambda session: SimpleNamespace(get_version=lambda key: version))
    client = TestClient(api_module.app)
    body = {"summary": "ORA-12170", "description": ""}
    assert client.post("/api/tickets/resolve", json=body).json()["candidates"][0]["resolution"] == "Restore listener"
    assert client.post("/api/tickets/resolve", json=body).json()["candidates"][0]["root_cause"] == "Listener stopped"
    version.status = ArticleStatus.DRAFT
    assert client.post("/api/tickets/resolve", json=body).json()["candidates"][0]["resolution"] == ""


@pytest.mark.parametrize("identifier, description, expected_calls", [
    ("ORA-12170", "", ["FULL_TEXT"]),
    ("", "Timeout", ["FULL_TEXT", "ANN"]),
    ("ORA-12170", "Timeout", ["FULL_TEXT", "FULL_TEXT", "ANN"]),
])
def test_search_tab_routes_fields_and_loads_resolution(monkeypatch, identifier, description, expected_calls):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from kedb.domain import RetrievalCandidate, ArticleStatus
    calls = []
    candidate = RetrievalCandidate(known_error_id=uuid4(), article_version_id=uuid4(),
                                   title="Match", search_score=0.87, exact_score=1.0)
    class Search:
        def search(self, query, identifiers, **kwargs):
            calls.append(kwargs['query_type'])
            return [candidate, candidate]
    monkeypatch.setattr(api_module, 'make_search_adapter', lambda: Search())
    monkeypatch.setattr(api_module, 'db', SimpleNamespace(sessions=lambda: nullcontext(None)))
    version = SimpleNamespace(status=ArticleStatus.PUBLISHED, solution='Fix', root_cause='Cause')
    monkeypatch.setattr(api_module, 'SqlRepositories', lambda session: SimpleNamespace(get_version=lambda key: version))
    client = TestClient(api_module.app)
    response = client.post('/api/kedb/search', json={'summary': identifier, 'description': description})
    assert response.status_code == 200
    rows = response.json()['candidates']
    assert calls == expected_calls
    assert response.json()['query'] == {'identifier': identifier, 'description': description}
    assert len(rows) == 1
    assert rows[0]['final_score'] == pytest.approx(2 / 61 if identifier and description else 1.0 if identifier else 0.87)
    assert rows[0]['root_cause'] == 'Cause'
    assert rows[0]['resolution'] == 'Fix'
    assert not {'lexical_score', 'vector_score', 'search_score', 'exact_score'} & rows[0].keys()
    calls.clear()
    client.post('/api/tickets/resolve', json={'summary': 'Timeout', 'description': ''})
    assert calls == ['FULL_TEXT', 'ANN']
