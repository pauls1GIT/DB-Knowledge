import streamlit as st
import httpx
from kedb.config import settings

API=settings.api_base_url
st.set_page_config(page_title="KEDB Curator MVP",layout="wide")
st.title("Known Error DB Curator")
curate_tab,search_tab,resolve_tab=st.tabs(["CSV Curation Queue","Search KEDB","Resolve Ticket"])


def get(path):
    r=httpx.get(API+path,timeout=240); r.raise_for_status(); return r.json()


def post(path,payload=None,files=None,params=None):
    r=httpx.post(API+path,json=payload if files is None else None,files=files,params=params,timeout=240)
    r.raise_for_status(); return r.json()


def load_next(batch_id):
    data=get(f"/api/imports/{batch_id}/next")
    st.session_state.current_item=data.get("item")
    st.session_state.current_workflow=None
    if data.get("item") and data["item"].get("workflow_id"):
        snap=get(f"/api/workflows/{data['item']['workflow_id']}")
        st.session_state.current_workflow={
            "workflow_id":data["item"]["workflow_id"],
            "status":"AWAITING_REVIEW",
            "proposal":snap.get("values",{}).get("proposal"),
            "evaluation":snap.get("values",{}).get("evaluation"),
            "candidates":snap.get("values",{}).get("candidates",[]),
        }
    return data


with curate_tab:
    st.subheader("1. Import Jira CSV")
    uploaded=st.file_uploader("Jira CSV export",type=["csv"])
    include_unresolved=st.checkbox("Include unresolved issues in the review queue",value=True,
        help="Useful for reviewing every CSV row. Turn off to curate only rows that have Resolution/Resolved populated.")
    if st.button("Import CSV",type="primary",disabled=uploaded is None):
        out=post("/api/imports/jira-csv",files={"file":(uploaded.name,uploaded.getvalue(),"text/csv")},params={"include_unresolved":str(include_unresolved).lower()})
        st.session_state.batch_id=out["id"]
        st.session_state.current_item=None
        st.session_state.current_workflow=None
        st.success(f"Imported {out['valid_rows']} rows from {out['filename']}")

    batch_id=st.session_state.get("batch_id")
    if batch_id:
        summary=get(f"/api/imports/{batch_id}")
        c1,c2,c3,c4=st.columns(4)
        c1.metric("CSV rows",summary["total_rows"])
        c2.metric("Queued",summary["valid_rows"])
        c3.metric("Skipped",summary["skipped_rows"])
        c4.metric("Failed",summary["invalid_rows"])
        st.caption(f"Batch {batch_id} · states: {summary.get('item_counts',{})}")

        if st.session_state.get("current_item") is None:
            load_next(batch_id)

        item=st.session_state.get("current_item")
        if not item:
            st.success("No incidents remain in this review queue.")
        else:
            issue=item.get("issue") or {}
            st.divider()
            st.subheader(f"2. Review incident — CSV row {item['row_number']}")
            top1,top2,top3,top4=st.columns(4)
            top1.text_input("Issue key",issue.get("external_key") or "",disabled=True)
            top2.text_input("Status",issue.get("status") or "",disabled=True)
            top3.text_input("Priority",issue.get("priority") or "",disabled=True)
            top4.text_input("Issue type",issue.get("issue_type") or "",disabled=True)
            st.text_input("Summary",issue.get("summary") or "",disabled=True)
            left,right=st.columns(2)
            with left: st.text_area("Description",issue.get("description") or "",height=150,disabled=True)
            with right: st.text_area("Resolution",issue.get("resolution") or "",height=150,disabled=True)
            if not issue.get("resolution") and not issue.get("resolved_at"):
                st.warning("This Jira row is unresolved. You chose to include unresolved issues, so the curator may have weak evidence for a reusable solution.")

            wf=st.session_state.get("current_workflow")
            if not wf:
                if st.button("Analyze this incident",type="primary"):
                    wf=post(f"/api/imports/{batch_id}/items/{item['id']}/process",{})
                    st.session_state.current_workflow=wf
                    st.rerun()
            else:
                st.divider(); st.subheader("3. AI recommendation + human review")
                ev=wf.get("evaluation") or {}
                e1,e2,e3=st.columns(3)
                e1.metric("Recommendation",ev.get("recommendation","—"))
                conf=ev.get("confidence")
                e2.metric("Confidence",f"{conf:.2f}" if isinstance(conf,(int,float)) else "—")
                e3.metric("Revision",wf.get("revision_count",0))
                if ev.get("reasoning"): st.info(ev["reasoning"])
                if wf.get("candidates"):
                    with st.expander("Retrieved KEDB candidates"):
                        st.dataframe(wf["candidates"],use_container_width=True)

                proposal=wf.get("proposal") or {}
                with st.form("review_form",clear_on_submit=False):
                    title=st.text_input("Proposed title",proposal.get("title",issue.get("summary", "")))
                    problem=st.text_area("Problem",proposal.get("problem",issue.get("description", "")),height=110)
                    root_cause=st.text_area("Root cause",proposal.get("root_cause", ""),height=110)
                    solution=st.text_area("Solution",proposal.get("solution",issue.get("resolution", "")),height=130)
                    decision=st.radio("Decision",["APPROVE","MODIFY","REJECT"],horizontal=True,help="APPROVE publishes; MODIFY requests another revision; REJECT closes without publishing.")
                    feedback=st.text_area("Reviewer feedback",help="For MODIFY, explain what should be revised. For REJECT, record why the incident should not be published.")
                    submitted=st.form_submit_button("Submit review",type="primary")
                if submitted:
                    modified=None
                    if decision=="MODIFY":
                        modified={"title":title,"problem":problem,"root_cause":root_cause,"solution":solution}
                    result=post(f"/api/reviews/{wf['workflow_id']}",{
                        "decision":decision,"reviewer":"streamlit-reviewer","feedback":feedback or None,"modified_content":modified
                    })
                    if result["status"]=="AWAITING_REVIEW":
                        st.session_state.current_workflow={**wf,**result}
                        st.warning("Proposal revised. Review the same incident again before it can be published.")
                        st.rerun()
                    else:
                        if decision=="APPROVE":
                            st.success("Incident approved and published. Moving to the next CSV row.")
                        else:
                            st.warning("Incident rejected and not published. Moving to the next CSV row.")
                        st.session_state.current_item=None
                        st.session_state.current_workflow=None
                        load_next(batch_id)
                        st.rerun()

                if st.button("SKIP INCIDENT"):
                    post(f"/api/imports/{batch_id}/items/{item['id']}/skip",{})
                    st.session_state.current_item=None
                    st.session_state.current_workflow=None
                    load_next(batch_id)
                    st.rerun()

with search_tab:
    q=st.text_input("Search approved KEDB","Oracle connection timeout")
    ec=st.text_input("Exact identifier/error code","")
    if st.button("Search"):
        st.dataframe(post("/api/retrieval/search",{"query":q,"error_code":ec or None}),use_container_width=True)

with resolve_tab:
    s=st.text_input("Ticket summary","Oracle application connection times out",key="resolve_summary")
    d=st.text_area("Ticket description","Users report ORA-12170 while connecting.",key="resolve_desc")
    if st.button("Generate grounded answer"):
        st.json(post("/api/tickets/resolve",{"external_key":"CHAT-1","summary":s,"description":d,"resolution":"","error_code":None}))
