# Known Error Curator — Databricks Free Edition

A redeployable MVP for curating versioned Known Errors on Databricks.

## Recommended Free Edition deployment

This repository deliberately runs **Streamlit and FastAPI inside one Databricks App**:

```text
Browser
  -> Streamlit (public Databricks App port)
       -> FastAPI (localhost:8001)
            -> Lakebase
            -> Databricks AI Search
            -> Model Serving (adapter included)
```

This is simpler than two Databricks Apps because there is no app-to-app OAuth to configure and both frontend/backend share the same attached resources.

Read **REDEPLOY.md** for the exact deployment steps.

## Core invariants implemented

- Published article versions are immutable domain objects.
- Publication requires `APPROVE`, from a human or the automatic low-score policy.
- `MODIFY` requests an AI revision and returns to review.
- Ticket, workflow and normalized content identities prevent repeated publication, including retries.
- `REJECT` cannot publish.
- Updating a Known Error creates a new `ArticleVersion`.
- Only published versions report `can_embed=True`.
- Publication creates an outbox event for retryable downstream indexing.
- Search uses Databricks AI Search when configured and a deterministic Lakebase fallback during initial setup.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python start_app.py
```

Open `http://localhost:8000`.

Without Lakebase environment variables the backend uses `kedb-local.db` (SQLite) for local development only.

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## CSV review UI

The Streamlit application is now centered on a CSV review queue. It supports the `tickets_clean.csv` shape directly:

- `ticket_id` -> incident external key
- `subject` -> incident summary and default knowledge title
- `description` -> incident description and default knowledge problem
- `resolution` -> incident resolution and default knowledge solution
- `status` -> resolved/closed eligibility filter
- `category`, `sub_category`, `priority`, `product_service`, `department` -> reviewer context
- common structured error codes are extracted from ticket text when present

Press **Play** to read `D:\Python\Generate_dataset\tickets_clean.csv`. Local runs use this PC path when available. Databricks runs use the bundled `data/tickets_clean.csv` instead, since the remote server cannot access your PC's drive. Sync the entire project including `data/` and redeploy. The bundled dataset is a snapshot: copy the updated local CSV into `data/tickets_clean.csv` before syncing to refresh it.

Play starts a server background worker for resolved/closed tickets with resolution text. It continues past tickets requiring human review and adds them to the live Ready for review queue. The UI refreshes every three seconds and displays the next proposal after a decision. Closing the browser does not stop the worker while the server remains running. Pause takes effect after the current ticket; Play resumes saved progress, including after a server restart. An error pauses processing at that ticket and is shown in the UI; Play retries it. The current deployment uses one API process and one background worker. CREATE/UPDATE and the update target come from the AI workflow; root cause and the ingest-only control are removed from the UI. Approve publishes, Modify requests an AI revision, and Reject finishes without publication. Reviewing does not pause background processing. Results can be downloaded as CSV. Workflow checkpoints persist in the database so restarting Play reuses completed work.

Set `DATABRICKS_MODEL_ENDPOINT` and provide Databricks authentication (`DATABRICKS_HOST` / `DATABRICKS_TOKEN`, or SDK authentication). Missing model configuration is reported as an error; Play never substitutes fake AI proposals.

Each of the three searches is checked before the AI evaluation: any score strictly above 0.8 rejects the ticket. Otherwise a highest reranked candidate score strictly below 0.2 (including no candidates) automatically drafts and publishes CREATE. Scores exactly 0.2 or 0.8 follow AI evaluation and human review; USE_EXISTING terminates without publication.

New installations and normal app startup create the `publication_claim` table. For SQL-managed deployments apply `migrations/0002_publication_claim.sql` and `migrations/0003_csv_batch.sql`. It adds unique publication identities without deleting existing data. Existing publications are also checked before writing. Identical content is detected after Unicode, case and whitespace normalization; semantic matches depend on retrieval scores. Existing duplicates are not deleted.

## Workflow Graph tab

The Streamlit app now includes a **Workflow Graph** tab. The diagram is generated from the same `GRAPH_NODES` and `GRAPH_EDGES` definitions used by `build_langgraph()`, so it stays aligned with the executable workflow.

The graph exposes:

- Jira field retrieval and structured extraction;
- parallel exact, full-text and vector retrieval;
- candidate merge/reranking;
- evaluator branch for existing vs. new Known Error;
- LangGraph human-review interrupt;
- MODIFY -> AI revision -> human review loop;
- REJECT -> end without publishing;
- high-score automatic rejection and low-score automatic creation;
- publication, versioning, chunking, embeddings and retrieval-index update.

For local LangGraph Studio:

```powershell
$env:PYTHONPATH="src"
pip install -U "langgraph-cli[inmem]"
langgraph dev
```

`langgraph.json` points Studio to `src/kedb/application/workflows/studio.py:graph`.
