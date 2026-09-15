from __future__ import annotations
from pathlib import Path
from typing import TypedDict, Any
from dataclasses import asdict
from uuid import UUID, uuid4
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from kedb.application.dto import EvaluationResult, KnowledgeProposal, CandidateDTO
from kedb.domain.entities import HumanReview, ReviewDecision

PROMPTS=Path(__file__).resolve().parents[4]/"prompts"

def prompt(path): return (PROMPTS/path).read_text(encoding="utf-8")


class CuratorState(TypedDict, total=False):
    workflow_id: str
    issue_id: str
    candidates: list[dict]
    evaluation: dict
    proposal: dict
    reviewer_feedback: str
    revision_count: int
    review: dict
    publication_result: dict


def build_curator_graph(repo, retrieval, llm, publisher, checkpointer):
    def retrieve_node(state):
        issue=repo.get_issue(UUID(state["issue_id"]))
        items=retrieval.search(issue,limit=5)
        return {"candidates":[CandidateDTO.model_validate(asdict(c)).model_dump(mode="json") for c in items]}

    def evaluate_node(state):
        issue=repo.get_issue(UUID(state["issue_id"]))
        user=f"ISSUE:\n{issue.summary}\n{issue.description}\nResolution: {issue.resolution}\nError: {issue.error_code}\n\nCANDIDATES:\n{state.get('candidates',[])}"
        result=llm.structured(prompt(Path("knowledge_evaluator/v1.md")),user,EvaluationResult)
        return {"evaluation":result.model_dump(mode="json")}

    def curate_node(state):
        issue=repo.get_issue(UUID(state["issue_id"]))
        ev=EvaluationResult.model_validate(state["evaluation"])
        action="CREATE" if ev.recommendation=="CREATE_NEW" else "UPDATE"
        target=None if action=="CREATE" else ev.selected_known_error_id
        feedback=state.get("reviewer_feedback")
        sys=prompt(Path("knowledge_curator/revise_v1.md" if feedback else "knowledge_curator/v1.md"))
        user=f"Required action={action}; target={target}.\nISSUE={issue}\nEVALUATION={state['evaluation']}\nEVIDENCE={state.get('candidates',[])}\nCURRENT PROPOSAL={state.get('proposal')}\nREVIEWER FEEDBACK={feedback or 'none'}"
        p=llm.structured(sys,user,KnowledgeProposal)
        if action=="UPDATE" and p.target_known_error_id is None: p.target_known_error_id=target
        return {"proposal":p.model_dump(mode="json"),"revision_count":state.get("revision_count",0)+(1 if feedback else 0),"reviewer_feedback":""}

    def review_node(state):
        answer=interrupt({"workflow_id":state["workflow_id"],"proposal":state["proposal"],"message":"Human approval required before publication."})
        decision=ReviewDecision(answer["decision"])
        review=HumanReview(workflow_id=UUID(state["workflow_id"]),decision=decision,reviewer=answer.get("reviewer","reviewer"),feedback=answer.get("feedback"),modified_content=answer.get("modified_content"))
        repo.save_review(review)
        proposal=state["proposal"]
        # MODIFY means request another AI revision, never publication. Reviewer edits
        # become the starting point for the next curator pass.
        if decision==ReviewDecision.MODIFY and review.modified_content:
            proposal={**proposal,**review.modified_content}
        feedback=review.feedback or ""
        if decision==ReviewDecision.MODIFY and not feedback:
            feedback="Revise the proposal using the reviewer-edited fields as guidance."
        return {"review":{"id":str(review.id),"decision":decision.value,"reviewer":review.reviewer,"feedback":review.feedback,"modified_content":review.modified_content},"proposal":proposal,"reviewer_feedback":feedback}

    def route_review(state):
        decision=state["review"]["decision"]
        if decision==ReviewDecision.APPROVE.value:
            return "publish"
        if decision==ReviewDecision.MODIFY.value:
            return "revise"
        return "reject"

    def reject_node(state):
        # Explicit terminal path: rejected incidents do not create/update KEDB knowledge.
        return {"publication_result":None}

    def publish_node(state):
        r=state["review"]
        review=HumanReview(id=UUID(r["id"]),workflow_id=UUID(state["workflow_id"]),decision=ReviewDecision(r["decision"]),reviewer=r["reviewer"],feedback=r.get("feedback"),modified_content=r.get("modified_content"))
        result=publisher.execute(UUID(state["issue_id"]),KnowledgeProposal.model_validate(state["proposal"]),review,EvaluationResult.model_validate(state["evaluation"]).confidence)
        return {"publication_result":result}

    g=StateGraph(CuratorState)
    g.add_node("retrieve",retrieve_node); g.add_node("evaluate",evaluate_node); g.add_node("curate",curate_node); g.add_node("human_review",review_node); g.add_node("publish",publish_node); g.add_node("reject",reject_node)
    g.add_edge(START,"retrieve"); g.add_edge("retrieve","evaluate"); g.add_edge("evaluate","curate"); g.add_edge("curate","human_review")
    g.add_conditional_edges("human_review",route_review,{"revise":"curate","publish":"publish","reject":"reject"}); g.add_edge("publish",END); g.add_edge("reject",END)
    return g.compile(checkpointer=checkpointer)
