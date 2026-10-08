# Redeploy to Databricks Free Edition

This repository is configured to run **Streamlit + FastAPI in one Databricks App**.

- The reverse proxy is public on the Databricks App port.
- Streamlit is internal on `127.0.0.1:8501`; the proxy forwards UI HTTP and WebSocket traffic.
- Only `POST /api/jira/webhook` is forwarded to FastAPI; other `/api/` routes remain internal.
- FastAPI is internal on `127.0.0.1:8001`.
- Both processes share the same attached Lakebase, AI Search and model resources.
- Streamlit calls FastAPI using `KEDB_API_URL=http://127.0.0.1:8001`.

This avoids app-to-app authentication and uses only one of the Free Edition app slots.

## 1. Existing Databricks resources

Before deployment, create/attach these resources to the Databricks App:

1. A Lakebase Autoscaling database.
2. The AI Search index, if you already created it.
3. A model serving endpoint, if you intend to use LLM features.

The application can start without AI Search/model configuration. Lakebase is required for persistence.

## 2. Configure the Lakebase endpoint name

Attaching Lakebase injects `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGSSLMODE`.
The OAuth SDK also needs the Lakebase **compute endpoint resource name**.

In Databricks:

`Lakebase Postgres -> your project -> production -> Computes -> Get ID`

Copy the resource name. It looks similar to:

`projects/<project-id>/branches/<branch-id>/endpoints/<endpoint-id>`

Edit `app.yaml` and replace:

`CHANGE_ME_LAKEBASE_ENDPOINT_RESOURCE_NAME`

with that value.

If your AI Search names differ, also edit:

- `DATABRICKS_AI_SEARCH_ENDPOINT`
- `DATABRICKS_AI_SEARCH_INDEX`

## 3. Sync source to the workspace

From PowerShell in this repository:

```powershell
databricks auth login --host https://YOUR-WORKSPACE-URL

databricks sync . "/Workspace/Users/YOUR_EMAIL/known-error-curator"
```

## 4. Deploy

If your app is named `kedb-api` (the name can stay even though it now hosts the UI too):

```powershell
databricks apps deploy kedb-api --source-code-path "/Workspace/Users/YOUR_EMAIL/known-error-curator"
```

Or use Databricks UI:

`Apps -> kedb-api -> Deploy -> choose /Workspace/Users/YOUR_EMAIL/known-error-curator`

## 5. Open the application

The Databricks App URL now opens Streamlit directly.

Use the **Status** page first. You want:

- API: `ok`
- Database: `lakebase`
- database_ready: `true`

If status is `degraded`, the page displays the Lakebase configuration error instead of crashing the deployment.

## 6. First test

1. Open **Process Incident** and ingest `INC-001`.
2. Open **Publish Knowledge** and publish an APPROVE decision.
3. Open **Known Errors** and confirm the article exists.
4. Open **Search KEDB**.

Until the Delta materialization/indexing job has populated AI Search, the API automatically falls back to searching the current published versions from Lakebase.

## Local development

Install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Without `PGHOST`, the backend uses local SQLite (`kedb-local.db`). Start both services with:

```powershell
python start_app.py
```

Open http://localhost:8000.

## Important files

- `app.yaml` - Databricks App startup/configuration
- `start_app.py` - starts FastAPI + Streamlit
- `requirements.txt` - dependencies Databricks installs
- `src/kedb/presentation/api/app.py` - backend
- `src/kedb/presentation/streamlit/app.py` - frontend
- `src/kedb/infrastructure/lakebase/database.py` - Lakebase OAuth + local SQLite fallback


## Jira webhook gateway

`start_app.py` starts FastAPI (8001), Streamlit (8501), and the public proxy
(`DATABRICKS_APP_PORT`, or local `PORT`, default 8000). Keep the public port distinct
from both internal ports. Both internal servers bind only to localhost.

Before deployment, attach READ secret resources named `smtp-password` and
`jira-webhook-token`, as referenced in `app.yaml`. The webhook token is an independent
random secret; use the same value in Jira's `X-Jira-Webhook-Token` header. For local
execution, set `JIRA_WEBHOOK_TOKEN` in `.env`.

After deploying, the webhook URL is:
`https://kedb-api-7474655221377046.aws.databricksapps.com/api/jira/webhook`

Databricks still authenticates requests before they reach the proxy. Jira must send
an OAuth Bearer token from an identity with CAN USE on the app, in addition to the
webhook token. Use a service principal OAuth flow that obtains fresh access tokens;
a permanently pasted access token will expire. See
https://docs.databricks.com/aws/en/dev-tools/databricks-apps/connect-local .
The proxy does not bypass Databricks authentication.

Configure Jira Automation: Issue created -> Send web request, method POST, custom
JSON body as below. Set Content-Type to application/json and both authentication
headers. Hide secret header values in Jira. Wait for the response and inspect the
rule audit log after creating a test ticket.

```json
{
  "webhookEvent": "jira:issue_created",
  "issue": {
    "key": "{{issue.key}}",
    "fields": {
      "summary": {{issue.summary.asJsonString}},
      "description": "{{issue.description.jsonEncode}}",
      "reporter": {"emailAddress": "{{issue.reporter.emailAddress}}"}
    }
  }
}
```

Expected results: 200 sent/already_sent; 401 invalid webhook token; 422 missing
reporter email or issue fields; 503 missing configuration or SMTP failure; 502 an
internal server is unavailable. Databricks can separately return authentication
errors before the request reaches the application. Confirm the UI loads and its
widgets work after deployment to exercise Streamlit's WebSocket connection.


## Email delivery through Jira (default)

The webhook now returns `status: candidates_ready`, `candidate_count`, `candidates`,
`email_subject`, `email_body` (plain text), and `email_body_html` (escaped HTML).
It does not send mail or record successful SMTP delivery in this mode.
`KEDB_EMAIL_DELIVERY=smtp` restores the original SMTP path where networking permits.

After the second Send web request, retain Wait for response and add a smart-value
condition: `{{webResponse.body.status}}` equals `candidates_ready`.
Add Send email (or Send customized email), recipient Reporter, subject
`{{webResponse.body.email_subject}}`, body `{{webResponse.body.email_body_html}}`
in HTML mode (use `email_body` in plain-text mode). Do not insert another web
request between the candidate request and email action. Jira owns delivery and its
audit log records email-action outcomes. Re-running the rule can send another email;
the app cannot confirm or deduplicate mail sent by Jira.

The app's SMTP resource is unused in the default mode. No Google App Password is
needed for the Jira email action. Existing secret attachments can be retained.
