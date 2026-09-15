from __future__ import annotations
from uuid import UUID
from sqlalchemy import select, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from kedb.domain.entities import ArticleChunk, ArticleStatus, ArticleVersion, HumanReview, JiraIssue, KnownError, RetrievalCandidate
from .database import SessionLocal
from .models import *


class SqlAlchemyKnowledgeRepository:
    def __init__(self, session_factory=SessionLocal): self.session_factory = session_factory

    def save_issue(self, issue: JiraIssue) -> JiraIssue:
        with self.session_factory.begin() as s:
            existing=s.scalar(select(JiraIssueModel).where(JiraIssueModel.external_key==issue.external_key))
            if existing is not None:
                issue.id=existing.id
            row = JiraIssueModel(id=issue.id, external_key=issue.external_key, external_id=issue.external_id, summary=issue.summary,
                description=issue.description, resolution=issue.resolution, error_code=issue.error_code, status=issue.status,
                priority=issue.priority, issue_type=issue.issue_type, environment=issue.environment,
                parent_external_key=issue.parent_external_key, resolved_at=issue.resolved_at,
                source_created_at=issue.source_created_at, source_updated_at=issue.source_updated_at, raw_payload=issue.raw_payload,
                ground_truth_error_group=issue.ground_truth_error_group, ground_truth_known_error=issue.ground_truth_known_error)
            s.merge(row)
        return issue

    def get_issue(self, issue_id: UUID):
        with self.session_factory() as s:
            r=s.get(JiraIssueModel, issue_id)
            return None if not r else JiraIssue(id=r.id, external_key=r.external_key, external_id=r.external_id, summary=r.summary,
                description=r.description, resolution=r.resolution, error_code=r.error_code, status=r.status,
                priority=r.priority, issue_type=r.issue_type, environment=r.environment, parent_external_key=r.parent_external_key,
                resolved_at=r.resolved_at, source_created_at=r.source_created_at, source_updated_at=r.source_updated_at, raw_payload=r.raw_payload,
                ground_truth_error_group=r.ground_truth_error_group, ground_truth_known_error=r.ground_truth_known_error)


    @staticmethod
    def issue_to_dict(issue):
        if issue is None: return None
        return {
            "id": str(issue.id), "external_key": issue.external_key, "external_id": issue.external_id,
            "summary": issue.summary, "description": issue.description, "resolution": issue.resolution,
            "error_code": issue.error_code, "status": issue.status, "priority": issue.priority,
            "issue_type": issue.issue_type, "environment": issue.environment,
            "parent_external_key": issue.parent_external_key,
            "resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else None,
            "source_created_at": issue.source_created_at.isoformat() if issue.source_created_at else None,
            "source_updated_at": issue.source_updated_at.isoformat() if issue.source_updated_at else None,
            "raw_payload": issue.raw_payload,
        }

    def create_import_batch(self, filename: str, total_rows: int):
        with self.session_factory.begin() as s:
            row=ImportBatchModel(filename=filename,total_rows=total_rows)
            s.add(row); s.flush(); s.expunge(row)
            return row

    def finish_import_batch(self, batch_id, valid_rows: int, invalid_rows: int, skipped_rows: int):
        with self.session_factory.begin() as s:
            row=s.get(ImportBatchModel,batch_id)
            row.valid_rows=valid_rows; row.invalid_rows=invalid_rows; row.skipped_rows=skipped_rows
            row.status="READY"; row.completed_at=now()

    def create_import_item(self, batch_id, jira_issue_id, row_number: int, status: str, error_message: str | None):
        with self.session_factory.begin() as s:
            row=ImportItemModel(import_batch_id=batch_id,jira_issue_id=jira_issue_id,row_number=row_number,status=status,error_message=error_message)
            s.add(row); s.flush(); return row.id

    def get_import_batch_summary(self, batch_id):
        with self.session_factory() as s:
            b=s.get(ImportBatchModel,batch_id)
            if not b: return None
            counts=dict(s.execute(select(ImportItemModel.status,func.count()).where(ImportItemModel.import_batch_id==batch_id).group_by(ImportItemModel.status)).all())
            return {"id":str(b.id),"filename":b.filename,"total_rows":b.total_rows,"valid_rows":b.valid_rows,
                    "invalid_rows":b.invalid_rows,"skipped_rows":b.skipped_rows,"status":b.status,"item_counts":counts}

    def get_next_import_item(self, batch_id):
        with self.session_factory() as s:
            row=s.scalar(select(ImportItemModel).where(ImportItemModel.import_batch_id==batch_id,ImportItemModel.status.in_(["PENDING","AWAITING_REVIEW"])).order_by(ImportItemModel.row_number).limit(1))
            return self._item_dict(row) if row else None

    def get_import_item(self, batch_id, item_id):
        with self.session_factory() as s:
            row=s.scalar(select(ImportItemModel).where(ImportItemModel.import_batch_id==batch_id,ImportItemModel.id==item_id))
            return self._item_dict(row) if row else None

    @staticmethod
    def _item_dict(row):
        return {"id":str(row.id),"batch_id":str(row.import_batch_id),"jira_issue_id":row.jira_issue_id,"row_number":row.row_number,
                "status":row.status,"workflow_id":str(row.workflow_id) if row.workflow_id else None,"error_message":row.error_message}

    def update_import_item(self, item_id, *, status=None, workflow_id=None):
        with self.session_factory.begin() as s:
            row=s.get(ImportItemModel,item_id)
            if not row: return
            if status is not None: row.status=status
            if workflow_id is not None: row.workflow_id=workflow_id

    def update_import_item_by_workflow(self, workflow_id, *, status):
        with self.session_factory.begin() as s:
            row=s.scalar(select(ImportItemModel).where(ImportItemModel.workflow_id==workflow_id))
            if row: row.status=status

    def create_known_error(self, item: KnownError):
        with self.session_factory.begin() as s: s.add(KnownErrorModel(id=item.id, title=item.title, current_version_id=item.current_version_id))
        return item

    def get_known_error(self, known_error_id: UUID):
        with self.session_factory() as s:
            r=s.get(KnownErrorModel, known_error_id)
            return None if not r else KnownError(id=r.id, title=r.title, current_version_id=r.current_version_id)

    def next_version_number(self, known_error_id: UUID) -> int:
        with self.session_factory() as s:
            n=s.scalar(select(func.max(ArticleVersionModel.version_number)).where(ArticleVersionModel.known_error_id==known_error_id))
            return (n or 0)+1

    def save_version(self, v: ArticleVersion):
        with self.session_factory.begin() as s:
            s.add(ArticleVersionModel(id=v.id, known_error_id=v.known_error_id, version_number=v.version_number,
                title=v.title, problem=v.problem, root_cause=v.root_cause, solution=v.solution, status=v.status.value,
                source_jira_issue_id=v.source_jira_issue_id, review_id=v.review_id,
                published_at=v.created_at if v.is_published else None))
            s.flush()
            s.execute(text("UPDATE article_version SET search_vector = setweight(to_tsvector('english', coalesce(title,'')), 'A') || setweight(to_tsvector('english', coalesce(problem,'')), 'A') || setweight(to_tsvector('english', coalesce(root_cause,'')), 'B') || setweight(to_tsvector('english', coalesce(solution,'')), 'B') WHERE id = :id"), {"id": v.id})
        return v

    def get_version(self, version_id: UUID):
        with self.session_factory() as s:
            r=s.get(ArticleVersionModel, version_id)
            if not r: return None
            return ArticleVersion(id=r.id, known_error_id=r.known_error_id, version_number=r.version_number,
                title=r.title, problem=r.problem, root_cause=r.root_cause, solution=r.solution,
                source_jira_issue_id=r.source_jira_issue_id, review_id=r.review_id, status=ArticleStatus(r.status), created_at=r.created_at)

    def save_chunks(self, chunks):
        with self.session_factory.begin() as s:
            s.add_all([ArticleChunkModel(id=c.id, article_version_id=c.article_version_id, chunk_index=c.chunk_index, section=c.section, content=c.content) for c in chunks])

    def list_published_versions(self):
        with self.session_factory() as s:
            rows=s.scalars(select(ArticleVersionModel).where(ArticleVersionModel.status==ArticleStatus.PUBLISHED.value)).all()
            return [ArticleVersion(id=r.id, known_error_id=r.known_error_id, version_number=r.version_number,title=r.title,problem=r.problem,root_cause=r.root_cause,solution=r.solution,source_jira_issue_id=r.source_jira_issue_id,review_id=r.review_id,status=ArticleStatus(r.status),created_at=r.created_at) for r in rows]

    def link_issue(self, issue_id, known_error_id, confidence):
        with self.session_factory.begin() as s:
            stmt=pg_insert(JiraKnownErrorLinkModel).values(jira_issue_id=issue_id, known_error_id=known_error_id, confidence=confidence).on_conflict_do_update(index_elements=["jira_issue_id","known_error_id"], set_={"confidence":confidence})
            s.execute(stmt)

    def set_current_version(self, known_error_id, version_id):
        with self.session_factory.begin() as s:
            r=s.get(KnownErrorModel, known_error_id); r.current_version_id=version_id

    def save_review(self, review):
        with self.session_factory.begin() as s:
            s.merge(HumanReviewModel(id=review.id, workflow_id=review.workflow_id, decision=review.decision.value, reviewer=review.reviewer, feedback=review.feedback, modified_content=review.modified_content))
        return review


