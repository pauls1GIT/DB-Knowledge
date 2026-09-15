## What is implemented

- Clean Architecture modular monolith
- PostgreSQL system of record with SQLAlchemy 2.x and Alembic
- versioned Known Errors and immutable ArticleVersion records
- synthetic Jira incident generator
- exact PostgreSQL retrieval
- PostgreSQL full-text/lexical retrieval
- ChromaDB vector retrieval
- Ollama embeddings
- Qwen3 structured LLM outputs through Ollama
- hybrid candidate merge/deduplication/reranking
- LangGraph curator workflow
- mandatory human review with APPROVE / MODIFY / REJECT
- REJECT -> revise -> human review loop
- PostgreSQL-backed LangGraph checkpoints when available
- publication pipeline that only embeds approved/published knowledge
- grounded ticket-resolution endpoint
- FastAPI API
- Streamlit UI
- deterministic unit/retrieval tests

## Architecture

```text
Streamlit -> FastAPI -> Application Use Cases / LangGraph -> Domain
                            ^          ^
                            |          |
                 Infrastructure adapters
                 PostgreSQL / Chroma / Ollama
```

The Domain layer imports no FastAPI, SQLAlchemy, LangGraph, ChromaDB, or Ollama code.

## Prerequisites

- Python 3.12+
- Docker / Docker Compose
- Ollama

Pull the local models:

```bash
ollama pull qwen3:4b
ollama pull nomic-embed-text
```

## Setup

```bash
cp .env.example .env
docker compose up -d
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -e .
alembic upgrade head
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -e .
alembic upgrade head
```

Generate and seed synthetic Jira incidents:

```bash
python scripts/generate_mock_data.py --count 200 --seed 42
python scripts/seed_database.py mock_incidents.json
```

## Run FastAPI

```bash
uvicorn kedb.presentation.api.app:app --reload --port 8000
```

Open Swagger:

```text
http://localhost:8000/docs
```

## Run Streamlit

In another terminal:

```bash
streamlit run src/kedb/presentation/streamlit/app.py
```

## Demo journey

1. Open the Streamlit **Process Incident** tab.
2. Create/process a resolved incident.
3. The LangGraph flow performs hybrid retrieval, evaluation and curation.
4. The graph interrupts at human review.
5. Copy/use the workflow id in **Human Review**.
6. Try `REJECT` with feedback. The Curator revises and the graph interrupts again.
7. Submit `APPROVE`.
8. Publication creates a new immutable ArticleVersion and indexes only that published version into ChromaDB.
9. Open **Search KEDB** and search for the same issue in different wording.
10. Open **Resolve Ticket** to generate a grounded answer using approved KEDB evidence.

## Important endpoints

```text
GET  /health
POST /api/jira/issues
GET  /api/jira/issues/{issue_id}
POST /api/jira/issues/{issue_id}/process
GET  /api/workflows/{workflow_id}
POST /api/reviews/{workflow_id}
POST /api/retrieval/search
POST /api/tickets/resolve
```

## Human-review invariant

```text
Proposal -> Human Review
             | APPROVE -> Publish
             | MODIFY  -> Apply edits -> Publish
             | REJECT  -> Revise -> Human Review
```

Rejected or draft content cannot enter the production Chroma collection.

## Tests

```bash
pytest
```

The included tests cover domain publication/indexing rules, deterministic synthetic data, and hybrid retrieval deduplication. The infrastructure is designed so additional application/workflow tests can use fake repositories, fake vector stores and fake LLM adapters.

## Configuration

See `.env.example`.

Important variables:

```text
DATABASE_URL
LANGGRAPH_CHECKPOINT_URL
CHROMA_PATH
OLLAMA_BASE_URL
OLLAMA_LLM_MODEL
OLLAMA_EMBED_MODEL
RETRIEVAL_EXACT_WEIGHT
RETRIEVAL_VECTOR_WEIGHT
RETRIEVAL_LEXICAL_WEIGHT
```

## limitations

- Jira is represented by locally seeded synthetic incidents rather than a real Jira connection.
- ChromaDB is local persistent storage for the POC and can be replaced behind `VectorStorePort`.
- Ollama/Qwen is local and can be replaced behind `LLMPort` and `EmbeddingPort`.
- PostgreSQL is still the authoritative operational database.
- The first Alembic revision builds the initial metadata schema in one revision; subsequent changes should use normal incremental Alembic migrations.

## CSV curation queue (v0.2)

The primary UI is now **CSV Curation Queue**. Upload a Jira CSV export and the backend:

1. parses Jira columns through `JiraCsvReader`;
2. maps normalized fields with `JiraCsvMapper`;
3. stores the original row in `jira_issue.raw_payload` for traceability;
4. creates an `import_batch` and one `import_item` per row;
5. runs each queued row through the existing LangGraph curator workflow;
6. shows the incident, retrieval/evaluation output, editable proposal, and APPROVE/MODIFY/REJECT controls on one screen;
7. after publication, automatically advances to the next row.

Run the new schema migration after upgrading an existing checkout:

```powershell
alembic upgrade head
```

For the supplied Jira export, the important normalized mappings are:

| Jira CSV | PostgreSQL |
|---|---|
| Issue key | `jira_issue.external_key` |
| Issue id | `jira_issue.external_id` |
| Summary | `jira_issue.summary` |
| Description | `jira_issue.description` |
| Resolution | `jira_issue.resolution` |
| Status | `jira_issue.status` |
| Priority | `jira_issue.priority` |
| Issue Type | `jira_issue.issue_type` |
| Environment | `jira_issue.environment` |
| Parent key | `jira_issue.parent_external_key` |
| Resolved | `jira_issue.resolved_at` |
| Created | `jira_issue.source_created_at` |
| Updated | `jira_issue.source_updated_at` |
| all original columns | `jira_issue.raw_payload` JSONB |

Use **Include unresolved issues** if you want to review every CSV row. Disable it to queue only rows with `Resolution` or `Resolved` populated.

## CSV review decisions

The CSV curation queue uses these exact semantics:

- **APPROVE**: publish the approved proposal to the KEDB, then advance to the next incident.
- **MODIFY**: send reviewer edits/feedback back to the Knowledge Curator, generate a revised proposal, and require human review again for the same incident. It does not publish directly.
- **REJECT**: close the queue item as `REJECTED`, do not publish or embed knowledge, and advance to the next incident.
- **SKIP INCIDENT**: mark the queue item as `SKIPPED` without publishing, then advance immediately to the next incident.
