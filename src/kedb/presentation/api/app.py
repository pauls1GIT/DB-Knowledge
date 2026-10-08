from __future__ import annotations

import os
import json
import httpx
import hashlib
from pathlib import Path
from contextlib import asynccontextmanager
from uuid import UUID, NAMESPACE_URL, uuid5

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Literal
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from kedb.application.workflows.curator import CuratorWorkflow
from kedb.infrastructure.lakebase.models import WorkflowCheckpointRow, CsvBatchRow, PublicationOutboxRow
from kedb.application.incidents import incidents_from_json, batch_items
from kedb.infrastructure.jira import fetch_incidents
from kedb.application.workflows.batch import BatchWorker

from kedb.application.dto import KnowledgeProposal
from kedb.application.retrieval import RetrievalCoordinator
from kedb.application.use_cases import PublishApprovedKnowledge, GenerateGroundedAnswer
from kedb.config import Settings
from kedb.domain import HumanReview, JiraIssue, ReviewDecision
from kedb.infrastructure.lakebase import Database, SqlRepositories
from kedb.infrastructure.search.in_memory import InMemorySearch

settings = Settings()
db = Database(settings.kedb_database_url)
startup_error: str | None = None
materializer = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global startup_error, materializer
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
    chunk_worker = None
    materializer = None
    if startup_error is None and settings.databricks_warehouse_id:
        from kedb.application.use_cases.materialize import MaterializePublications, MaterializationWorker
        from kedb.infrastructure.delta.sql_chunks import SqlChunkSink
        materializer = MaterializePublications(db, SqlChunkSink(
            warehouse_id=settings.databricks_warehouse_id, table=settings.kedb_uc_chunk_table,
            index_name=settings.databricks_ai_search_index))
        chunk_worker = MaterializationWorker(materializer)
        chunk_worker.start()
    try:
        yield
    finally:
        if chunk_worker:
            chunk_worker.stop()
        if worker:
            worker.stop()


app = FastAPI(title="Known Error Curator", version="0.2.0", lifespan=lifespan)


class JiraIn(BaseModel):
    external_key: str
    summary: str
    description: str
    resolution: str = ""
    error_code: str | None = None


class SearchIn(BaseModel):
    query: str

class ResolveTicketIn(BaseModel):
    summary: str
    description: str


class GroundedQuestionIn(BaseModel):
    question: str
    evidence: list[dict]
    history: list[dict] = []


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
                            "resolution": version.solution,
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
    result = health()
    pending = None
    if startup_error is None:
        with db.sessions() as session:
            pending = session.scalar(select(func.count()).select_from(PublicationOutboxRow).where(
                PublicationOutboxRow.processed.is_(False)))
    result["article_chunks"] = {
        "table": settings.kedb_uc_chunk_table,
        "warehouse_configured": bool(settings.databricks_warehouse_id),
        "worker_running": materializer is not None,
        "pending_publications": pending,
        "last_error": materializer.last_error if materializer else (
            f"Database startup failed: {startup_error}" if startup_error else None
        ),
        "configuration_required": None if settings.databricks_warehouse_id else (
            "Set DATABRICKS_WAREHOUSE_ID to enable chunk materialization"
        ),
    }
    return result


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

@app.post("/api/tickets/resolve")
def resolve_ticket(body: ResolveTicketIn):
    query = f"{body.summary}\n{body.description}"

    retriever = RetrievalCoordinator(make_search_adapter())
    candidates = retriever.search(query, settings.kedb_search_top_k)
    # AI Search indexes chunks; load the complete published resolution from Lakebase.
    results = []
    with db.sessions() as session:
        repo = SqlRepositories(session)
        for candidate in candidates:
            result = dict(candidate.__dict__)
            if not result["resolution"]:
                version = repo.get_version(candidate.article_version_id)
                if version and version.status.value == "PUBLISHED":
                    result["resolution"] = version.solution
            results.append(result)

    return {"query": query, "candidates": results}

@app.post("/api/tickets/grounded-answer")
def grounded_answer(body: GroundedQuestionIn):
    if not body.question.strip():
        raise HTTPException(400, "Question is required.")

    evidence = [
        {
            "title": item["title"],
            "content": item.get("resolution", ""),
            "known_error_id": item.get("known_error_id"),
            "article_version_id": item.get("article_version_id"),
        }
        for item in body.evidence
        if item.get("resolution")
    ]

    if not evidence:
        raise HTTPException(400, "No KEDB resolution evidence was provided.")

    generator = GenerateGroundedAnswer(make_llm())
    return generator.execute(body.question, evidence, body.history)


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
    if settings.databricks_model_endpoint:
        from kedb.infrastructure.llm.databricks_model import DatabricksModelServingProvider

        host, token = settings.databricks_host, settings.databricks_token
        if not host or not token:
            from databricks.sdk import WorkspaceClient

            workspace = WorkspaceClient()
            host = workspace.config.host
            token = workspace.config.authenticate()["Authorization"].removeprefix("Bearer ")

        return DatabricksModelServingProvider(
            base_url=host,
            token=token,
            model=settings.databricks_model_endpoint,
        )

    from kedb.infrastructure.llm.ollama_model import OllamaModelProvider

    return OllamaModelProvider()


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


JSON_BUNDLED_PATH = Path(__file__).resolve().parents[4] / "data" / "tickets_clean.json"


class BatchInput(BaseModel):
    source: Literal["json", "jira"] = "json"
    tickets: list[dict] | None = None
    jql: str | None = None


