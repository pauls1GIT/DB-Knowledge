from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st

from kedb.application.workflows.curator import GRAPH_EDGES, GRAPH_NODES, workflow_dot

API = os.getenv("KEDB_API_URL", "http://127.0.0.1:8001").rstrip("/")
DEFAULT_REVIEWER = os.getenv("KEDB_DEFAULT_REVIEWER", "human-reviewer")

st.set_page_config(page_title="Known Error Curator", page_icon="▶", layout="wide")
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


@st.fragment(run_every=3)
def render_csv_review():
    st.subheader("CSV Incident Review")
    play, pause = st.columns([1, 5])
    if play.button("Play", type="primary"):
        started = api("POST", "/api/batches/play")
        if started:
            st.session_state["batch_id"] = started["batch_id"]
    batch_id = st.session_state.get("batch_id")
    batch = api("GET", f"/api/batches/{batch_id}" if batch_id else "/api/batches/current")
    if batch:
        st.session_state["batch_id"] = batch["batch_id"]
    if pause.button("Pause", disabled=not batch or batch["status"] != "RUNNING"):
        if api("POST", f"/api/batches/{batch['batch_id']}/pause"):
            st.rerun()
    if not batch:
        st.info("Press Play to process the CSV in the background. Tickets needing review will appear here.")
        return
    st.caption(f"CSV: `{batch['source']}`")
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
        st.error(f"Background processing stopped: {batch['error']}. Press Play to retry this ticket.")
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
                st.dataframe(pd.DataFrame(state["candidates"]), hide_index=True)
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

    summary = st.text_input(
        "Ticket summary",
        placeholder="e.g. Oracle application connection times out",
    )

    description = st.text_area(
        "Ticket description",
        placeholder="Describe the problem, symptoms, error messages, etc.",
    )

    if st.button("Generate grounded answer", type="primary"):
        if not summary.strip() and not description.strip():
            st.warning("Enter a ticket summary or description.")
        else:
            result = api(
                "POST",
                "/api/tickets/resolve",
                json={
                    "summary": summary,
                    "description": description,
                },
             )
        if result:
            candidates = result.get("candidates", [])

            if candidates:
                 st.success("Relevant KEDB knowledge found.")
                 st.dataframe(
                    pd.DataFrame(candidates),
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
            2. Exact, full-text and vector searches fan out in parallel, then merge and rerank.
            3. Any search score > 0.8 rejects; final score < 0.2 automatically creates. Otherwise the AI chooses CREATE or UPDATE.
            4. Human review is a real LangGraph `interrupt()` node.
            5. `MODIFY` requests AI revision and returns to human review.
            6. `REJECT` ends the ticket without publishing.
            7. Human approval or the low-score policy permits publication. The outbox schedules index materialization.
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
        st.json(status)


with st.sidebar:
    st.caption(f"Backend: {API}")
    st.markdown("**App views**")
    st.write("Use the tabs at the top for CSV review, the LangGraph workflow, and deployment status.")

review_tab, resolve_tab, graph_tab, status_tab = st.tabs(
    ["CSV Incident Review", "Resolve Ticket", "Workflow Graph", "Status"]
)

with review_tab:
    render_csv_review()

with resolve_tab:
    render_resolve_ticket()

with graph_tab:
    render_graph()

with status_tab:
    render_status()
