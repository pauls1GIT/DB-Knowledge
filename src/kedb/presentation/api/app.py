from __future__ import annotations
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from langgraph.types import Command
from kedb.domain.entities import JiraIssue
from kedb.infrastructure.persistence.repositories import SqlAlchemyKnowledgeRepository, PostgresExactSearcher, PostgresLexicalSearcher
from kedb.infrastructure.embeddings.ollama_embeddings import OllamaEmbeddingProvider
from kedb.infrastructure.vectorstore.chroma import ChromaVectorStore
from kedb.infrastructure.llm.ollama_qwen import OllamaQwenLLM
from kedb.infrastructure.persistence.checkpoint import build_checkpointer
from kedb.infrastructure.csv.jira_csv_reader import JiraCsvReader
from kedb.application.services.jira_csv_mapper import JiraCsvMapper
from kedb.application.use_cases.import_jira_csv import ImportJiraCsv
from kedb.application.use_cases.review_queue import ReviewQueue
from kedb.application.retrieval.hybrid import HybridRetrievalCoordinator
from kedb.application.use_cases.publish import PublishApprovedKnowledge
from kedb.application.use_cases.resolve_ticket import ResolveTicket
from kedb.application.workflows.curator_graph import build_curator_graph

app=FastAPI(title="Known Error DB Curator MVP",version="0.2.0")
repo=SqlAlchemyKnowledgeRepository(); embeddings=OllamaEmbeddingProvider(); vectors=ChromaVectorStore(); llm=OllamaQwenLLM()
retrieval=HybridRetrievalCoordinator(PostgresExactSearcher(),PostgresLexicalSearcher(),vectors,embeddings)
publisher=PublishApprovedKnowledge(repo,embeddings,vectors)
graph=build_curator_graph(repo,retrieval,llm,publisher,build_checkpointer())
resolver=ResolveTicket(retrieval,llm)
importer=ImportJiraCsv(repo,JiraCsvReader(),JiraCsvMapper())
queue=ReviewQueue(repo,graph)

class IssueIn(BaseModel):
    external_key: str
    summary: str
    description: str
    resolution: str = ""
    error_code: str | None = None

class SearchIn(BaseModel):
    query: str
    error_code: str | None = None

class ReviewIn(BaseModel):
    decision: str
    reviewer: str = "reviewer"
    feedback: str | None = None
    modified_content: dict | None = None

@app.get("/health")
def health(): return {"status":"ok"}

@app.post("/api/imports/jira-csv")
async def import_jira_csv(file: UploadFile = File(...), include_unresolved: bool = Query(True)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400,"A .csv Jira export is required")
    try:
        return importer.execute(file.filename,await file.read(),include_unresolved=include_unresolved)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc

@app.get("/api/imports/{batch_id}")
def import_status(batch_id: UUID):
    result=repo.get_import_batch_summary(batch_id)
    if not result: raise HTTPException(404,"Import batch not found")
    return result

@app.get("/api/imports/{batch_id}/next")
def next_import_item(batch_id: UUID):
    item=queue.next_item(batch_id)
    return {"batch_id":str(batch_id),"item":item,"complete":item is None}

@app.post("/api/imports/{batch_id}/items/{item_id}/process")
def process_import_item(batch_id: UUID,item_id: UUID):
    try: return queue.process_item(batch_id,item_id)
    except ValueError as exc: raise HTTPException(404,str(exc)) from exc

@app.post("/api/imports/{batch_id}/items/{item_id}/skip")
def skip_import_item(batch_id: UUID,item_id: UUID):
    try: return queue.skip_item(batch_id,item_id)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc

@app.post("/api/jira/issues")
def create_issue(body: IssueIn):
    issue=JiraIssue(**body.model_dump()); repo.save_issue(issue)
    return {"id":str(issue.id),**body.model_dump()}

@app.get("/api/jira/issues/{issue_id}")
def get_issue(issue_id: UUID):
    issue=repo.get_issue(issue_id)
    if not issue: raise HTTPException(404,"Issue not found")
    return repo.issue_to_dict(issue)

@app.post("/api/jira/issues/{issue_id}/process")
def process_issue(issue_id: UUID):
    if not repo.get_issue(issue_id): raise HTTPException(404,"Issue not found")
    workflow_id=uuid4(); cfg={"configurable":{"thread_id":str(workflow_id)}}
    result=graph.invoke({"workflow_id":str(workflow_id),"issue_id":str(issue_id),"revision_count":0},config=cfg)
    return {"workflow_id":str(workflow_id),"status":"AWAITING_REVIEW" if "__interrupt__" in result else "COMPLETED","proposal":result.get("proposal"),"evaluation":result.get("evaluation"),"candidates":result.get("candidates",[])}

@app.get("/api/workflows/{workflow_id}")
def workflow_state(workflow_id: UUID):
    snap=graph.get_state({"configurable":{"thread_id":str(workflow_id)}})
    return {"workflow_id":str(workflow_id),"next":list(snap.next),"values":snap.values}

@app.post("/api/reviews/{workflow_id}")
def review(workflow_id: UUID, body: ReviewIn):
    cfg={"configurable":{"thread_id":str(workflow_id)}}
    if not graph.get_state(cfg).values: raise HTTPException(404,"Workflow not found")
    result=graph.invoke(Command(resume=body.model_dump()),config=cfg)
    queue.sync_review_result(workflow_id,result)
    return {"workflow_id":str(workflow_id),"status":"AWAITING_REVIEW" if "__interrupt__" in result else "COMPLETED","proposal":result.get("proposal"),"publication_result":result.get("publication_result"),"revision_count":result.get("revision_count",0)}

@app.post("/api/retrieval/search")
def search(body: SearchIn):
    issue=JiraIssue(external_key="SEARCH",summary=body.query,description=body.query,resolution="",error_code=body.error_code)
    return [{"known_error_id":str(x.known_error_id),"article_version_id":str(x.article_version_id),"title":x.title,"exact_score":x.exact_score,"lexical_score":x.lexical_score,"vector_score":x.vector_score,"final_score":x.final_score,"rank":x.rank} for x in retrieval.search(issue,body.query)]

@app.post("/api/tickets/resolve")
def resolve(body: IssueIn):
    issue=JiraIssue(**body.model_dump())
    return resolver.execute(issue).model_dump(mode="json")