def process_batch_item(item):
    issue = create_issue(JiraIn(**item))
    return start_workflow(UUID(str(issue["id"])))


@app.post("/api/batches/play")
def play_batch(body: BatchInput | None = None):
    require_database()
    body = body or BatchInput()
    try:
        if body.source == "jira":
            if body.tickets is not None:
                raise ValueError("tickets cannot be combined with Jira input")
            items = batch_items(fetch_incidents(settings, body.jql))
            source = f"Jira: {body.jql or settings.jira_jql}"
            identity = settings.jira_base_url + source
        else:
            if body.jql is not None:
                raise ValueError("jql requires Jira input")
            path = Path(settings.kedb_json_path) if settings.kedb_json_path else JSON_BUNDLED_PATH
            payload = body.tickets if body.tickets is not None else json.loads(path.read_text(encoding="utf-8-sig"))
            items = batch_items(incidents_from_json(payload))
            source = "JSON upload" if body.tickets is not None else str(path)
            identity = source
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Jira API returned HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "Cannot connect to Jira API") from exc
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, f"Cannot load input: {exc}") from exc
    content = json.dumps([identity, items], sort_keys=True, ensure_ascii=False).encode()
    batch_id = hashlib.sha256(content).hexdigest()
    with db.sessions.begin() as session:
        batch = session.get(CsvBatchRow, batch_id)
        if batch is None:
            try:
                with session.begin_nested():
                    session.add(CsvBatchRow(id=batch_id, source=source, items=items,
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
        # Bound SQL parameter counts for large batches.
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


@app.post("/api/batches/{batch_id}/resume")
def resume_batch(batch_id: str):
    require_database()
    with db.sessions.begin() as session:
        batch = session.get(CsvBatchRow, batch_id)
        if batch is None:
            raise HTTPException(404, "Batch not found")
        if batch.position < len(batch.items):
            batch.status = "RUNNING"
            batch.error = None
    return {"batch_id": batch_id}


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


@app.get("/api/jira/issues")
def list_issues():
    require_database()
    from kedb.infrastructure.lakebase.models import JiraIssueRow
    with db.sessions() as session:
        return [{"id": row.id, "external_key": row.external_key, "summary": row.summary}
                for row in session.scalars(select(JiraIssueRow).order_by(JiraIssueRow.created_at.desc()))]


@app.delete("/api/jira/issues/{issue_id}")
def delete_issue(issue_id: UUID):
    require_database()
    from kedb.infrastructure.lakebase.models import JiraIssueRow, ArticleVersionRow
    with db.sessions.begin() as session:
        row = session.get(JiraIssueRow, str(issue_id))
        if row is None:
            raise HTTPException(404, "Issue not found")
        if session.scalar(select(ArticleVersionRow.id).where(ArticleVersionRow.source_jira_issue_id == str(issue_id)).limit(1)):
            raise HTTPException(409, "Ticket is linked to published knowledge and cannot be deleted")
        session.delete(row)
    return {"deleted": str(issue_id)}


@app.post("/api/jira/webhook")
def jira_created(body: dict, x_jira_webhook_token: str = Header(default="")):
    import secrets
    from kedb.infrastructure.jira import jira_text
    from kedb.infrastructure.notifications import send_candidates
    if not settings.jira_webhook_token:
        raise HTTPException(503, "Configure JIRA_WEBHOOK_TOKEN")
    if not secrets.compare_digest(x_jira_webhook_token, settings.jira_webhook_token):
        raise HTTPException(401, "Invalid webhook token")
    if body.get("webhookEvent") == "kedb:smtp_diagnostic":
        from kedb.infrastructure.notifications import diagnose_smtp
        return diagnose_smtp(settings)
    if body.get("webhookEvent") != "jira:issue_created":
        return {"status": "ignored"}
    raw = body.get("issue") or {}
    fields = raw.get("fields") or {}
    if not raw.get("key") or not fields.get("summary"):
        raise HTTPException(422, "Issue key and summary are required")
    recipient = (fields.get("reporter") or {}).get("emailAddress")
    if settings.kedb_email_delivery == "smtp" and not recipient:
        raise HTTPException(422, "Reporter emailAddress is required in the webhook payload")
    issue = create_issue(JiraIn(external_key=raw["key"], summary=fields["summary"],
                               description=jira_text(fields.get("description"))))
    candidates = RetrievalCoordinator(make_search_adapter()).search(
        fields["summary"] + " " + jira_text(fields.get("description")), top_k=3)
    if settings.kedb_email_delivery == "jira":
        from kedb.infrastructure.notifications import candidate_email
        return {**candidate_email(raw["key"], fields["summary"], candidates), "issue_id": issue["id"]}
    from kedb.infrastructure.lakebase.models import JiraNotificationRow
    try:
        with db.sessions.begin() as session:
            if session.get(JiraNotificationRow, raw["key"]):
                return {"status": "already_sent", "issue_id": issue["id"]}
            session.add(JiraNotificationRow(external_key=raw["key"]))
            session.flush()
            send_candidates(settings, JiraIssue(**issue), recipient, candidates)
    except IntegrityError:
        return {"status": "already_sent", "issue_id": issue["id"]}
    except (ValueError, OSError) as exc:
        raise HTTPException(503, "Candidate email could not be sent; check SMTP configuration and retry") from exc
    return {"status": "sent", "candidate_count": len(candidates), "issue_id": issue["id"]}
