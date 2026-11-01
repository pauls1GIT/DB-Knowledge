from __future__ import annotations

import logging
import math
from typing import Any, TypedDict
from uuid import uuid4

from kedb.application.dto import KnowledgeProposal, RetrievalPlan
from kedb.observability import execution, traced_step

logger = logging.getLogger(__name__)


class CuratorState(TypedDict, total=False):
    workflow_id: str
    issue: dict
    jira_fields: dict
    retrieval_plan: dict
    exact_candidates: list[dict]
    hybrid_candidates: list[dict]
    candidates: list[dict]
    evaluation: dict
    proposal: dict
    review: dict
    revision_count: int
    publication_result: dict
    chunks: list[dict]
    embedding_result: dict
    index_result: dict
    status: str
    automatic_create: bool


# Single source of truth used by both build_langgraph() and the Streamlit graph tab.
GRAPH_NODES: list[tuple[str, str, str]] = [
    ("retrieve_jira_fields", "Retrieve Jira Fields", "process"),
    ("extract_structured_error_information", "Extract Structured Error Information", "ai"),
    ("exact_search", "Exact Search", "retrieval"),
    ("hybrid_search", "Hybrid Search", "retrieval"),
    ("combine_candidates", "Combine Candidates", "process"),
    ("score_candidates", "Cosine Similarity", "process"),
    ("suitable_known_error_found", "Cosine Decision Band?", "decision"),
    ("generate_new_known_error_candidate", "Generate New Known Error Candidate", "ai"),
    ("human_review", "Human Review", "human"),
    ("return_for_ai_revision", "Return for AI Revision", "ai"),
    ("reject", "Reject (No Publication)", "process"),
    ("automatic_approve", "Automatically Approve Nonduplicate", "process"),
    ("approve", "Approve", "human"),
    ("publish_approved_knowledge", "Publish Approved Knowledge", "publish"),
    ("create_update_article_version", "Create / Update Article Version", "publish"),
    ("chunk_content", "Chunk Content", "process"),
    ("generate_embeddings", "Generate Embeddings", "process"),
    ("update_retrieval_index", "Update Retrieval Index", "process"),
    ("available_for_future_jira", "Available for Future Jira", "publish"),
]

# (source, destination, edge label)
GRAPH_EDGES: list[tuple[str, str, str | None]] = [
    ("__start__", "retrieve_jira_fields", None),
    ("retrieve_jira_fields", "extract_structured_error_information", None),
    ("extract_structured_error_information", "exact_search", None),
    ("extract_structured_error_information", "hybrid_search", None),
    ("exact_search", "combine_candidates", None),
    ("hybrid_search", "combine_candidates", None),
    ("combine_candidates", "generate_new_known_error_candidate", None),
    ("generate_new_known_error_candidate", "score_candidates", None),
    ("score_candidates", "suitable_known_error_found", None),
    ("suitable_known_error_found", "automatic_approve", "Below approval cutoff / no articles"),
    ("suitable_known_error_found", "human_review", "Between cutoffs"),
    ("human_review", "return_for_ai_revision", "Modify"),
    ("human_review", "reject", "Reject"),
    ("human_review", "approve", "Approve"),
    ("return_for_ai_revision", "human_review", None),
    ("reject", "__end__", None),
    ("suitable_known_error_found", "reject", "At or above rejection cutoff"),
    ("automatic_approve", "publish_approved_knowledge", None),
    ("approve", "publish_approved_knowledge", None),
    ("publish_approved_knowledge", "create_update_article_version", None),
    ("create_update_article_version", "chunk_content", None),
    ("chunk_content", "generate_embeddings", None),
    ("generate_embeddings", "update_retrieval_index", None),
    ("update_retrieval_index", "available_for_future_jira", None),
    ("available_for_future_jira", "__end__", None),
]


