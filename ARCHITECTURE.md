# Architecture

Dependency direction: Presentation -> Application -> Domain. Infrastructure implements Application ports.

Operational state lives in Lakebase/Postgres. Approved published knowledge is materialized to Unity Catalog/Delta and indexed by Databricks AI Search. Cross-system publication uses an outbox/eventual-materialization pattern.

## Non-negotiable invariants

- Domain imports no Databricks/FastAPI/SQLAlchemy/LangGraph libraries.
- Published article versions are immutable.
- Publication requires an APPROVE review, including the deterministic cosine policy.
- REJECT ends the workflow without publication.
- Only PUBLISHED + current article chunks can be materialized to the production search index.
- Grounded answers carry article-version/chunk evidence.

## Executable LangGraph curator workflow

The curator is now an explicit multi-node LangGraph rather than a single wrapper node. The executable topology is defined in `src/kedb/application/workflows/curator.py` and the Streamlit **Workflow Graph** tab renders the same `GRAPH_NODES` / `GRAPH_EDGES` metadata.

```text
START -> Retrieve Jira Fields -> Extract Retrieval Plan
  -> Exact Search  ----\
  -> Hybrid Search ----> Merge Candidates
  -> Generate Article Draft
  -> Embed Draft + Current Published Articles (cached in Lakebase)
  -> Bulk Cached Embeddings + Batched Missing Embeddings
  -> Vectorized Cosine Similarity -> Highest Score
       -> >= rejection cutoff -> Reject Duplicate (Keep Audit History) -> END
       -> Between cutoffs -> Human Review -> Approve / Modify / Reject
       -> < approval cutoff -> Automatic Approve -> Publish Article + Outbox
              -> Chunk Materialization -> Managed Search Index Sync -> END

Human reviews: MODIFY -> AI revision -> Human Review
                        REJECT -> END
                        APPROVE -> Publication
```

For local LangGraph Studio, `langgraph.json` exposes `src/kedb/application/workflows/studio.py:graph` with deterministic fake adapters, so Studio can be used without Databricks connectivity.
