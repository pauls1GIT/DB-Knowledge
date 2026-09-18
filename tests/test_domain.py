from uuid import uuid4
import pytest
from kedb.domain import ArticleVersion, HumanReview, ReviewDecision, ArticleStatus, create_new_version

def test_rejected_article_cannot_publish():
    v=ArticleVersion(known_error_id=uuid4(),version_number=1,title='x',problem='p',root_cause='r',solution='s')
    review=HumanReview(workflow_id=uuid4(),decision=ReviewDecision.REJECT,reviewer='r')
    with pytest.raises(ValueError): v.publish(review)

def test_approved_published_can_embed_and_new_version_increments():
    ke=uuid4(); review=HumanReview(workflow_id=uuid4(),decision=ReviewDecision.APPROVE,reviewer='r')
    v1=ArticleVersion(known_error_id=ke,version_number=1,title='x',problem='p',root_cause='r',solution='s').publish(review)
    assert v1.status==ArticleStatus.PUBLISHED and v1.can_embed
    v2=create_new_version([v1],ke,title='x2',problem='p',root_cause='r',solution='s')
    assert v2.version_number==2 and not v2.can_embed
