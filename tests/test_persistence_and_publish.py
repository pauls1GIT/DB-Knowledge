from uuid import uuid4
import pytest
from kedb.infrastructure.lakebase import Database, SqlRepositories
from kedb.domain import HumanReview, ReviewDecision
from kedb.application.dto import KnowledgeProposal
from kedb.application.use_cases import PublishApprovedKnowledge, semantic_chunks

def repo_ctx():
    db=Database('sqlite+pysqlite:///:memory:'); db.create_all(); return db

def test_publish_create_and_update_preserves_v1():
    db=repo_ctx(); wf=uuid4()
    p=KnowledgeProposal(action='CREATE',title='Oracle timeout',problem='Cannot connect',root_cause='Network timeout',solution='Fix route')
    review=HumanReview(workflow_id=wf,decision=ReviewDecision.APPROVE,reviewer='alice')
    with db.sessions.begin() as s:
        repo=SqlRepositories(s); v1=PublishApprovedKnowledge(repo).execute(proposal=p,review=review)
    assert len(semantic_chunks(v1))==3
    p2=KnowledgeProposal(action='UPDATE',target_known_error_id=v1.known_error_id,title='Oracle timeout',problem='Cannot connect',root_cause='Firewall timeout',solution='Fix firewall')
    review2=HumanReview(workflow_id=uuid4(),decision=ReviewDecision.APPROVE,reviewer='bob')
    with db.sessions.begin() as s:
        repo=SqlRepositories(s); v2=PublishApprovedKnowledge(repo).execute(proposal=p2,review=review2)
    with db.sessions() as s:
        repo=SqlRepositories(s); versions=repo.list_versions(v1.known_error_id); ke=repo.get_known_error(v1.known_error_id)
    assert [v.version_number for v in versions]==[1,2]
    assert ke.current_version_id==v2.id

def test_reject_cannot_publish():
    db=repo_ctx(); p=KnowledgeProposal(action='CREATE',title='x',problem='p',root_cause='r',solution='s')
    review=HumanReview(workflow_id=uuid4(),decision=ReviewDecision.REJECT,reviewer='alice')
    with pytest.raises(ValueError):
        with db.sessions.begin() as s: PublishApprovedKnowledge(SqlRepositories(s)).execute(proposal=p,review=review)


@pytest.mark.parametrize("decision", [ReviewDecision.REJECT, ReviewDecision.MODIFY])
def test_non_approval_never_publishes(decision):
    db = repo_ctx()
    proposal = KnowledgeProposal(action="CREATE", title="t", problem="p", root_cause="r", solution="s")
    with pytest.raises(ValueError), db.sessions.begin() as session:
        PublishApprovedKnowledge(SqlRepositories(session)).execute(proposal=proposal,
            review=HumanReview(workflow_id=uuid4(), decision=decision, reviewer="alice"))


def test_retries_and_normalized_content_create_only_one_article_and_outbox():
    from sqlalchemy import select, func
    from kedb.infrastructure.lakebase.models import ArticleVersionRow, PublicationOutboxRow, HumanReviewRow
    db = repo_ctx()
    proposal = KnowledgeProposal(action="CREATE", title="t", problem="A Problem", root_cause="r", solution="A solution")
    def publish(p, wf):
        with db.sessions.begin() as session:
            return PublishApprovedKnowledge(SqlRepositories(session)).execute(proposal=p,
                review=HumanReview(workflow_id=wf, decision=ReviewDecision.APPROVE, reviewer="alice"))
    wf = uuid4()
    first = publish(proposal, wf)
    assert publish(proposal.model_copy(update={"solution": "changed"}), wf).id == first.id
    assert publish(proposal.model_copy(update={"title": "another title", "problem": " a  PROBLEM "}), uuid4()).id == first.id
    with db.sessions() as session:
        assert len(SqlRepositories(session).list_known_errors()) == 1
        for model in (ArticleVersionRow, PublicationOutboxRow, HumanReviewRow):
            assert session.scalar(select(func.count()).select_from(model)) == 1


def test_same_ticket_cannot_publish_twice_even_with_changed_content():
    from kedb.domain import JiraIssue
    db = repo_ctx()
    issue = JiraIssue(external_key="T-1", summary="t", description="d", resolution="r")
    with db.sessions.begin() as session:
        SqlRepositories(session).add_jira(issue)
    versions = []
    for solution in ("first solution", "different solution"):
        with db.sessions.begin() as session:
            versions.append(PublishApprovedKnowledge(SqlRepositories(session)).execute(
                proposal=KnowledgeProposal(action="CREATE", title="t", problem="p", root_cause="r", solution=solution),
                review=HumanReview(workflow_id=uuid4(), decision=ReviewDecision.APPROVE, reviewer="alice"),
                jira_issue_id=issue.id))
    assert versions[0].id == versions[1].id


def test_failed_update_rolls_back_claims():
    from sqlalchemy import select, func
    from kedb.infrastructure.lakebase.models import PublicationClaimRow
    db = repo_ctx()
    with pytest.raises(LookupError), db.sessions.begin() as session:
        PublishApprovedKnowledge(SqlRepositories(session)).execute(
            proposal=KnowledgeProposal(action="UPDATE", target_known_error_id=uuid4(),
                                       title="t", problem="p", root_cause="r", solution="s"),
            review=HumanReview(workflow_id=uuid4(), decision=ReviewDecision.APPROVE, reviewer="alice"))
    with db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(PublicationClaimRow)) == 0
