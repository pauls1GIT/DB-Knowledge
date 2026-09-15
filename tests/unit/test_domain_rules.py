from uuid import uuid4
import pytest
from kedb.domain.entities import ArticleVersion, ArticleStatus, ReviewDecision
from kedb.domain.rules import ensure_can_embed, validate_review_for_publication, DomainRuleViolation

def version(status):
    return ArticleVersion(known_error_id=uuid4(),version_number=1,title="x",problem="p",root_cause="r",solution="s",source_jira_issue_id=uuid4(),status=status)

def test_rejected_review_cannot_publish():
    with pytest.raises(DomainRuleViolation): validate_review_for_publication(ReviewDecision.REJECT)

def test_draft_cannot_embed():
    with pytest.raises(DomainRuleViolation): ensure_can_embed(version(ArticleStatus.DRAFT))

def test_published_can_embed():
    ensure_can_embed(version(ArticleStatus.PUBLISHED))

def test_modify_review_cannot_publish_directly():
    with pytest.raises(DomainRuleViolation): validate_review_for_publication(ReviewDecision.MODIFY)

def test_approve_can_publish():
    validate_review_for_publication(ReviewDecision.APPROVE)
