from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Text, Float, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


def now(): return datetime.now(timezone.utc)


class JiraIssueModel(Base):
    __tablename__ = "jira_issue"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    external_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    resolution: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    priority: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issue_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    environment: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_external_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ground_truth_error_group: Mapped[str | None] = mapped_column(String(128))
    ground_truth_known_error: Mapped[object | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KnownErrorModel(Base):
    __tablename__ = "known_error"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(500))
    current_version_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ArticleVersionModel(Base):
    __tablename__ = "article_version"
    __table_args__ = (UniqueConstraint("known_error_id", "version_number"),)
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    known_error_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("known_error.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    problem: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str] = mapped_column(Text)
    solution: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    source_jira_issue_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("jira_issue.id"))
    review_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    search_vector: Mapped[object | None] = mapped_column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ArticleChunkModel(Base):
    __tablename__ = "article_chunk"
    __table_args__ = (UniqueConstraint("article_version_id", "chunk_index"),)
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    article_version_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("article_version.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class JiraKnownErrorLinkModel(Base):
    __tablename__ = "jira_known_error_link"
    __table_args__ = (UniqueConstraint("jira_issue_id", "known_error_id"),)
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    jira_issue_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("jira_issue.id"), index=True)
    known_error_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("known_error.id"), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class HumanReviewModel(Base):
    __tablename__ = "human_review"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[object] = mapped_column(UUID(as_uuid=True), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    reviewer: Mapped[str] = mapped_column(String(255))
    feedback: Mapped[str | None] = mapped_column(Text)
    modified_content: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RetrievalSessionModel(Base):
    __tablename__ = "retrieval_session"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    jira_issue_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    query: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RetrievalCandidateModel(Base):
    __tablename__ = "retrieval_candidate"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    retrieval_session_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("retrieval_session.id"), index=True)
    known_error_id: Mapped[object] = mapped_column(UUID(as_uuid=True))
    article_version_id: Mapped[object] = mapped_column(UUID(as_uuid=True))
    exact_score: Mapped[float] = mapped_column(Float, default=0)
    lexical_score: Mapped[float] = mapped_column(Float, default=0)
    vector_score: Mapped[float] = mapped_column(Float, default=0)
    final_score: Mapped[float] = mapped_column(Float, default=0)
    rank: Mapped[int] = mapped_column(Integer, default=0)


class WorkflowEventModel(Base):
    __tablename__ = "workflow_event"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[object] = mapped_column(UUID(as_uuid=True), index=True)
    event_type: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEventModel(Base):
    __tablename__ = "audit_event"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    entity_type: Mapped[str] = mapped_column(String(128))
    entity_id: Mapped[object] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(128))
    actor: Mapped[str] = mapped_column(String(255))
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EmbeddingModelModel(Base):
    __tablename__ = "embedding_model"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(128))
    model_name: Mapped[str] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class VectorReferenceModel(Base):
    __tablename__ = "vector_reference"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    article_chunk_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("article_chunk.id"), unique=True)
    embedding_model_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    vector_store: Mapped[str] = mapped_column(String(64))
    collection_name: Mapped[str] = mapped_column(String(255))
    external_vector_id: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ChatSessionModel(Base):
    __tablename__ = "chat_session"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ChatMessageModel(Base):
    __tablename__ = "chat_message"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    chat_session_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_session.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ChatRetrievalModel(Base):
    __tablename__ = "chat_retrieval"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    chat_session_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_session.id"), index=True)
    retrieval_session_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("retrieval_session.id"), index=True)


class DuplicateGroupModel(Base):
    __tablename__ = "duplicate_group"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(String(32), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DuplicateGroupMemberModel(Base):
    __tablename__ = "duplicate_group_member"
    __table_args__ = (UniqueConstraint("duplicate_group_id", "jira_issue_id"),)
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    duplicate_group_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("duplicate_group.id"), index=True)
    jira_issue_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("jira_issue.id"), index=True)
    similarity_score: Mapped[float] = mapped_column(Float)


class ImportBatchModel(Base):
    __tablename__ = "import_batch"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    filename: Mapped[str] = mapped_column(String(500))
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    skipped_rows: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="IMPORTING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImportItemModel(Base):
    __tablename__ = "import_item"
    __table_args__ = (UniqueConstraint("import_batch_id", "row_number"),)
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    import_batch_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batch.id"), index=True)
    jira_issue_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jira_issue.id"), nullable=True, index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    workflow_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