def workflow_dot() -> str:
    """Return a Graphviz DOT representation of the same workflow topology."""
    labels = {node_id: label for node_id, label, _kind in GRAPH_NODES}
    kinds = {node_id: kind for node_id, _label, kind in GRAPH_NODES}
    lines = [
        "digraph CuratorWorkflow {",
        '  graph [rankdir=TB, bgcolor="transparent", pad="0.2", nodesep="0.35", ranksep="0.45"];',
        '  node [shape=box, style="rounded,filled", fontname="Arial", fontsize=10, color="#6b7280", fillcolor="#111827", fontcolor="white", margin="0.12,0.08"];',
        '  edge [fontname="Arial", fontsize=9, color="#9ca3af", fontcolor="#d1d5db"];',
        '  "__start__" [label="New Jira Issue", shape=box, fillcolor="#1f2937"];',
        '  "__end__" [label="Complete", shape=box, fillcolor="#064e3b"];',
    ]
    shape_by_kind = {
        "decision": "diamond",
        "human": "box",
        "ai": "box",
        "retrieval": "box",
        "publish": "box",
        "process": "box",
    }
    fill_by_kind = {
        "decision": "#312e81",
        "human": "#78350f",
        "ai": "#581c87",
        "retrieval": "#1e3a8a",
        "publish": "#064e3b",
        "process": "#111827",
    }
    for node_id, label in labels.items():
        kind = kinds[node_id]
        lines.append(
            f'  "{node_id}" [label="{label}", shape={shape_by_kind[kind]}, fillcolor="{fill_by_kind[kind]}"];'
        )
    for source, target, label in GRAPH_EDGES:
        attrs = f' [label="{label}"]' if label else ""
        lines.append(f'  "{source}" -> "{target}"{attrs};')
    lines.append("}")
    return "\n".join(lines)


