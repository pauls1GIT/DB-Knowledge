from uuid import uuid4

from kedb.application.dto import EvaluationResult, KnowledgeProposal, RetrievalPlan
from kedb.application.retrieval import RetrievalCoordinator
from kedb.application.workflows.curator import (
    GRAPH_EDGES,
    GRAPH_NODES,
    CuratorWorkflow,
    build_langgraph,
    workflow_dot,
)
from kedb.infrastructure.llm.fake import FakeLLM
from kedb.infrastructure.search.in_memory import InMemorySearch


def _workflow():
    known_error_id, version_id = uuid4(), uuid4()
    llm = FakeLLM(
        {
            RetrievalPlan: RetrievalPlan(
                semantic_query="oracle timeout",
                keywords=["oracle", "timeout"],
                exact_identifiers=["ORA-12170"],
                error_codes=["ORA-12170"],
            ),
            EvaluationResult: EvaluationResult(
                recommendation="UPDATE_EXISTING",
                selected_known_error_id=known_error_id,
                selected_article_version_id=version_id,
                confidence=0.9,
                reasoning="match",
            ),
            KnowledgeProposal: KnowledgeProposal(
                action="UPDATE",
                target_known_error_id=known_error_id,
                title="t",
                problem="p",
                root_cause="r",
                solution="s",
            ),
        }
    )
    retrieval = RetrievalCoordinator(
        InMemorySearch(
            [
                {
                    "known_error_id": known_error_id,
                    "article_version_id": version_id,
                    "title": "Oracle timeout",
                    "content": "ORA-12170 oracle timeout",
                }
            ]
        )
    )
    return CuratorWorkflow(llm, retrieval)


def test_graph_has_visible_retrieval_fanout_and_review_loop():
    node_ids = {node_id for node_id, _label, _kind in GRAPH_NODES}
    assert {"exact_search", "full_text_search", "vector_search", "human_review"} <= node_ids
    assert ("human_review", "return_for_ai_revision", "Modify") in GRAPH_EDGES
    assert ("return_for_ai_revision", "human_review", None) in GRAPH_EDGES
    assert "Vector Search" in workflow_dot()


def test_compiled_graph_exposes_expected_nodes():
    import pytest
    pytest.importorskip("langgraph")
    graph = build_langgraph(_workflow())
    rendered = graph.get_graph()
    assert "exact_search" in rendered.nodes
    assert "human_review" in rendered.nodes
    assert "publish_approved_knowledge" in rendered.nodes
