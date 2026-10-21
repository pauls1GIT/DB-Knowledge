from __future__ import annotations

import os
import json

import pandas as pd
import requests
import streamlit as st

from kedb.application.workflows.curator import GRAPH_EDGES, GRAPH_NODES, workflow_dot

API = os.getenv("KEDB_API_URL", "http://127.0.0.1:8001").rstrip("/")
DEFAULT_REVIEWER = os.getenv("KEDB_DEFAULT_REVIEWER", "human-reviewer")

st.set_page_config(page_title="Known Error Curator", page_icon="â–¶", layout="wide")
st.title("Known Error DB Curator")
st.caption("Process tickets in the background and review proposals as they arrive.")


def api(method: str, path: str, **kwargs):
    try:
        response = requests.request(method, f"{API}{path}", timeout=300, **kwargs)
        if not response.ok:
            st.error(f"API {response.status_code}: {response.text}")
            return None
        return response.json()
    except requests.RequestException as exc:
        st.error(f"Cannot reach backend: {exc}")
        return None


def candidate_frame(candidates, *, review=False):
    rows = []
    for candidate in candidates:
        row = {key: value for key, value in candidate.items()
               if key not in {"search_score", "exact_score"}}
        if "root_cause" not in row:
            versions = api("GET", f"/api/known-errors/{row['known_error_id']}/versions") or []
            version = next((v for v in versions if str(v["id"]) == str(row.get("article_version_id"))), {})
            row["root_cause"] = version.get("root_cause") or "Not recorded"
        row["root_cause"] = row.get("root_cause") or "Not recorded"
        if review and ("exact_rank" in candidate or "hybrid_rank" in candidate):
            row = {
                "rank": candidate.get("rank"),
                "title": candidate.get("title"),
                "root_cause": row["root_cause"],
                "exact_match": candidate.get("exact_score", 0) == 1,
                "exact_rank": candidate.get("exact_rank"),
                "hybrid_rank": candidate.get("hybrid_rank"),
                "hybrid_score": candidate.get("hybrid_score"),
                "final_score": candidate.get("final_score"),
                "known_error_id": candidate.get("known_error_id"),
                "article_version_id": candidate.get("article_version_id"),
            }
        rows.append(row)
    return pd.DataFrame(rows)


