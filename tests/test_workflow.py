from uuid import uuid4
from types import SimpleNamespace

import pytest

from kedb.application.workflows.curator import CuratorWorkflow, build_langgraph
from kedb.application.dto import RetrievalPlan, KnowledgeProposal
from kedb.infrastructure.llm.fake import FakeLLM


class Search:
    def __init__(self, exact=1):
        self.ke, self.version = str(uuid4()), str(uuid4())
        self.exact = exact

    def exact_search(self, *args, **kwargs):
        return [{"known_error_id": self.ke, "article_version_id": self.version,
                 "exact_score": self.exact, "final_score": self.exact}]

    def hybrid_search(self, *args, **kwargs):
        return [{"known_error_id": self.ke, "article_version_id": self.version,
                 "final_score": 999}]  # Backend scores must never drive duplication.


class Scorer:
    embedder = SimpleNamespace(model="test", model_version="v1")

    def __init__(self, score):
        self.value = score

    def score(self, proposal, candidates):
        assert proposal["problem"] == "p"
        return [{**c, "cosine_score": self.value} for c in candidates]


def workflow(score=.9, publisher=None, threshold=.9, approval=.6):
    llm = FakeLLM({
        RetrievalPlan: RetrievalPlan(semantic_query="timeout", exact_identifiers=["ERR-123"]),
        KnowledgeProposal: KnowledgeProposal(action="CREATE", title="t", problem="p", root_cause="r", solution="s"),
    })  # No EvaluationResult response: an LLM evaluation would fail this test.
    return CuratorWorkflow(llm, Search(), publisher=publisher,
                           duplicate_scorer=Scorer(score), duplicate_threshold=threshold, auto_approve_threshold=approval)


@pytest.mark.parametrize("score", [.9, .90001, 1.0])
def test_cosine_at_or_above_threshold_rejects_without_publication(score):
    wf = workflow(score, publisher=lambda _: pytest.fail("Must not publish"))
    for state in (wf.start({"summary": "timeout"}),
                  build_langgraph(wf).invoke({"issue": {"summary": "timeout"}})):
        assert state["status"] == "REJECTED"
        assert state["evaluation"]["cosine_score"] == score
        assert state["candidates"][0]["final_score"] == score
        assert "publication_result" not in state


@pytest.mark.parametrize("score", [-1, 0, .59999])
def test_below_threshold_publishes_even_with_exact_code_match(score):
    published = []
    wf = workflow(score, publisher=lambda state: published.append(state["proposal"]) or {})
    state = wf.start({"summary": "timeout"})
    assert state["status"] == "PUBLISHED_PENDING_INDEX"
    assert published[0]["action"] == "CREATE"
    assert state["evaluation"]["duplicate_threshold"] == .9
    assert state["evaluation"]["embedding_model"] == "test"


def test_no_articles_approves_without_inventing_zero_score():
    wf = workflow()
    wf.duplicate_scorer.score = lambda *args: []
    state = wf.start({"summary": "new"})
    assert state["evaluation"]["cosine_score"] is None
    assert state["evaluation"]["compared_articles"] == 0
    assert state["status"] == "AVAILABLE_FOR_FUTURE_JIRA"


@pytest.mark.parametrize("score", [float("nan"), float("inf"), 1.1, None])
def test_invalid_score_never_approves(score):
    with pytest.raises(ValueError, match="cosine score"):
        workflow(score, publisher=lambda _: pytest.fail("Must not publish")).start({})


def test_scorer_failure_never_approves():
    wf = workflow(publisher=lambda _: pytest.fail("Must not publish"))
    wf.duplicate_scorer = None
    with pytest.raises(ValueError, match="scorer is required"):
        wf.start({})


def test_merge_keeps_each_article_once_without_rank_fusion():
    wf = workflow()
    a = {"known_error_id": "a", "article_version_id": "a", "exact_score": 1}
    b = {"known_error_id": "b", "article_version_id": "b", "final_score": .9}
    merged = wf.combine_candidates({"exact_candidates": [a, a], "hybrid_candidates": [b, a]})
    assert len(merged["candidates"]) == 2
    assert merged["candidates"][0]["retrieval_methods"] == ["exact", "hybrid"]


def test_saved_manual_review_can_still_be_revised_and_rejected():
    wf = workflow(publisher=lambda _: pytest.fail("Must not publish"))
    state = {"workflow_id": str(uuid4()), "status": "WAITING_FOR_REVIEW",
             "proposal": {"action": "CREATE"}, "revision_count": 0}
    revised = wf.apply_review(state, {"decision": "MODIFY", "feedback": "wrong solution"})
    assert revised["revision_count"] == 1
    assert revised["status"] == "WAITING_FOR_REVIEW"
    rejected = wf.apply_review(revised, {"decision": "REJECT"})
    assert rejected["status"] == "REJECTED"
    with pytest.raises(ValueError):
        wf.publish(rejected)


def test_threshold_is_configurable():
    assert workflow(.7, threshold=.6, approval=.4).start({})["status"] == "REJECTED"
    with pytest.raises(ValueError, match="threshold"):
        workflow(threshold=float("nan"))


@pytest.mark.parametrize("score", [.6, .7, .89999])
def test_middle_band_waits_for_review_without_publication(score):
    wf = workflow(score, publisher=lambda _: pytest.fail("Must not publish before approval"))
    state = wf.start({"summary": "timeout"})
    assert state["status"] == "WAITING_FOR_REVIEW"
    assert state["evaluation"]["decision"] == "HUMAN_REVIEW"
    assert state["evaluation"]["auto_approve_threshold"] == .6
    assert not state["automatic_create"]
    assert "publication_result" not in state
    approved = wf.apply_review(state, {"decision": "APPROVE", "reviewer": "tester"})
    assert approved["status"] == "APPROVED_FOR_PUBLICATION"


def test_interactive_middle_band_interrupts_and_can_reject():
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command
    graph = build_langgraph(workflow(.7), checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid4())}}
    state = graph.invoke({"issue": {"summary": "timeout"}}, config)
    assert state["__interrupt__"]
    state = graph.invoke(Command(resume={"decision": "REJECT"}), config)
    assert state["status"] == "REJECTED"
    assert "publication_result" not in state


@pytest.mark.parametrize("approval,rejection", [(.9, .9), (.95, .9), (float("nan"), .9)])
def test_invalid_threshold_order_is_rejected(approval, rejection):
    from kedb.config import Settings
    with pytest.raises(ValueError):
        workflow(approval=approval, threshold=rejection)
    with pytest.raises(ValueError):
        Settings(_env_file=None, kedb_auto_approve_threshold=approval, kedb_duplicate_threshold=rejection)
