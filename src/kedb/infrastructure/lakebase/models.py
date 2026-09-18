from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON, Boolean, Float, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime, timezone
from uuid import uuid4

def now(): return datetime.now(timezone.utc)
def uid(): return str(uuid4())

class Base(DeclarativeBase): pass

class JiraIssueRow(Base):
    __tablename__='jira_issue'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    external_key: Mapped[str] = mapped_column(String(100), unique=True)
    summary: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    resolution: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str|None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class KnownErrorRow(Base):
    __tablename__='known_error'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(500))
    current_version_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class ArticleVersionRow(Base):
    __tablename__='article_version'
    __table_args__=(UniqueConstraint('known_error_id','version_number'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    known_error_id: Mapped[str] = mapped_column(ForeignKey('known_error.id'))
    version_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    problem: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str] = mapped_column(Text)
    solution: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40))
    source_jira_issue_id: Mapped[str|None] = mapped_column(ForeignKey('jira_issue.id'), nullable=True)
    review_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    published_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class HumanReviewRow(Base):
    __tablename__='human_review'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workflow_id: Mapped[str] = mapped_column(String(36), index=True)
    decision: Mapped[str] = mapped_column(String(30))
    reviewer: Mapped[str] = mapped_column(String(200))
    feedback: Mapped[str|None] = mapped_column(Text, nullable=True)
    modified_content: Mapped[dict|None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class WorkflowCheckpointRow(Base):
    __tablename__='workflow_checkpoint'
    workflow_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(40))
    current_step: Mapped[str] = mapped_column(String(80))
    state: Mapped[dict] = mapped_column(JSON)
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class PublicationOutboxRow(Base):
    __tablename__='publication_outbox'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    article_version_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(80), default='ARTICLE_PUBLISHED')
    payload: Mapped[dict] = mapped_column(JSON)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class RetrievalCandidateRow(Base):
    __tablename__='retrieval_candidate'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    retrieval_session_id: Mapped[str] = mapped_column(String(36), index=True)
    known_error_id: Mapped[str] = mapped_column(String(36))
    article_version_id: Mapped[str] = mapped_column(String(36))
    retrieval_method: Mapped[str] = mapped_column(String(40))
    exact_score: Mapped[float] = mapped_column(Float, default=0)
    lexical_score: Mapped[float] = mapped_column(Float, default=0)
    vector_score: Mapped[float] = mapped_column(Float, default=0)
    final_score: Mapped[float] = mapped_column(Float, default=0)
    rank: Mapped[int] = mapped_column(Integer)


class PublicationClaimRow(Base):
    """Transactionally reserve publication identities, including concurrent retries."""
    __tablename__ = 'publication_claim'
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    article_version_id: Mapped[str] = mapped_column(String(36))


class CsvBatchRow(Base):
    __tablename__ = 'csv_batch'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    items: Mapped[list] = mapped_column(JSON)
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default='RUNNING')
    results: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
