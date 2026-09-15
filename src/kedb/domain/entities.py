from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4


class ReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    REJECT = "REJECT"


class ArticleStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"


class Recommendation(StrEnum):
    USE_EXISTING = "USE_EXISTING"
    UPDATE_EXISTING = "UPDATE_EXISTING"
    CREATE_NEW = "CREATE_NEW"


@dataclass(slots=True)
class JiraIssue:
    external_key: str
    summary: str
    description: str
    resolution: str
    error_code: str | None = None
    id: UUID = field(default_factory=uuid4)
    external_id: str | None = None
    status: str | None = None
    priority: str | None = None
    issue_type: str | None = None
    environment: str | None = None
    parent_external_key: str | None = None
    resolved_at: datetime | None = None
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    raw_payload: dict | None = None
    ground_truth_error_group: str | None = None
    ground_truth_known_error: UUID | None = None


@dataclass(slots=True)
class KnownError:
    title: str
    id: UUID = field(default_factory=uuid4)
    current_version_id: UUID | None = None


@dataclass(slots=True, frozen=True)
class ArticleVersion:
    known_error_id: UUID
    version_number: int
    title: str
    problem: str
    root_cause: str
    solution: str
    source_jira_issue_id: UUID
    status: ArticleStatus = ArticleStatus.DRAFT
    review_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_published(self) -> bool:
        return self.status == ArticleStatus.PUBLISHED


@dataclass(slots=True, frozen=True)
class ArticleChunk:
    article_version_id: UUID
    chunk_index: int
    section: str
    content: str
    id: UUID = field(default_factory=uuid4)


@dataclass(slots=True)
class RetrievalCandidate:
    known_error_id: UUID
    article_version_id: UUID
    title: str
    exact_score: float = 0.0
    lexical_score: float = 0.0
    vector_score: float = 0.0
    final_score: float = 0.0
    rank: int = 0


@dataclass(slots=True)
class HumanReview:
    workflow_id: UUID
    decision: ReviewDecision
    reviewer: str
    feedback: str | None = None
    modified_content: dict | None = None
    id: UUID = field(default_factory=uuid4)