class CuratorWorkflow:
    """Multi-node curator workflow used by LangGraph and LangGraph Studio.

    LLM reasoning is limited to retrieval planning and proposal
    drafting/revision. Duplicate decisions use deterministic cosine thresholds.
    Publication and indexing retain their existing approval and outbox boundaries.
    """

    def __init__(self, llm, retrieval, publisher=None, chunker=None, embedder=None, indexer=None,
                 duplicate_scorer=None, duplicate_threshold=0.90, auto_approve_threshold=0.60,
                 progress=None):
        self.llm = llm
        self.retrieval = retrieval
        self.publisher = publisher
        self.chunker = chunker
        self.embedder = embedder
        self.indexer = indexer
        self.progress = progress
        if not math.isfinite(duplicate_threshold) or not -1 <= duplicate_threshold <= 1:
            raise ValueError("Duplicate threshold must be between -1 and 1")
        self.duplicate_scorer = duplicate_scorer
        self.duplicate_threshold = duplicate_threshold
        if (not math.isfinite(auto_approve_threshold)
                or not -1 <= auto_approve_threshold < duplicate_threshold):
            raise ValueError("Auto-approve threshold must be below duplicate rejection threshold")
        self.auto_approve_threshold = auto_approve_threshold

    def tracked_node(self, name, node):
        def tracked(state):
            from langgraph.errors import GraphInterrupt

            def report(event):
                if self.progress:
                    try:
                        self.progress(state.get("workflow_id"), name, event)
                    except Exception:
                        logger.warning("Live workflow progress update failed", exc_info=True)
            report("started")
            try:
                result = node(state)
            except GraphInterrupt:
                report("completed")
                raise
            except Exception:
                report("failed")
                raise
            report("completed")
            return result
        return tracked

    @staticmethod
    def _candidate_to_dict(candidate: Any) -> dict:
        if isinstance(candidate, dict):
            data = dict(candidate)
        else:
            data = dict(candidate.__dict__)
        for key in ("known_error_id", "article_version_id", "article_chunk_id"):
            if data.get(key) is not None:
                data[key] = str(data[key])
        return data

    # ------------------------------------------------------------------
    # API entry points execute compiled graphs. Persisted application state
    # separates review from publication so database transaction ownership stays explicit.
    # ------------------------------------------------------------------
    def start(self, issue: dict, *, workflow_id: str | None = None) -> CuratorState:
        workflow_id = workflow_id or str(uuid4())
        with execution("known-error-curator", workflow_id):
            return self._start(issue, workflow_id=workflow_id)

    def _start(self, issue: dict, *, workflow_id: str | None = None) -> CuratorState:
        state: CuratorState = {"issue": issue, "workflow_id": workflow_id or str(uuid4())}
        return build_langgraph(self, phase="start").invoke(
            state, config={"configurable": {"thread_id": state["workflow_id"]}}
        )

    def publish(self, state: CuratorState) -> CuratorState:
        with execution("known-error-curator", state.get("workflow_id")):
            return self._publish(state)

    def _publish(self, state: CuratorState) -> CuratorState:
        return build_langgraph(self, phase="publish").invoke(
            state, config={"configurable": {"thread_id": state.get("workflow_id")}}
        )

    def apply_review(self, state: CuratorState, review: dict) -> CuratorState:
        with execution("known-error-curator", state.get("workflow_id")):
            return self._apply_review(state, review)

    def _apply_review(self, state: CuratorState, review: dict) -> CuratorState:
        if state.get("status") != "WAITING_FOR_REVIEW":
            raise ValueError("This workflow is not waiting for review")
        updated = dict(state)
        updated["review"] = review
        route_review(updated)  # Validate before running graph nodes.
        return build_langgraph(self, phase="review").invoke(
            updated, config={"configurable": {"thread_id": state.get("workflow_id")}}
        )

    # ------------------------------------------------------------------
    # LangGraph nodes
    # ------------------------------------------------------------------
    def retrieve_jira_fields(self, state: CuratorState) -> dict:
        issue = state["issue"]
        return {
            "workflow_id": state.get("workflow_id", str(uuid4())),
            "jira_fields": {
                "external_key": issue.get("external_key"),
                "summary": issue.get("summary"),
                "description": issue.get("description"),
                "resolution": issue.get("resolution"),
                "error_code": issue.get("error_code"),
            },
            "revision_count": state.get("revision_count", 0),
            "status": "PROCESSING",
        }

    def extract_structured_error_information(self, state: CuratorState) -> dict:
        plan = self.llm.structured(
            system=(
                "Extract a structured KEDB retrieval plan from the Jira incident. "
                "Return semantic_query, keywords, exact_identifiers and error_codes."
            ),
            user=str(state["jira_fields"]),
            schema=RetrievalPlan,
        )
        return {"retrieval_plan": plan.model_dump(mode="json")}

    def exact_search(self, state: CuratorState) -> dict:
        plan = state["retrieval_plan"]
        query = " ".join(plan.get("exact_identifiers", []) + plan.get("error_codes", []))
        if not query:
            return {"exact_candidates": []}
        results = self.retrieval.exact_search(query, top_k=5)
        return {"exact_candidates": [self._candidate_to_dict(c) for c in results]}

    def hybrid_search(self, state: CuratorState) -> dict:
        query = state["retrieval_plan"].get("semantic_query", "")
        results = self.retrieval.hybrid_search(query, top_k=5)
        return {"hybrid_candidates": [self._candidate_to_dict(c) for c in results]}

    def combine_candidates(self, state: CuratorState) -> dict:
        merged = {}
        for channel in ("exact", "hybrid"):
            seen = set()
            for candidate in state.get(f"{channel}_candidates", []):
                identity = (candidate.get("known_error_id"), candidate.get("article_version_id"))
                if identity in seen:
                    continue
                seen.add(identity)
                current = merged.setdefault(identity, {
                    **candidate, "exact_score": 0.0, "retrieval_methods": [],
                })
                current["retrieval_methods"].append(channel)
                current[f"{channel}_rank"] = len(seen)
                if channel == "exact":
                    current["exact_score"] = float(candidate.get("exact_score", 0))
                else:
                    current["hybrid_score"] = float(candidate.get("final_score", 0))
        return {"candidates": list(merged.values())}

    @traced_step("duplication.score_candidates")
    def score_candidates(self, state: CuratorState) -> dict:
        if self.duplicate_scorer is None:
            raise ValueError("An article cosine scorer is required for duplicate decisions")
        candidates = self.duplicate_scorer.score(state["proposal"], state.get("candidates", []))
        for candidate in candidates:
            score = candidate.get("cosine_score")
            if score is None or not math.isfinite(score) or not -1 <= score <= 1:
                raise ValueError("Missing or invalid cosine score; duplicate decision stopped")
        candidates.sort(key=lambda c: c["cosine_score"], reverse=True)
        for rank, candidate in enumerate(candidates, 1):
            candidate.update(rank=rank, final_score=candidate["cosine_score"])
        return {"candidates": candidates}

    @traced_step("duplication.threshold_decision")
    def suitable_known_error_found(self, state: CuratorState) -> dict:
        candidates = state.get("candidates", [])
        best = candidates[0] if candidates else None
        score = best["cosine_score"] if best else None
        duplicate = best is not None and score >= self.duplicate_threshold
        automatic = best is None or score < self.auto_approve_threshold
        decision = "REJECT" if duplicate else "APPROVE" if automatic else "HUMAN_REVIEW"
        if best is None:
            reason = "No current published articles; approved as nonduplicate"
        elif duplicate:
            reason = f"Cosine {score:.6f} >= rejection cutoff {self.duplicate_threshold:.6f}: duplicate rejected"
        elif automatic:
            reason = f"Cosine {score:.6f} < approval cutoff {self.auto_approve_threshold:.6f}: automatically approved"
        else:
            reason = (f"Cosine {score:.6f} is between approval cutoff {self.auto_approve_threshold:.6f} "
                      f"(inclusive) and rejection cutoff {self.duplicate_threshold:.6f}: human review required")
        evaluation = {
            "recommendation": "USE_EXISTING" if duplicate else "CREATE_NEW",
            "decision": decision,
            "auto_approve_threshold": self.auto_approve_threshold,
            "cosine_score": score,
            "duplicate_threshold": self.duplicate_threshold,
            "selected_known_error_id": best["known_error_id"] if best else None,
            "selected_article_version_id": best["article_version_id"] if best else None,
            "compared_articles": len(candidates),
            "embedding_model": self.duplicate_scorer.embedder.model,
            "embedding_model_version": self.duplicate_scorer.embedder.model_version,
            "reasoning": reason,
        }
        logger.info("Duplicate decision workflow=%s score=%s approve_below=%s reject_at=%s match=%s decision=%s",
                    state.get("workflow_id"), score, self.auto_approve_threshold, self.duplicate_threshold,
                    evaluation["selected_article_version_id"], decision)
        return {"evaluation": evaluation, "automatic_create": automatic,
                "status": "WAITING_FOR_REVIEW" if decision == "HUMAN_REVIEW" else "PROCESSING"}

    def generate_new_known_error_candidate(self, state: CuratorState) -> dict:
        proposal = self.llm.structured(
            system="Generate a new Known Error proposal from the incident. Never publish.",
            user=f"issue={state['issue']}",
            schema=KnowledgeProposal,
        )
        data = proposal.model_dump(mode="json")
        data.update(action="CREATE", target_known_error_id=None)
        return {"proposal": data, "status": "WAITING_FOR_REVIEW"}

    def human_review(self, state: CuratorState) -> dict:
        from langgraph.types import interrupt

        review = interrupt(
            {
                "type": "HUMAN_REVIEW",
                "workflow_id": state["workflow_id"],
                "issue": state["issue"],
                "evaluation": state["evaluation"],
                "proposal": state["proposal"],
                "revision_count": state.get("revision_count", 0),
                "allowed_decisions": ["APPROVE", "MODIFY", "REJECT"],
            }
        )
        return {"review": review}

    def reject(self, _state: CuratorState) -> dict:
        return {"status": "REJECTED"}

    def automatic_approve(self, state: CuratorState) -> dict:
        if not state.get("automatic_create") or state["proposal"]["action"] != "CREATE":
            raise ValueError("Automatic publication requires a low-score CREATE")
        return {"review": {"decision": "APPROVE", "reviewer": "automatic-cosine-duplicate-policy"},
                "status": "APPROVED_FOR_PUBLICATION"}

    def return_for_ai_revision(self, state: CuratorState) -> dict:
        review = state.get("review", {})
        revised = self.llm.structured(
            system="Revise the Known Error proposal using reviewer feedback. Do not publish.",
            user=f"proposal={state['proposal']}\nfeedback={review.get('feedback', '')}",
            schema=KnowledgeProposal,
        )
        data = revised.model_dump(mode="json")
        data["action"] = state["proposal"]["action"]
        data["target_known_error_id"] = state["proposal"].get("target_known_error_id")
        return {
            "proposal": data,
            "revision_count": state.get("revision_count", 0) + 1,
            "status": "WAITING_FOR_REVIEW",
        }

    def approve(self, _state: CuratorState) -> dict:
        return {"status": "APPROVED_FOR_PUBLICATION"}

    def publish_approved_knowledge(self, state: CuratorState) -> dict:
        decision = state.get("review", {}).get("decision")
        if decision != "APPROVE" or state.get("status") != "APPROVED_FOR_PUBLICATION":
            raise ValueError("Publication requires approval")
        return {"status": "PUBLICATION_STARTED"}

    def create_update_article_version(self, state: CuratorState) -> dict:
        if self.publisher is None:
            return {
                "publication_result": {
                    "mode": "DEMO",
                    "action": state["proposal"].get("action"),
                    "target_known_error_id": state["proposal"].get("target_known_error_id"),
                }
            }
        result = self.publisher(state)
        if hasattr(result, "model_dump"):
            result = result.model_dump(mode="json")
        elif not isinstance(result, dict):
            result = dict(result.__dict__)
        return {"publication_result": result}

    def chunk_content(self, state: CuratorState) -> dict:
        if self.chunker is not None:
            return {"chunks": self.chunker(state)}
        proposal = state["proposal"]
        return {
            "chunks": [
                {"section": "problem", "content": proposal.get("problem", "")},
                {"section": "root_cause", "content": proposal.get("root_cause", "")},
                {"section": "solution", "content": proposal.get("solution", "")},
            ]
        }

    def generate_embeddings(self, state: CuratorState) -> dict:
        if self.embedder is None:
            return {
                "embedding_result": {
                    "mode": "DEFERRED" if self.publisher else "DEMO",
                    "chunks_embedded": 0 if self.publisher else len(state.get("chunks", [])),
                }
            }
        vectors = self.embedder.embed_batch([c["content"] for c in state.get("chunks", [])])
        return {"embedding_result": {"count": len(vectors)}}

    def update_retrieval_index(self, state: CuratorState) -> dict:
        if self.indexer is None:
            return {"index_result": {"mode": "OUTBOX" if self.publisher else "DEMO",
                                     "status": "PENDING" if self.publisher else "INDEXED"}}
        return {"index_result": self.indexer(state)}

    def available_for_future_jira(self, _state: CuratorState) -> dict:
        if self.publisher is not None and self.indexer is None:
            return {"status": "PUBLISHED_PENDING_INDEX"}
        return {"status": "AVAILABLE_FOR_FUTURE_JIRA"}


