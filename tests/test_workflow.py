from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from kedb.application.workflows.curator import CuratorWorkflow, build_langgraph
from kedb.application.dto import RetrievalPlan, EvaluationResult, KnowledgeProposal
from kedb.infrastructure.llm.fake import FakeLLM


class Search:
    def __init__(self, scores):
        self.scores = scores
        self.ke, self.version = uuid4(), uuid4()

    def rows(self, channel):
        score = self.scores[channel]
        return [{"known_error_id": str(self.ke), "article_version_id": str(self.version),
                 channel + "_score": score, "final_score": score, "search_score": score}]

    def exact_search(self, *args, **kwargs): return self.rows("exact")
    def full_text_search(self, *args, **kwargs): return self.rows("lexical")
    def vector_search(self, *args, **kwargs): return self.rows("vector")


def workflow(scores=None, publisher=None):
    search = Search(scores or dict(exact=.4, lexical=.4, vector=.4))
    llm = FakeLLM({
        RetrievalPlan: RetrievalPlan(semantic_query="timeout", exact_identifiers=["ERR-123"]),
        EvaluationResult: EvaluationResult(recommendation="UPDATE_EXISTING",
            selected_known_error_id=search.ke, confidence=.9, reasoning="match"),
        KnowledgeProposal: KnowledgeProposal(action="UPDATE", target_known_error_id=search.ke,
            title="t", problem="p", root_cause="r", solution="s"),
    })
    return CuratorWorkflow(llm, search, publisher=publisher)


@pytest.mark.parametrize("channel", ["lexical", "vector"])
def test_any_high_search_rejects_without_publication(channel):
    scores = dict(exact=1, lexical=.70, vector=.70)
    scores[channel] = .70001
    wf = workflow(scores, publisher=lambda _: pytest.fail("Must not publish"))
    state = wf.start({"summary": "timeout"})
    assert state["status"] == "REJECTED"
    assert "proposal" not in state
    compiled = build_langgraph(wf).invoke({"issue": {"summary": "timeout"}})
    assert compiled["status"] == "REJECTED"


@pytest.mark.parametrize("score", [0, .34999])
def test_low_score_creates_and_publishes_without_human_review(score):
    published = []
    wf = workflow(dict(exact=score, lexical=score, vector=score),
                  publisher=lambda state: published.append(state["proposal"]) or {})
    state = build_langgraph(wf).invoke({"issue": {"summary": "new issue"}})
    assert state["status"] == "PUBLISHED_PENDING_INDEX"
    assert published[0]["action"] == "CREATE"
    assert published[0]["target_known_error_id"] is None


@pytest.mark.parametrize("score", [.35, .70])
def test_boundary_scores_require_review(score):
    state = workflow(dict(exact=score, lexical=score, vector=score)).start({"summary": "timeout"})
    assert state["status"] == "WAITING_FOR_REVIEW"
    assert state["proposal"]["action"] == "UPDATE"


def test_modify_revises_and_reject_ends_without_publication():
    wf = workflow(publisher=lambda _: pytest.fail("Must not publish"))
    state = wf.start({"summary": "timeout"})
    revised = wf.apply_review(state, {"decision": "MODIFY", "feedback": "wrong solution"})
    assert revised["status"] == "WAITING_FOR_REVIEW"
    assert revised["revision_count"] == 1
    rejected = wf.apply_review(revised, {"decision": "REJECT"})
    assert rejected["status"] == "REJECTED"
    with pytest.raises(ValueError): wf.publish(rejected)


def test_graph_modify_loops_and_reject_terminates():
    graph = build_langgraph(workflow(), checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid4())}}
    state = graph.invoke({"issue": {"summary": "timeout"}}, config)
    assert state["__interrupt__"]
    state = graph.invoke(Command(resume={"decision": "MODIFY", "feedback": "revise"}), config)
    assert state["revision_count"] == 1
    assert state["__interrupt__"]
    state = graph.invoke(Command(resume={"decision": "REJECT"}), config)
    assert state["status"] == "REJECTED"
    assert "publication_result" not in state


def test_exact_score_does_not_affect_formula_or_decision():
    state = workflow(dict(exact=1, lexical=.4, vector=.6)).start({"summary": "timeout"})
    assert state["candidates"][0]["final_score"] == .5
    assert state["status"] == "WAITING_FOR_REVIEW"


def test_single_high_channel_does_not_override_combined_score():
    state = workflow(dict(exact=1, lexical=.9, vector=.1)).start({"summary": "timeout"})
    assert state["candidates"][0]["final_score"] == .5
    assert state["status"] == "WAITING_FOR_REVIEW"
