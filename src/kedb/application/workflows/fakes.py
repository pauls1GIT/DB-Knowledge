from uuid import UUID

from kedb.application.dto import EvaluationResult, KnowledgeProposal, RetrievalPlan
from kedb.infrastructure.llm.fake import FakeLLM
from kedb.infrastructure.search.in_memory import InMemorySearch
from kedb.application.retrieval import RetrievalCoordinator


def studio_fake_llm() -> FakeLLM:
    return FakeLLM(
        {
            RetrievalPlan: RetrievalPlan(
                semantic_query="Oracle application connection timeout ORA-12170",
                keywords=["oracle", "connection", "timeout"],
                exact_identifiers=["ORA-12170"],
                error_codes=["ORA-12170"],
            ),
            EvaluationResult: EvaluationResult(
                recommendation="CREATE_NEW",
                selected_known_error_id=None,
                selected_article_version_id=None,
                confidence=0.90,
                reasoning="Studio demo: no approved matching Known Error was found.",
                evidence_ids=[],
            ),
            KnowledgeProposal: KnowledgeProposal(
                action="CREATE",
                target_known_error_id=None,
                title="Oracle connection timeout ORA-12170",
                problem="The application cannot establish an Oracle database connection.",
                root_cause="The connection request times out before a session is established.",
                solution="Verify network connectivity, the Oracle listener, and connection settings.",
                evidence_ids=[],
            ),
        }
    )


def studio_fake_retrieval() -> RetrievalCoordinator:
    # Empty by design so the demo follows the CREATE_NEW branch.
    return RetrievalCoordinator(InMemorySearch([]))
