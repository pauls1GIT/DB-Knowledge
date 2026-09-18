# Architecture

Dependency direction: Presentation -> Application -> Domain. Infrastructure implements Application ports.

Operational state lives in Lakebase/Postgres. Approved published knowledge is materialized to Unity Catalog/Delta and indexed by Databricks AI Search. Cross-system publication uses an outbox/eventual-materialization pattern.

## Non-negotiable invariants

- Domain imports no Databricks/FastAPI/SQLAlchemy/LangGraph libraries.
- Published article versions are immutable.
- Publication requires APPROVE or MODIFY review decision.
- REJECT always routes to revision and then human review again.
- Only PUBLISHED + current article chunks can be materialized to the production search index.
- Grounded answers carry article-version/chunk evidence.

## Executable LangGraph curator workflow

The curator is now an explicit multi-node LangGraph rather than a single wrapper node. The executable topology is defined in `src/kedb/application/workflows/curator.py` and the Streamlit **Workflow Graph** tab renders the same `GRAPH_NODES` / `GRAPH_EDGES` metadata.

```text
START
  -> Retrieve Jira Fields
  -> Extract Structured Error Information
       -> Exact Search -----------\
       -> Full Text Search --------> Combine Candidates -> Rerank Candidates
       -> Vector Search ----------/
  -> Suitable Known Error Found?
       -> existing -> Propose Existing Known Error Revision --\
       -> new      -> Generate New Known Error Candidate ------> Human Review
                                                                  | APPROVE
                                                                  | MODIFY -> Reviewer Edits
                                                                  | REJECT -> AI Revision -> Human Review
                                                                  v
                                                               Approve
                                                                  v
                                                       Publish Approved Knowledge
                                                                  v
                                                       Create / Update Version
                                                                  v
                                                             Chunk Content
                                                                  v
                                                        Generate Embeddings
                                                                  v
                                                       Update Retrieval Index
                                                                  v
                                                       Ready for Future Jira
                                                                  v
                                                                 END
```

For local LangGraph Studio, `langgraph.json` exposes `src/kedb/application/workflows/studio.py:graph` with deterministic fake adapters, so Studio can be used without Databricks connectivity.
