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

## JSON and Jira incident input

Select **JSON** or **Jira API** in the Incident Review tab, then press **Play**.
JSON accepts an uploaded file or reads `KEDB_JSON_PATH` on the server, defaulting to
`data/tickets_clean.json`. The bundled dataset has been converted from CSV. Input is an
array of objects, for example:

```json
[
  {
    "ticket_id": "TKT-1",
    "subject": "Database timeout ORA-12170",
    "description": "Database connection fails.",
    "resolution": "Restore the listener.",
    "status": "Resolved"
  }
]
```

All five fields are required (values must be strings or null); ticket ID, subject and
status must be nonempty. Optional metadata fields from the previous dataset are accepted.
Only Resolved/Closed tickets with nonempty resolution text enter the queue; duplicate
keys within one input are skipped.

For **Jira Cloud**, configure `JIRA_BASE_URL`, `JIRA_EMAIL` and `JIRA_API_TOKEN` in the
backend environment. Enter a JQL query in the UI or set `JIRA_JQL` (default:
`statusCategory = Done ORDER BY key ASC`). The adapter uses the
[enhanced Jira search API](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/)
and follows pagination tokens. Jira descriptions and custom resolution fields support
Atlassian Document Format. Done-category statuses map to Resolved. Set
`JIRA_RESOLUTION_FIELD=customfield_10042` (your actual field ID) to ingest remediation
text; the default native `resolution` field supplies only its label, such as ?Fixed?.
Jira Server/Data Center is not supported by this adapter.

API clients can POST `/api/batches/play` with `{"source":"json","tickets":[...]}`
or `{"source":"jira","jql":"project = OPS AND statusCategory = Done ORDER BY key ASC"}`.
An empty body reads the server JSON file. **Resume current batch** resumes the stored
snapshot without fetching Jira again; Play fetches the selected input and reuses a
batch when its source and normalized items are unchanged.

Play starts a server background worker for resolved/closed tickets with resolution text. It continues past tickets requiring human review and adds them to the live Ready for review queue. The UI refreshes every three seconds and displays the next proposal after a decision. Closing the browser does not stop the worker while the server remains running. Pause takes effect after the current ticket; Play resumes saved progress, including after a server restart. An error pauses processing at that ticket and is shown in the UI; Resume current batch retries it. The current deployment uses one API process and one background worker. CREATE/UPDATE and the update target come from the AI workflow; root cause and the ingest-only control are removed from the UI. Approve publishes, Modify requests an AI revision, and Reject finishes without publication. Reviewing does not pause background processing. Results can be downloaded as CSV. Workflow checkpoints persist in the database so restarting Play reuses completed work.

Set `DATABRICKS_MODEL_ENDPOINT` and provide Databricks authentication (`DATABRICKS_HOST` / `DATABRICKS_TOKEN`, or SDK authentication). When no Databricks model endpoint is configured, the app uses the Ollama provider at `http://localhost:11434/v1` with model `llama3.2:3b`; this requires a running Ollama server and that model. Play never substitutes fake AI proposals.

Full-text and vector scores contribute 50% each. A combined score strictly above 0.70 rejects the ticket; a score strictly below 0.35 (including no candidates) automatically drafts and publishes CREATE. Boundary scores require AI evaluation and human review.

New installations and normal app startup create the `publication_claim` table. For SQL-managed deployments apply `migrations/0002_publication_claim.sql` and `migrations/0003_csv_batch.sql`. It adds unique publication identities without deleting existing data. Existing publications are also checked before writing. Identical content is detected after Unicode, case and whitespace normalization; semantic matches depend on retrieval scores. Existing duplicates are not deleted.

## Workflow Graph tab

The Streamlit app now includes a **Workflow Graph** tab. The diagram is generated from the same `GRAPH_NODES` and `GRAPH_EDGES` definitions used by `build_langgraph()`, so it stays aligned with the executable workflow.

The graph exposes:

- Jira field retrieval and structured extraction;
- parallel full-text and vector retrieval;
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


## Article chunks and publication delivery

The app consumes `publication_outbox` in a separate background worker every 30 seconds.
Attach a SQL warehouse resource named `sql-warehouse` with CAN_USE; `app.yaml` resolves
its ID into `DATABRICKS_WAREHOUSE_ID`. Set `KEDB_UC_CHUNK_TABLE` to the existing Delta
chunk table. The app service principal needs USE CATALOG, USE SCHEMA, SELECT and MODIFY
on the chunk table, and permission to synchronize the configured AI Search index.

Approval first commits an article and outbox event to Lakebase. The worker writes
nonempty semantic chunks with stable IDs, retires older versions from current search,
and requests an index sync. Only after both operations succeed is the event processed.
Existing pending approvals are picked up automatically on deployment; failed operations
remain pending and retry. Status shows pending publications and the last delivery error.
A successful sync request is asynchronous; it does not mean embeddings are already ready.

`jobs/publish_materialization.py` is an optional one-shot consumer using the same code
and app/Lakebase credentials. Do not run a separate consumer concurrently with the app.


## Resolve Ticket and Search KEDB

The **Resolve Ticket** tab retrieves matching KEDB knowledge and answers follow-up
questions using the retrieved resolutions and conversation history. **Search KEDB**
shows matching articles and their resolutions. The API exposes
`POST /api/tickets/resolve` (summary, description) and
`POST /api/tickets/grounded-answer` (question, evidence, optional history).
Databricks AI Search results obtain full published resolutions from Lakebase.

Integrated from `pauls1GIT/DB-Knowledge`, branch `andrei-resolve-ticket`, commit
`cbd5d34c2c3c450f2c4ee73e9ff3465f27d9e6d8`. Existing incident input, Jira
connection settings, and background review behavior are preserved.
The optional `scripts/seed_local_kedb.py` adds a sample article to a local SQLite
database; it is not run automatically.


### New Jira ticket emails and manual management

Configure a Jira Automation rule triggered by issue creation to POST to `/api/jira/webhook`, with header `X-Jira-Webhook-Token` matching the server's `JIRA_WEBHOOK_TOKEN`. The JSON payload must include `webhookEvent: "jira:issue_created"` and `issue.key`, `issue.fields.summary`, `issue.fields.description`, and `issue.fields.reporter.emailAddress`. Ensure Jira permits access to the reporter email; missing addresses return 422 rather than sending to another recipient.

Set `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_FROM`, `SMTP_USERNAME`, and `SMTP_PASSWORD`. `SMTP_STARTTLS` defaults to true. The reporter receives the top three published candidates (or fewer when fewer exist). Failed delivery returns 503 so the automation can retry. Successful deliveries are recorded to suppress repeated webhook events. SMTP delivery and database commit are not atomic: a process failure immediately after delivery can cause a duplicate on retry. Apply `migrations/0004_jira_notification.sql` when provisioning schema through migrations.

The **Manage Tickets** tab inserts and deletes curator ticket records. It does not delete issues in Jira or published known errors. Tickets referenced by published articles cannot be deleted. Manual insertion does not send a Jira creation notification.

The public reverse proxy now forwards `/api/jira/webhook` to the internal API and
supports Streamlit HTTP/WebSockets on other UI paths. Deployment and Jira OAuth
requirements are documented in `REDEPLOY.md` under Jira webhook gateway.