class PostgresExactSearcher:
    def __init__(self, session_factory=SessionLocal): self.session_factory=session_factory
    def search(self, issue: JiraIssue, limit=10):
        if not issue.error_code: return []
        with self.session_factory() as s:
            rows=s.execute(text("""
                SELECT ke.id kid, av.id vid, av.title
                FROM article_version av JOIN known_error ke ON ke.current_version_id=av.id
                WHERE av.status='PUBLISHED' AND (av.problem ILIKE :q OR av.root_cause ILIKE :q OR av.solution ILIKE :q OR av.title ILIKE :q)
                LIMIT :lim"""), {"q":f"%{issue.error_code}%", "lim":limit}).all()
            return [RetrievalCandidate(known_error_id=r.kid, article_version_id=r.vid, title=r.title, exact_score=1.0) for r in rows]


class PostgresLexicalSearcher:
    def __init__(self, session_factory=SessionLocal): self.session_factory=session_factory
    def search(self, query: str, limit=10):
        with self.session_factory() as s:
            rows=s.execute(text("""
                SELECT ke.id kid, av.id vid, av.title,
                       ts_rank_cd(av.search_vector, websearch_to_tsquery('english', :q)) score
                FROM article_version av JOIN known_error ke ON ke.current_version_id=av.id
                WHERE av.status='PUBLISHED' AND av.search_vector @@ websearch_to_tsquery('english', :q)
                ORDER BY score DESC LIMIT :lim"""), {"q":query, "lim":limit}).all()
            return [RetrievalCandidate(known_error_id=r.kid, article_version_id=r.vid, title=r.title, lexical_score=float(r.score)) for r in rows]
