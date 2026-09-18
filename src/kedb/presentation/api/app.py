from __future__ import annotations

import os
import csv
import hashlib
import io
from pathlib import Path
from contextlib import asynccontextmanager
from uuid import UUID, NAMESPACE_URL, uuid5

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from kedb.application.workflows.curator import CuratorWorkflow
from kedb.infrastructure.lakebase.models import WorkflowCheckpointRow, CsvBatchRow
from kedb.application.csv_incidents import incident_from_row, resolve_csv_path, REQUIRED_COLUMNS
from kedb.application.workflows.batch import BatchWorker

from kedb.application.dto import KnowledgeProposal
from kedb.application.retrieval import RetrievalCoordinator
from kedb.application.use_cases import PublishApprovedKnowledge
from kedb.config import Settings
from kedb.domain import HumanReview, JiraIssue, ReviewDecision
from kedb.infrastructure.lakebase import Database, SqlRepositories
from kedb.infrastructure.search.in_memory import InMemorySearch

settings = Settings()
db = Database(settings.kedb_database_url)
startup_error: str | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global startup_error
    try:
        db.create_all()
        db.ping()
        startup_error = None
    except Exception as exc:  # Keep UI up so configuration errors are visible.
        startup_error = f"{type(exc).__name__}: {exc}"
        print(f"Database startup check failed: {startup_error}", flush=True)
    worker = BatchWorker(db, process_batch_item) if startup_error is None else None
    if worker:
        worker.start()
    try:
        yield
    finally:
        if worker:
            worker.stop()


app = FastAPI(title="Known Error Curator", version="0.2.0", lifespan=lifespan)


class JiraIn(BaseModel):
    external_key: str
    summary: str
    description: str
    resolution: str
    error_code: str | None = None


class SearchIn(BaseModel):
    query: str


class ReviewIn(BaseModel):
    decision: ReviewDecision
    reviewer: str
    feedback: str | None = None
    modified_content: dict | None = None


class PublishIn(BaseModel):
    workflow_id: UUID
    jira_issue_id: UUID | None = None
    proposal: KnowledgeProposal
    review: ReviewIn


def require_database() -> None:
    if startup_error:
        raise HTTPException(status_code=503, detail=startup_error)


def make_search_adapter():
    endpoint = settings.databricks_ai_search_endpoint
    index = settings.databricks_ai_search_index
    if endpoint and index:
        try:
            from kedb.infrastructure.search.databricks_ai_search import DatabricksAISearch

            return DatabricksAISearch(endpoint_name=endpoint, index_name=index)
        except Exception as exc:
            print(f"AI Search unavailable; falling back to database search: {exc}", flush=True)

    require_database()
    with db.sessions() as session:
        repo = SqlRepositories(session)
        docs = []
        for ke in repo.list_known_errors():
            for version in repo.list_versions(ke.id):
                if ke.current_version_id == version.id and version.can_embed:
                    docs.append(
                        {
                            "known_error_id": ke.id,
                            "article_version_id": version.id,
                            "title": version.title,
                            "content": " ".join(
                                [version.problem, version.root_cause, version.solution]
                            ),
                        }
                    )
    return InMemorySearch(docs)


@app.get("/health")
def health():
    return {
        "status": "ok" if startup_error is None else "degraded",
        "database": db.mode,
        "database_ready": startup_error is None,
        "ai_search_configured": bool(
            settings.databricks_ai_search_endpoint and settings.databricks_ai_search_index
        ),
        "error": startup_error,
    }


@app.get("/api/system/status")
def system_status():
    return health()


@app.post("/api/jira/issues")
def create_issue(body: JiraIn):
    require_database()
    issue = JiraIssue(**body.model_dump())
    with db.sessions.begin() as session:
        repo = SqlRepositories(session)
        existing = repo.get_jira_by_external_key(issue.external_key)
        if existing:
            return existing.__dict__
        try:
            with session.begin_nested():
                repo.add_jira(issue)
        except IntegrityError:
            existing = repo.get_jira_by_external_key(issue.external_key)
            if existing:
                return existing.__dict__
            raise
    return issue.__dict__


@app.get("/api/jira/issues/by-key/{external_key}")
def get_issue_by_key(external_key: str):
    require_database()
    with db.sessions() as session:
        issue = SqlRepositories(session).get_jira_by_external_key(external_key)
    if not issue:
        raise HTTPException(404, "Issue not found")
    return issue.__dict__


