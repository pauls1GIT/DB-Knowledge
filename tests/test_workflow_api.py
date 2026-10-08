from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select, func

from kedb.presentation.api import app as api_module
from kedb.infrastructure.lakebase import Database
from kedb.infrastructure.lakebase.models import ArticleVersionRow, JiraIssueRow
from kedb.application.dto import KnowledgeProposal, RetrievalPlan, EvaluationResult
from kedb.infrastructure.llm.fake import FakeLLM
from kedb.infrastructure.search.in_memory import InMemorySearch


def test_api_play_persists_publication_and_retries(tmp_path, monkeypatch):
    db = Database(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(api_module, "db", db)
    monkeypatch.setattr(api_module, "make_search_adapter", lambda: InMemorySearch([]))
    monkeypatch.setattr(api_module, "make_llm", lambda: FakeLLM({
        RetrievalPlan: RetrievalPlan(semantic_query="new failure"),
        KnowledgeProposal: KnowledgeProposal(action="CREATE", title="t", problem="p", root_cause="r", solution="s"),
    }))
    with TestClient(api_module.app) as client:
        body = dict(external_key="T-1", summary="t", description="d", resolution="s")
        issue = client.post("/api/jira/issues", json=body).json()
        assert client.post("/api/jira/issues", json=body).json()["id"] == issue["id"]
        response = client.post(f"/api/workflows/{issue['id']}/start")
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["proposal"]["action"] == "CREATE"
        assert state["publication_result"]["version_number"] == 1
        assert client.post(f"/api/workflows/{issue['id']}/start").json() == state
        assert client.post(f"/api/workflows/{state['workflow_id']}/review", json={
            "decision": "APPROVE", "reviewer": "alice"}).json() == state
    with db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JiraIssueRow)) == 1
        assert session.scalar(select(func.count()).select_from(ArticleVersionRow)) == 1


def test_review_api_modify_then_reject_never_publishes(tmp_path, monkeypatch):
    from kedb.infrastructure.lakebase.models import WorkflowCheckpointRow
    from kedb.application.workflows.curator import CuratorWorkflow
    db = Database(f"sqlite+pysqlite:///{tmp_path / 'review.db'}")
    db.create_all()
    monkeypatch.setattr(api_module, "db", db)
    workflow_id = str(uuid4())
    proposal = KnowledgeProposal(action="CREATE", title="t", problem="p", root_cause="r", solution="s")
    wf = CuratorWorkflow(FakeLLM({KnowledgeProposal: proposal}), None,
                         publisher=lambda _: (_ for _ in ()).throw(AssertionError("Published")))
    monkeypatch.setattr(api_module, "workflow_for", lambda session: wf)
    with db.sessions.begin() as session:
        session.add(WorkflowCheckpointRow(workflow_id=workflow_id, status="WAITING_FOR_REVIEW",
            current_step="human_review", state={"workflow_id": workflow_id,
            "status": "WAITING_FOR_REVIEW", "proposal": proposal.model_dump(mode="json")}))
    with TestClient(api_module.app) as client:
        response = client.post(f"/api/workflows/{workflow_id}/review", json={
            "decision": "MODIFY", "reviewer": "alice", "feedback": "revise"})
        assert response.status_code == 200
        assert response.json()["revision_count"] == 1
        assert response.json()["status"] == "WAITING_FOR_REVIEW"
        response = client.post(f"/api/workflows/{workflow_id}/review", json={
            "decision": "REJECT", "reviewer": "alice"})
        assert response.json()["status"] == "REJECTED"
    with db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ArticleVersionRow)) == 0


def test_batch_play_returns_immediately_and_restores_saved_queue(tmp_path, monkeypatch):
    from kedb.application.workflows.batch import BatchWorker
    from kedb.infrastructure.lakebase.models import CsvBatchRow
    db = Database(f"sqlite+pysqlite:///{tmp_path / 'batch_api.db'}")
    monkeypatch.setattr(api_module, "db", db)
    import json
    dataset = tmp_path / "tickets.json"
    dataset.write_text(json.dumps([
        {"ticket_id": key, "subject": title, "description": "Issue", "resolution": fix, "status": status}
        for key, title, fix, status in [("T-1", "One", "Fix", "Resolved"),
            ("T-2", "Two", "Fix", "Closed"), ("T-1", "Duplicate", "Fix", "Resolved"),
            ("T-3", "Open", "", "Open")]
    ]))
    monkeypatch.setattr(api_module.settings, "kedb_json_path", str(dataset))
    # Control worker steps explicitly to prove Play does not invoke the model inline.
    monkeypatch.setattr(BatchWorker, "start", lambda self: None)
    monkeypatch.setattr(BatchWorker, "stop", lambda self: None)
    monkeypatch.setattr(api_module, "make_search_adapter", lambda: InMemorySearch([]))
    monkeypatch.setattr(api_module, "make_llm", lambda: FakeLLM({
        RetrievalPlan: RetrievalPlan(semantic_query="new failure"),
        KnowledgeProposal: KnowledgeProposal(action="CREATE", title="t", problem="p", root_cause="r", solution="s"),
    }))
    with TestClient(api_module.app) as client:
        assert client.get("/api/batches/current").json() is None
        response = client.post("/api/batches/play")
        assert response.status_code == 200, response.text
        batch_id = response.json()["batch_id"]
        first = client.get(f"/api/batches/{batch_id}").json()
        assert first["total"] == 2
        assert first["processed"] == 0
        assert client.post("/api/batches/play").json()["batch_id"] == batch_id
        worker = BatchWorker(db, api_module.process_batch_item)
        assert worker.process_next()
        assert client.post(f"/api/batches/{batch_id}/pause").status_code == 200
        assert not worker.process_next()
        assert client.get("/api/batches/current").json()["processed"] == 1
        client.post("/api/batches/play")
        assert worker.process_next()
        result = client.get(f"/api/batches/{batch_id}").json()
        assert result["status"] == "COMPLETE"
        assert len(result["results"]) == 2
        workflow_id = result["results"][0]["workflow_id"]
        assert client.get(f"/api/workflows/{workflow_id}").json()["proposal"]["action"] == "CREATE"
        assert client.post("/api/batches/play").json()["batch_id"] == batch_id
        assert not worker.process_next()
    with db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(CsvBatchRow)) == 1
        assert session.scalar(select(func.count()).select_from(ArticleVersionRow)) == 1