def route_known_error(state: CuratorState) -> str:
    recommendation = state["evaluation"].get("recommendation")
    if recommendation == "USE_EXISTING":
        return "reject"
    if recommendation == "CREATE_NEW":
        return "automatic" if state.get("automatic_create") else "review"
    raise ValueError(f"Unexpected duplicate decision: {recommendation}")


def route_review(state: CuratorState) -> str:
    decision = state["review"].get("decision")
    if decision == "APPROVE":
        return "approve"
    if decision == "MODIFY":
        return "modify"
    if decision == "REJECT":
        return "reject"
    raise ValueError(f"Unknown review decision: {decision}")


def build_langgraph(workflow: CuratorWorkflow, *, checkpointer=None, phase: str = "interactive"):
    """Build the shared topology for Studio or a durable API phase.

    API review pauses are persisted by the caller in Lakebase. Approval returns
    before publication so the caller can acquire its database lock and transaction.
    Studio uses native interrupts and a caller-supplied LangGraph checkpointer.
    """
    from langgraph.graph import END, START, StateGraph

    if phase not in {"interactive", "start", "review", "publish"}:
        raise ValueError(f"Unknown workflow phase: {phase}")
    graph = StateGraph(CuratorState)

    for node_name, _label, _kind in GRAPH_NODES:
        # The API stores pending review in Lakebase; Studio uses native interrupts.
        node = getattr(workflow, node_name)
        if node_name == "human_review" and phase != "interactive":
            node = lambda _state: {}
        graph.add_node(node_name, workflow.tracked_node(node_name, node))

    if phase == "review":
        graph.add_conditional_edges(START, route_review, {
            "approve": "approve", "modify": "return_for_ai_revision", "reject": "reject",
        })
    else:
        entry = "publish_approved_knowledge" if phase == "publish" else "retrieve_jira_fields"
        graph.add_edge(START, entry)
    graph.add_edge("retrieve_jira_fields", "extract_structured_error_information")

    # Fan-out hybrid retrieval.
    graph.add_edge("extract_structured_error_information", "exact_search")
    graph.add_edge("extract_structured_error_information", "hybrid_search")

    # Barrier: combine only after both retrieval branches have completed.
    graph.add_edge(["exact_search", "hybrid_search"], "combine_candidates")
    graph.add_edge("combine_candidates", "generate_new_known_error_candidate")
    graph.add_edge("generate_new_known_error_candidate", "score_candidates")
    graph.add_edge("score_candidates", "suitable_known_error_found")

    graph.add_conditional_edges(
        "suitable_known_error_found",
        route_known_error,
        {"automatic": "automatic_approve", "reject": "reject", "review": "human_review"},
    )
    graph.add_edge("automatic_approve", "publish_approved_knowledge")
    graph.add_edge("reject", END)

    if phase == "interactive":
        graph.add_conditional_edges(
            "human_review", route_review,
            {"approve": "approve", "modify": "return_for_ai_revision", "reject": "reject"},
        )
    else:
        graph.add_edge("human_review", END)
    graph.add_edge("return_for_ai_revision", "human_review")
    graph.add_edge("approve", END if phase == "review" else "publish_approved_knowledge")
    graph.add_edge("publish_approved_knowledge", "create_update_article_version")
    graph.add_edge("create_update_article_version", "chunk_content")
    graph.add_edge("chunk_content", "generate_embeddings")
    graph.add_edge("generate_embeddings", "update_retrieval_index")
    graph.add_edge("update_retrieval_index", "available_for_future_jira")
    graph.add_edge("available_for_future_jira", END)

    return graph.compile(checkpointer=checkpointer)