@app.get("/api/jira/issues/{issue_id}")
def get_issue(issue_id: UUID):
    require_database()
    with db.sessions() as session:
        issue = SqlRepositories(session).get_jira(issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")
    return issue.__dict__


@app.get("/api/known-errors")
def known_errors():
    require_database()
    with db.sessions() as session:
        return [item.__dict__ for item in SqlRepositories(session).list_known_errors()]


@app.get("/api/known-errors/{known_error_id}/versions")
def versions(known_error_id: UUID):
    require_database()
    with db.sessions() as session:
        return [item.__dict__ for item in SqlRepositories(session).list_versions(known_error_id)]


@app.post("/api/retrieval/search")
def search(body: SearchIn):
    retriever = RetrievalCoordinator(make_search_adapter())
    return [candidate.__dict__ for candidate in retriever.search(body.query, settings.kedb_search_top_k)]


@app.post("/api/publications")
def publish(body: PublishIn):
    require_database()
    review = HumanReview(
        workflow_id=body.workflow_id,
        decision=body.review.decision,
        reviewer=body.review.reviewer,
        feedback=body.review.feedback,
        modified_content=body.review.modified_content,
    )
    try:
        with db.sessions.begin() as session:
            published = PublishApprovedKnowledge(SqlRepositories(session)).execute(
                proposal=body.proposal,
                review=review,
                jira_issue_id=body.jira_issue_id,
            )
        return {
            "article_version_id": published.id,
            "known_error_id": published.known_error_id,
            "version_number": published.version_number,
            "status": published.status,
        }
    except (ValueError, LookupError) as exc:
        raise HTTPException(400, str(exc)) from exc


def make_llm():
    from kedb.infrastructure.llm.databricks_model import DatabricksModelServingProvider

    if not settings.databricks_model_endpoint:
        raise HTTPException(503, "Set DATABRICKS_MODEL_ENDPOINT to run the AI curator.")
    host, token = settings.databricks_host, settings.databricks_token
    if not host or not token:
        from databricks.sdk import WorkspaceClient
        workspace = WorkspaceClient()
        host = workspace.config.host
        token = workspace.config.authenticate()["Authorization"].removeprefix("Bearer ")
    return DatabricksModelServingProvider(
        base_url=host, token=token, model=settings.databricks_model_endpoint)


def workflow_for(session):
    def publisher(state):
        if session is None:
            with db.sessions.begin() as publication_session:
                return workflow_for(publication_session).publisher(state)
        review = state["review"]
        article = PublishApprovedKnowledge(SqlRepositories(session)).execute(
            proposal=KnowledgeProposal.model_validate(state["proposal"]),
            review=HumanReview(workflow_id=UUID(state["workflow_id"]),
                              decision=ReviewDecision(review["decision"]),
                              reviewer=review.get("reviewer", "human-reviewer"),
                              feedback=review.get("feedback")),
            jira_issue_id=UUID(state["issue"]["id"]),
        )
        return {"article_version_id": str(article.id), "known_error_id": str(article.known_error_id),
                "version_number": article.version_number, "status": article.status.value}
    return CuratorWorkflow(make_llm(), RetrievalCoordinator(make_search_adapter()), publisher=publisher)


def save_workflow(row, state):
    row.state = state
    row.status = state["status"]
    row.current_step = state["status"]
    row.revision_count = state.get("revision_count", 0)


@app.post("/api/workflows/{issue_id}/start")
def start_workflow(issue_id: UUID):
    require_database()
    workflow_id = str(uuid5(NAMESPACE_URL, f"kedb:issue:{issue_id}"))
    with db.sessions.begin() as session:
        issue = SqlRepositories(session).get_jira(issue_id)
        if issue is None:
            raise HTTPException(404, "Issue not found")
        row = session.get(WorkflowCheckpointRow, workflow_id)
        if row is None:
            try:
                with session.begin_nested():
                    session.add(WorkflowCheckpointRow(workflow_id=workflow_id, status="NEW",
                                current_step="NEW", state={}))
                    session.flush()
            except IntegrityError:
                pass  # A concurrent request created the same workflow.
        row = session.scalars(select(WorkflowCheckpointRow).where(
            WorkflowCheckpointRow.workflow_id == workflow_id).with_for_update().execution_options(populate_existing=True)).one()
        if row.state:
            return row.state
    # Model calls run outside a database transaction so reviewing another ticket
    # does not wait for the background worker's model response.
    workflow = workflow_for(None)
    state = workflow.start({**issue.__dict__, "id": str(issue.id)}, workflow_id=workflow_id)
    with db.sessions.begin() as session:
        row = session.scalars(select(WorkflowCheckpointRow).where(
            WorkflowCheckpointRow.workflow_id == workflow_id).with_for_update()).one()
        if row.state:
            return row.state
        save_workflow(row, state)
    return state


@app.post("/api/workflows/{workflow_id}/review")
def review_workflow(workflow_id: UUID, body: ReviewIn):
    require_database()
    with db.sessions() as session:
        row = session.get(WorkflowCheckpointRow, str(workflow_id))
        if row is None:
            raise HTTPException(404, "Workflow not found")
        if row.status != "WAITING_FOR_REVIEW":
            return row.state
        previous = row.state
    workflow = workflow_for(None)
    try:
        state = workflow.apply_review(previous, body.model_dump(mode="json"))
        with db.sessions.begin() as session:
            row = session.scalars(select(WorkflowCheckpointRow).where(
                WorkflowCheckpointRow.workflow_id == str(workflow_id)).with_for_update()).one()
            if row.state != previous:
                raise HTTPException(409, "This proposal has changed. Refresh before reviewing again.")
            if state["status"] == "APPROVED_FOR_PUBLICATION":
                workflow = workflow_for(session)
                state = workflow.publish(state)
            save_workflow(row, state)
    except (ValueError, LookupError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return state


CSV_LOCAL_PATH = Path(r"D:\Python\Generate_dataset\tickets_clean.csv")
CSV_BUNDLED_PATH = Path(__file__).resolve().parents[4] / "data" / "tickets_clean.csv"


def process_batch_item(item):
    issue = create_issue(JiraIn(**item))
    return start_workflow(UUID(str(issue["id"])))


@app.post("/api/batches/play")
def play_batch():
    require_database()
    path = resolve_csv_path(CSV_LOCAL_PATH, CSV_BUNDLED_PATH)
    try:
        content = path.read_bytes()
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        missing = (REQUIRED_COLUMNS | {"resolution"}).difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
        items, seen = [], set()
        for row in reader:
            incident = incident_from_row(row)
            if not incident.is_resolved or incident.external_key in seen:
                continue
            if not incident.external_key:
                raise ValueError("CSV contains a resolved ticket without a ticket_id")
            seen.add(incident.external_key)
            items.append({key: getattr(incident, key) for key in
                          ("external_key", "summary", "description", "resolution", "error_code")})
    except (OSError, ValueError) as exc:
        raise HTTPException(400, f"Cannot read server CSV {path}: {exc}") from exc
    batch_id = hashlib.sha256(content).hexdigest()
    with db.sessions.begin() as session:
        batch = session.get(CsvBatchRow, batch_id)
        if batch is None:
            try:
                with session.begin_nested():
                    session.add(CsvBatchRow(id=batch_id, source=str(path), items=items,
                        position=0, results=[], status="RUNNING" if items else "COMPLETE"))
                    session.flush()
            except IntegrityError:
                pass
            batch = session.get(CsvBatchRow, batch_id)
        if batch.position < len(batch.items):
            batch.status = "RUNNING"
            batch.error = None
    return {"batch_id": batch_id}


def batch_status(batch_id):
    with db.sessions() as session:
        batch = session.get(CsvBatchRow, batch_id)
        if batch is None:
            raise HTTPException(404, "Batch not found")
        results = [dict(result) for result in batch.results]
        ids = {result["workflow_id"] for result in results}
        statuses = {}
        # Bound SQL parameter counts for large CSVs.
        ids = list(ids)
        for offset in range(0, len(ids), 500):
            statuses.update(dict(session.execute(select(
                WorkflowCheckpointRow.workflow_id, WorkflowCheckpointRow.status).where(
                WorkflowCheckpointRow.workflow_id.in_(ids[offset:offset + 500]))).all()))
        for result in results:
            result["status"] = statuses.get(result["workflow_id"], result["status"])
        waiting = [result for result in results if result["status"] == "WAITING_FOR_REVIEW"]
        return {"batch_id": batch.id, "source": batch.source, "status": batch.status,
                "processed": batch.position, "total": len(batch.items), "error": batch.error,
                "waiting": waiting, "results": results}


@app.get("/api/batches/current")
def current_batch():
    require_database()
    with db.sessions() as session:
        batch_id = session.scalar(select(CsvBatchRow.id).order_by(CsvBatchRow.created_at.desc()))
    return batch_status(batch_id) if batch_id else None


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str):
    require_database()
    return batch_status(batch_id)


@app.post("/api/batches/{batch_id}/pause")
def pause_batch(batch_id: str):
    require_database()
    with db.sessions.begin() as session:
        batch = session.get(CsvBatchRow, batch_id)
        if batch is None:
            raise HTTPException(404, "Batch not found")
        if batch.status == "RUNNING":
            batch.status = "PAUSED"
    return {"batch_id": batch_id}


@app.get("/api/workflows/{workflow_id}")
def get_workflow(workflow_id: UUID):
    require_database()
    with db.sessions() as session:
        row = session.get(WorkflowCheckpointRow, str(workflow_id))
        if row is None:
            raise HTTPException(404, "Workflow not found")
        return row.state