@st.fragment(run_every=3)
def render_incident_review():
    st.subheader("Incident Review")
    source = st.radio("Input source", ["JSON", "Jira API"], horizontal=True)
    payload = {"source": "json" if source == "JSON" else "jira"}
    uploaded = None
    if source == "JSON":
        uploaded = st.file_uploader("Upload tickets JSON (optional; defaults to server dataset)", type=["json"])
    else:
        jql = st.text_area("JQL query", placeholder="Leave blank to use the server query")
        if jql.strip():
            payload["jql"] = jql.strip()
        st.caption("Uses Jira Cloud credentials configured on the server.")
    play, pause, resume = st.columns([1, 1, 4])
    if play.button("Play", type="primary"):
        valid = True
        if uploaded is not None:
            try:
                payload["tickets"] = json.loads(uploaded.getvalue().decode("utf-8-sig"))
                if not isinstance(payload["tickets"], list):
                    raise ValueError("JSON must contain an array of ticket objects")
            except (ValueError, UnicodeError) as exc:
                st.error(f"Invalid JSON: {exc}")
                valid = False
        started = api("POST", "/api/batches/play", json=payload) if valid else None
        if started:
            st.session_state["batch_id"] = started["batch_id"]
    batch_id = st.session_state.get("batch_id")
    batch = api("GET", f"/api/batches/{batch_id}" if batch_id else "/api/batches/current")
    if batch:
        st.session_state["batch_id"] = batch["batch_id"]
    if pause.button("Pause", disabled=not batch or batch["status"] != "RUNNING"):
        if api("POST", f"/api/batches/{batch['batch_id']}/pause"):
            st.rerun()
    if resume.button("Resume current batch", disabled=not batch or batch["status"] not in {"PAUSED", "ERROR"}):
        if api("POST", f"/api/batches/{batch['batch_id']}/resume"):
            st.rerun()
    if not batch:
        st.info("Press Play to process the selected input in the background. Tickets needing review will appear here.")
        return
    st.caption(f"Source: `{batch['source']}`")
    st.progress(batch["processed"] / max(batch["total"], 1),
                text=f"Prepared {batch['processed']} of {batch['total']} tickets")
    waiting = batch["waiting"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Ready for review", len(waiting))
    c2.metric("Finished", batch["processed"] - len(waiting))
    c3.metric("Background processing", batch["status"])
    seen = st.session_state.setdefault("seen_workflows", set())
    new_ids = {item["workflow_id"] for item in waiting} - seen
    if new_ids:
        st.toast(f"{len(new_ids)} new ticket(s) ready for review")
        st.session_state["seen_workflows"] = seen | new_ids
    if batch.get("error"):
        st.error(f"Background processing stopped: {batch['error']}. Press Resume current batch to retry this ticket.")
    elif batch["status"] == "PAUSED":
        st.info("Background processing paused. The current ticket may still finish; reviews remain available.")
    elif batch["status"] == "COMPLETE":
        st.success("All tickets processed. Review the remaining proposals below." if waiting
                   else "All tickets processed and reviewed.")
    else:
        st.caption("Processing continues while you review, even if you close this browser tab.")
    state = None
    if waiting:
        options = {item["workflow_id"]: f"{item['external_key']} ? {item['summary']}" for item in waiting}
        selected = st.selectbox("Ready for review", list(options),
                                format_func=options.get, key="selected_workflow")
        state = api("GET", f"/api/workflows/{selected}")
        if state and state.get("status") != "WAITING_FOR_REVIEW":
            state = None
    elif batch["status"] == "RUNNING":
        st.info("No tickets need review yet. This view refreshes automatically.")
    if state:
        issue, proposal = state["issue"], state["proposal"]
        left, right = st.columns(2)
        with left:
            st.subheader(issue["external_key"])
            st.write(issue["summary"])
            st.markdown("**Description**")
            st.write(issue["description"])
            st.markdown("**Resolution**")
            st.write(issue["resolution"])
        with right:
            st.subheader("AI proposal")
            st.markdown(f"**Action: {proposal['action']}**")
            if proposal.get("target_known_error_id"):
                st.caption(f"Target Known Error: {proposal['target_known_error_id']}")
            for label, key in (("Title", "title"), ("Problem", "problem"), ("Solution", "solution")):
                st.markdown(f"**{label}**")
                st.write(proposal[key])
            st.caption(state["evaluation"].get("reasoning", ""))
        if state.get("candidates"):
            with st.expander("Search scores"):
                if any("exact_rank" in c or "hybrid_rank" in c for c in state["candidates"]):
                    st.caption("Exact match triggers automatic rejection. Final score combines exact and hybrid ranks using RRF (k=60); a missing channel contributes zero.")
                    columns = {
                        "exact_match": st.column_config.CheckboxColumn("Exact match"),
                        "exact_rank": st.column_config.NumberColumn("Exact rank", format="%d"),
                        "hybrid_rank": st.column_config.NumberColumn("Hybrid rank", format="%d"),
                        "hybrid_score": st.column_config.NumberColumn("Hybrid score", format="%.3f"),
                        "final_score": st.column_config.NumberColumn("Final RRF score", format="%.3f"),
                    }
                else:
                    st.caption("Saved results from the previous scoring method.")
                    columns = {}
                st.dataframe(candidate_frame(state["candidates"], review=True),
                             column_config=columns, hide_index=True)
        with st.form(f"review-{state['workflow_id']}-{state.get('revision_count', 0)}"):
            decision = st.selectbox("Review decision", ["APPROVE", "MODIFY", "REJECT"])
            reviewer = st.text_input("Reviewer", DEFAULT_REVIEWER)
            feedback = st.text_area("Feedback for AI modification / review notes")
            st.caption("Modify asks the AI to revise and returns here. Reject publishes nothing.")
            submitted = st.form_submit_button("Submit decision", type="primary")
        if submitted:
            if decision == "MODIFY" and not feedback.strip():
                st.error("Provide feedback so the AI knows what to modify.")
            else:
                updated = api("POST", f"/api/workflows/{state['workflow_id']}/review", json={
                    "decision": decision, "reviewer": reviewer, "feedback": feedback or None})
                if updated:
                    if updated["status"] != "WAITING_FOR_REVIEW":
                        st.session_state.pop("selected_workflow", None)
                    st.rerun()
    if batch["results"]:
        with st.expander("Batch results"):
            report = pd.DataFrame(batch["results"])
            st.dataframe(report, hide_index=True)
            st.download_button("Download results CSV", report.to_csv(index=False).encode(),
                               "kedb_review_results.csv", "text/csv")


def render_resolve_ticket() -> None:
    st.subheader("Resolve Ticket")
    st.caption(
        "Describe an incident and generate an answer grounded in approved KEDB knowledge."
    )

    if st.button("➕ New Chat", key="new_resolve_chat"):
        st.session_state.resolve_messages = []
        st.session_state.pop("resolve_candidates", None)
        st.rerun()

    if "resolve_messages" not in st.session_state:
        st.session_state.resolve_messages = []

    for message in st.session_state.resolve_messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    user_message = st.chat_input(
        "Describe the incident or ask a follow-up question..."
    )

    if user_message:
        st.session_state.resolve_messages.append({
            "role": "user",
            "content": user_message,
        })

        # Search KEDB using ONLY the latest user message.
        result = api(
            "POST",
            "/api/tickets/resolve",
            json={
                "summary": user_message,
                "description": "",
            },
        )

        candidates = (result or {}).get("candidates", [])
        st.session_state["resolve_candidates"] = candidates

        
        # Always call the LLM, even when retrieval returns no articles.
        answer = api(
            "POST",
            "/api/tickets/grounded-answer",
            json={
                "question": user_message,
                "evidence": candidates,
                "history": st.session_state.resolve_messages[:-1],
            },
        )

        if answer:
            st.session_state.resolve_messages.append({
                "role": "assistant",
                "content": answer["answer"],
            })
        else:
            st.session_state.resolve_messages.append({
                "role": "assistant",
                "content": "Sorry, I couldn't generate a response right now.",
            })

        st.rerun()

def render_search_kedb() -> None:
    st.subheader("Search KEDB")
    st.caption(
        "Search published knowledge using error codes, natural-language "
        "descriptions, or both."
    )

    identifier = st.text_input(
        "Error code / technical identifier",
        placeholder="e.g. ORA-12170 or HTTP 403",
    )

    description = st.text_area(
        "Describe your issue",
        placeholder="e.g. My Oracle database connection keeps timing out.",
    )

    if st.button("Search KEDB", type="primary"):
        if not identifier.strip() and not description.strip():
            st.warning("Enter an error code or describe your issue.")
        else:
            result = api(
                "POST",
                "/api/kedb/search",
                json={
                    "summary": identifier,
                    "description": description,
                },
            )

            st.session_state["hybrid_search_candidates"] = (
                (result or {}).get("candidates", [])
            )

    candidates = st.session_state.get("hybrid_search_candidates")

    if candidates is not None:
        if candidates:
            st.success("Relevant KEDB knowledge found.")

            st.dataframe(
                candidate_frame(candidates),
                column_config={
                    "final_score": st.column_config.NumberColumn(
                        "Combined search score",
                        format="%.3f",
                    )
                },
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.warning("No relevant KEDB knowledge was found.")

def render_graph() -> None:
    st.subheader("LangGraph Workflow")
    st.caption(
        "This diagram is generated from the same node/edge definitions used by build_langgraph(). "
        "Purple = AI reasoning, blue = retrieval, amber = human review, green = publication."
    )

    try:
        st.graphviz_chart(workflow_dot(), use_container_width=True)
    except Exception as exc:
        st.warning(f"Graphviz rendering unavailable: {exc}")
        st.code(workflow_dot(), language="dot")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Nodes", len(GRAPH_NODES))
    c2.metric("Edges", len(GRAPH_EDGES))
    c3.metric("AI nodes", sum(1 for _id, _label, kind in GRAPH_NODES if kind == "ai"))
    c4.metric(
        "Human gates", sum(1 for _id, _label, kind in GRAPH_NODES if kind == "human")
    )

    with st.expander("Node inventory", expanded=False):
        st.dataframe(
            pd.DataFrame(
                [
                    {"node": node_id, "label": label, "kind": kind}
                    for node_id, label, kind in GRAPH_NODES
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("How the graph behaves", expanded=True):
        st.markdown(
            """
            1. Jira fields are normalized and an LLM creates a structured retrieval plan.
            2. Exact and hybrid searches run in parallel. Their rankings are combined using RRF (k=60).
            3. An exact score of 1 automatically rejects. No matches automatically creates. Otherwise AI evaluation chooses reuse or a proposal for review.
            4. Human review is a real LangGraph `interrupt()` node.
            5. `MODIFY` requests AI revision and returns to human review.
            6. `REJECT` ends the ticket without publishing.
            7. Human approval or the no-match policy permits publication. The outbox schedules index materialization.
            """
        )

    with st.expander("Local LangGraph Studio", expanded=False):
        st.code(
            "$env:PYTHONPATH=\"src\"\n"
            "pip install -U \"langgraph-cli[inmem]\"\n"
            "langgraph dev",
            language="powershell",
        )
        st.write(
            "The repository includes `langgraph.json` and "
            "`src/kedb/application/workflows/studio.py` for the local Studio entrypoint."
        )


def render_status() -> None:
    st.subheader("Deployment Status")
    status = api("GET", "/api/system/status")
    if status:
        c1, c2, c3 = st.columns(3)
        c1.metric("API", status.get("status", "unknown"))
        c2.metric("Database", status.get("database", "unknown"))
        c3.metric(
            "AI Search",
            "Configured" if status.get("ai_search_configured") else "Fallback",
        )
        chunks = status.get("article_chunks", {})
        if chunks.get("configuration_required"):
            st.warning(chunks["configuration_required"])
        if chunks.get("last_error"):
            st.error(f"Article chunk materialization: {chunks['last_error']}")
        if chunks:
            st.metric("Publications waiting for chunks / sync", chunks.get("pending_publications") or 0)
        st.caption("Rebuild search data from current published articles. Processing runs in the background; search becomes available after index sync completes.")
        if st.button("Rebuild search index", disabled=not (
            status.get("database_ready") and chunks.get("worker_running") and chunks.get("index")
        )):
            result = api("POST", "/api/system/rebuild-search-index")
            if result:
                st.success(f"Queued {result['articles_queued']} published article(s) for rebuilding. Refresh status to check progress.")
        if st.button("Refresh status"):
            st.rerun()
        st.json(status)


with st.sidebar:
    menu = st.radio("Main menu", ["KEDB", "Status", "Workflow Graph"])
    st.markdown("**About KEDB**")
    st.markdown('Welcome to the Known Error Database curator!.  \nThe application collects knowledge from resolved incidents. Each article describes a known problem.  \n-Root causes explain why it happened.  \n-Solutions capture how it was resolved.  \n-Search helps find relevant past issues.  \n-Keyword matching finds shared terms.  \n-Semantic search finds similar meanings.  \nThe curator prepares knowledge proposals.  \nReviewers can approve, modify, or reject them.  \nApproved articles become reusable knowledge.  \nNew versions preserve article history.  \nResolve Ticket answers from saved knowledge.  \nManage Tickets starts incident processing.  \nReuse proven solutions to resolve issues faster.')

if menu == "Status":
    render_status()
elif menu == "Workflow Graph":
    render_graph()
else:
    review_tab, resolve_tab, search_tab, tickets_tab = st.tabs(
        ["Incident Review", "Resolve Ticket", "Search KEDB", "Manage Tickets"]
    )
    with review_tab:
        render_incident_review()
    with resolve_tab:
        render_resolve_ticket()
    with search_tab:
        render_search_kedb()

    with tickets_tab:
        st.subheader("Manage Tickets")
        with st.form("insert_ticket"):
            summary = st.text_input("Summary")
            description = st.text_area("Description")
            resolution = st.text_area("Resolution")
            if st.form_submit_button("Insert ticket"):
                if not summary.strip():
                    st.error("Summary is required.")
                else:
                    started = api("POST", "/api/jira/issues/curate", json=dict(
                        summary=summary.strip(),
                        description=description, resolution=resolution,
                    ))
                    if started:
                        st.session_state["batch_id"] = started["batch_id"]
                        st.success("Ticket saved and queued for processing. Follow progress and review proposals in Incident Review.")
        st.subheader("Insert tickets from Excel")
        from kedb.application.excel_tickets import ticket_template, read_ticket_workbook
        st.caption("Upload resolved tickets with their actual fixes. Follow batch progress and review proposals in Incident Review. IDs are generated automatically. Identical ticket content reuses its saved workflow.")
        st.download_button("Download Excel template", ticket_template(),
                           "kedb_ticket_template.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        workbook = st.file_uploader("Tickets workbook", type=["xlsx"], key="ticket_excel")
        if workbook is not None:
            try:
                uploaded_tickets = read_ticket_workbook(workbook.getvalue())
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.dataframe(pd.DataFrame(uploaded_tickets).drop(columns=["status", "ticket_id"]), hide_index=True)
                if st.button(f"Process {len(uploaded_tickets)} tickets", type="primary"):
                    started = api("POST", "/api/batches/play", json={"source": "json", "tickets": uploaded_tickets})
                    if started:
                        st.session_state["batch_id"] = started["batch_id"]
                        st.success("Batch queued. Open Incident Review to follow progress and approve proposals.")

        tickets = api("GET", "/api/jira/issues") or []
        if tickets:
            selected = st.selectbox("Ticket to delete", tickets,
                                    format_func=lambda t: f"{t['external_key']}: {t['summary']}")
            confirm = st.checkbox("Delete this ticket from the curator database")
            st.caption("This does not delete the original Jira issue. Tickets linked to published knowledge are retained.")
            if st.button("Delete ticket", disabled=not confirm):
                if api("DELETE", f"/api/jira/issues/{selected['id']}"):
                    st.rerun()
