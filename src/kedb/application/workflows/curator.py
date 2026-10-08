from __future__ import annotations

from typing import Any, TypedDict
from uuid import UUID, uuid4

from kedb.application.dto import EvaluationResult, KnowledgeProposal, RetrievalPlan


class CuratorState(TypedDict, total=False):
    workflow_id: str
    issue: dict
    jira_fields: dict
    retrieval_plan: dict
    exact_candidates: list[dict]
    lexical_candidates: list[dict]
    vector_candidates: list[dict]
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
    ("full_text_search", "Full Text Search", "retrieval"),
    ("vector_search", "Vector Search", "retrieval"),
    ("combine_candidates", "Combine Candidates", "process"),
    ("rerank_candidates", "Rerank Candidates", "process"),
    ("suitable_known_error_found", "Suitable Known Error Found?", "decision"),
    ("propose_existing_known_error", "Propose Existing Known Error Revision", "ai"),
    ("generate_new_known_error_candidate", "Generate New Known Error Candidate", "ai"),
    ("human_review", "Human Review", "human"),
    ("return_for_ai_revision", "Return for AI Revision", "ai"),
    ("reject", "Reject (No Publication)", "human"),
    ("automatic_approve", "Automatically Create (Final Score < 0.2)", "process"),
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
    ("extract_structured_error_information", "full_text_search", None),
    ("extract_structured_error_information", "vector_search", None),
    ("full_text_search", "combine_candidates", None),
    ("vector_search", "combine_candidates", None),
    ("combine_candidates", "rerank_candidates", None),
    ("rerank_candidates", "suitable_known_error_found", None),
    ("suitable_known_error_found", "propose_existing_known_error", "Yes"),
    ("suitable_known_error_found", "generate_new_known_error_candidate", "No"),
    ("propose_existing_known_error", "human_review", None),
    ("generate_new_known_error_candidate", "human_review", "Final score >= 0.2"),
    ("human_review", "return_for_ai_revision", "Modify"),
    ("human_review", "reject", "Reject"),
    ("human_review", "approve", "Approve"),
    ("return_for_ai_revision", "human_review", None),
    ("reject", "__end__", None),
    ("suitable_known_error_found", "reject", "Any search > 0.8 / use existing"),
    ("generate_new_known_error_candidate", "automatic_approve", "Final score < 0.2"),
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

    LLM reasoning is limited to retrieval planning, candidate evaluation and proposal
    drafting/revision. Search, merge/ranking, human approval, persistence, chunking,
    embeddings and index updates stay deterministic.
    """

    def __init__(self, llm, retrieval, publisher=None, chunker=None, embedder=None, indexer=None):
        self.llm = llm
        self.retrieval = retrieval
        self.publisher = publisher
        self.chunker = chunker
        self.embedder = embedder
        self.indexer = indexer

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
    # Backwards-compatible facade methods used by existing tests/callers.
    # The actual visual graph uses the individual node methods below.
    # ------------------------------------------------------------------
    def start(self, issue: dict, *, workflow_id: str | None = None) -> CuratorState:
        state: CuratorState = {"issue": issue, "workflow_id": workflow_id or str(uuid4())}
        for node in (
            self.retrieve_jira_fields,
            self.extract_structured_error_information,
        ):
            state.update(node(state))
        state.update(self.full_text_search(state))
        state.update(self.vector_search(state))
        state.update(self.combine_candidates(state))
        state.update(self.rerank_candidates(state))
        state.update(self.suitable_known_error_found(state))
        route = route_known_error(state)
        if route == "reject":
            state.update(self.reject(state))
            return state
        if route == "existing":
            state.update(self.propose_existing_known_error(state))
        else:
            state.update(self.generate_new_known_error_candidate(state))
        if state.get("automatic_create"):
            state.update(self.automatic_approve(state))
            state = self.publish(state)
        return state

    def publish(self, state: CuratorState) -> CuratorState:
        updated = dict(state)
        for node in (self.publish_approved_knowledge, self.create_update_article_version,
                     self.chunk_content, self.generate_embeddings, self.update_retrieval_index,
                     self.available_for_future_jira):
            updated.update(node(updated))
        return updated

    def apply_review(self, state: CuratorState, review: dict) -> CuratorState:
        if state.get("status") != "WAITING_FOR_REVIEW":
            raise ValueError("This workflow is not waiting for review")
        updated = dict(state)
        updated["review"] = review
        decision = review.get("decision")
        if decision == "APPROVE":
            updated.update(self.approve(updated))
        elif decision == "MODIFY":
            updated.update(self.return_for_ai_revision(updated))
        elif decision == "REJECT":
            updated.update(self.reject(updated))
        else:
            raise ValueError("Unknown review decision")
        return updated

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

    def full_text_search(self, state: CuratorState) -> dict:
        plan = state["retrieval_plan"]
        query = " ".join(plan.get("keywords", [])) or plan.get("semantic_query", "")
        results = self.retrieval.full_text_search(query, top_k=5)
        return {"lexical_candidates": [self._candidate_to_dict(c) for c in results]}

    def vector_search(self, state: CuratorState) -> dict:
        query = state["retrieval_plan"].get("semantic_query", "")
        results = self.retrieval.vector_search(query, top_k=5)
        return {"vector_candidates": [self._candidate_to_dict(c) for c in results]}

    def combine_candidates(self, state: CuratorState) -> dict:
        merged: dict[tuple[str | None, str | None], dict] = {}
        for channel, key in (
            ("lexical", "lexical_candidates"),
            ("vector", "vector_candidates"),
        ):
            for candidate in state.get(key, []):
                identity = (candidate.get("known_error_id"), candidate.get("article_version_id"))
                current = merged.setdefault(identity, dict(candidate))
                methods = current.setdefault("retrieval_methods", [])
                if channel not in methods:
                    methods.append(channel)
                score = float(candidate.get("final_score") or candidate.get("search_score") or 0.0)
                current[f"{channel}_score"] = max(float(current.get(f"{channel}_score", 0.0)), score)
                for score_key in ("exact_score", "lexical_score", "vector_score", "search_score"):
                    current[score_key] = max(
                        float(current.get(score_key, 0.0)), float(candidate.get(score_key, 0.0))
                    )
        return {"candidates": list(merged.values())}

    def rerank_candidates(self, state: CuratorState) -> dict:
        candidates = [dict(c) for c in state.get("candidates", [])]
        for candidate in candidates:
            exact = float(candidate.get("exact_score", 0.0))
            lexical = float(candidate.get("lexical_score", 0.0))
            vector = float(candidate.get("vector_score", 0.0))
            search = float(candidate.get("search_score", 0.0))
            candidate["final_score"] = 0.50 * lexical + 0.50 * vector
        candidates.sort(key=lambda c: c.get("final_score", 0.0), reverse=True)
        for rank, candidate in enumerate(candidates, start=1):
            candidate["rank"] = rank
        return {"candidates": candidates}

    def suitable_known_error_found(self, state: CuratorState) -> dict:
        final_score = max((c.get("final_score", 0) for c in state.get("candidates", [])), default=0)
        high_match = final_score > 0.70
        if high_match or final_score < 0.35:
            return {
                "evaluation": {
                    "recommendation": "USE_EXISTING" if high_match else "CREATE_NEW",
                    "confidence": 1.0,
                    "reasoning": "Combined score exceeds 0.70" if high_match else "Combined score is below 0.35",
                    "final_score": final_score,
                },
                "automatic_create": not high_match,
            }
        evaluation = self.llm.structured(
            system=(
                "Evaluate whether approved KEDB candidates match the incident. "
                "Choose USE_EXISTING, UPDATE_EXISTING or CREATE_NEW."
            ),
            user=f"issue={state['issue']}\ncandidates={state.get('candidates', [])}",
            schema=EvaluationResult,
        )
        return {"evaluation": evaluation.model_dump(mode="json"), "automatic_create": False}

    def propose_existing_known_error(self, state: CuratorState) -> dict:
        proposal = self.llm.structured(
            system="Propose a revision to the selected existing Known Error. Never publish.",
            user=(
                f"issue={state['issue']}\nevaluation={state['evaluation']}\n"
                f"candidates={state.get('candidates', [])}"
            ),
            schema=KnowledgeProposal,
        )
        data = proposal.model_dump(mode="json")
        data["action"] = "UPDATE"
        data["target_known_error_id"] = state["evaluation"].get("selected_known_error_id")
        if not data["target_known_error_id"] or str(data["target_known_error_id"]) not in {
            str(c["known_error_id"]) for c in state.get("candidates", [])
        }:
            raise ValueError("AI must select an existing search candidate for UPDATE")
        return {"proposal": data, "status": "WAITING_FOR_REVIEW"}

    def generate_new_known_error_candidate(self, state: CuratorState) -> dict:
        proposal = self.llm.structured(
            system="Generate a new Known Error proposal from the incident. Never publish.",
            user=f"issue={state['issue']}\nevaluation={state['evaluation']}",
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
        return {"review": {"decision": "APPROVE", "reviewer": "automatic-low-score-policy"},
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
    return "existing" if recommendation == "UPDATE_EXISTING" else "new"


def route_review(state: CuratorState) -> str:
    decision = state["review"].get("decision")
    if decision == "APPROVE":
        return "approve"
    if decision == "MODIFY":
        return "modify"
    if decision == "REJECT":
        return "reject"
    raise ValueError(f"Unknown review decision: {decision}")


def build_langgraph(workflow: CuratorWorkflow, *, checkpointer=None):
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(CuratorState)

    for node_name, _label, _kind in GRAPH_NODES:
        graph.add_node(node_name, getattr(workflow, node_name))

    graph.add_edge(START, "retrieve_jira_fields")
    graph.add_edge("retrieve_jira_fields", "extract_structured_error_information")

    # Fan-out hybrid retrieval.
    graph.add_edge("extract_structured_error_information", "full_text_search")
    graph.add_edge("extract_structured_error_information", "vector_search")

    # Barrier: combine only after both retrieval branches have completed.
    graph.add_edge(["full_text_search", "vector_search"], "combine_candidates")
    graph.add_edge("combine_candidates", "rerank_candidates")
    graph.add_edge("rerank_candidates", "suitable_known_error_found")

    graph.add_conditional_edges(
        "suitable_known_error_found",
        route_known_error,
        {"existing": "propose_existing_known_error", "new": "generate_new_known_error_candidate", "reject": "reject"},
    )
    graph.add_edge("propose_existing_known_error", "human_review")
    graph.add_conditional_edges(
        "generate_new_known_error_candidate",
        lambda state: "automatic" if state.get("automatic_create") else "review",
        {"automatic": "automatic_approve", "review": "human_review"},
    )
    graph.add_edge("automatic_approve", "publish_approved_knowledge")
    graph.add_edge("reject", END)

    graph.add_conditional_edges(
        "human_review",
        route_review,
        {"approve": "approve", "modify": "return_for_ai_revision", "reject": "reject"},
    )
    graph.add_edge("return_for_ai_revision", "human_review")

    graph.add_edge("approve", "publish_approved_knowledge")
    graph.add_edge("publish_approved_knowledge", "create_update_article_version")
    graph.add_edge("create_update_article_version", "chunk_content")
    graph.add_edge("chunk_content", "generate_embeddings")
    graph.add_edge("generate_embeddings", "update_retrieval_index")
    graph.add_edge("update_retrieval_index", "available_for_future_jira")
    graph.add_edge("available_for_future_jira", END)

    return graph.compile(checkpointer=checkpointer)
