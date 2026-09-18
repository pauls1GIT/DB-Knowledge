# Redeploy to Databricks Free Edition

This repository is configured to run **Streamlit + FastAPI in one Databricks App**.

- Streamlit is public on the Databricks App port.
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
