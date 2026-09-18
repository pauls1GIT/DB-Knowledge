from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class ArticleStatus(str, Enum):
    DRAFT = 'DRAFT'
    PUBLISHED = 'PUBLISHED'

class ReviewDecision(str, Enum):
    APPROVE = 'APPROVE'
    MODIFY = 'MODIFY'
    REJECT = 'REJECT'

class Recommendation(str, Enum):
    USE_EXISTING = 'USE_EXISTING'
    UPDATE_EXISTING = 'UPDATE_EXISTING'
    CREATE_NEW = 'CREATE_NEW'

@dataclass(frozen=True)
class JiraIssue:
    external_key: str
    summary: str
    description: str
    resolution: str
    error_code: Optional[str] = None
    id: UUID = field(default_factory=uuid4)

@dataclass(frozen=True)
class HumanReview:
    workflow_id: UUID
    decision: ReviewDecision
    reviewer: str
    feedback: Optional[str] = None
    modified_content: Optional[dict] = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utcnow)

@dataclass(frozen=True)
class ArticleVersion:
    known_error_id: UUID
    version_number: int
    title: str
    problem: str
    root_cause: str
    solution: str
    status: ArticleStatus = ArticleStatus.DRAFT
    source_jira_issue_id: Optional[UUID] = None
    review_id: Optional[UUID] = None
    id: UUID = field(default_factory=uuid4)
    published_at: Optional[datetime] = None

    def publish(self, review: HumanReview) -> 'ArticleVersion':
        if review.decision != ReviewDecision.APPROVE:
            raise ValueError('Publication requires APPROVE')
        if self.status == ArticleStatus.PUBLISHED:
            raise ValueError('Published versions are immutable')
        return replace(self, status=ArticleStatus.PUBLISHED, review_id=review.id, published_at=utcnow())

    @property
    def can_embed(self) -> bool:
        return self.status == ArticleStatus.PUBLISHED and self.review_id is not None

@dataclass
class KnownError:
    title: str
    id: UUID = field(default_factory=uuid4)
    current_version_id: Optional[UUID] = None

@dataclass(frozen=True)
class ArticleChunk:
    known_error_id: UUID
    article_version_id: UUID
    chunk_index: int
    section: str
    content: str
    id: UUID = field(default_factory=uuid4)

@dataclass(frozen=True)
class RetrievalCandidate:
    known_error_id: UUID
    article_version_id: UUID
    title: str
    exact_score: float = 0.0
    lexical_score: float = 0.0
    vector_score: float = 0.0
    search_score: float = 0.0
    final_score: float = 0.0
    rank: int = 0


def create_new_version(existing: list[ArticleVersion], known_error_id: UUID, **content) -> ArticleVersion:
    next_number = max((v.version_number for v in existing), default=0) + 1
    return ArticleVersion(known_error_id=known_error_id, version_number=next_number, **content)
