from uuid import UUID
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from kedb.domain import JiraIssue, KnownError, ArticleVersion, ArticleStatus, HumanReview, ReviewDecision
from .models import JiraIssueRow, KnownErrorRow, ArticleVersionRow, HumanReviewRow, PublicationOutboxRow, PublicationClaimRow

class SqlRepositories:
    def __init__(self, session): self.s = session

    def add_jira(self, x: JiraIssue):
        self.s.add(JiraIssueRow(id=str(x.id), external_key=x.external_key, summary=x.summary, description=x.description, resolution=x.resolution, error_code=x.error_code))
        self.s.flush()
    def get_jira_by_external_key(self, external_key: str):
        r=self.s.scalars(select(JiraIssueRow).where(JiraIssueRow.external_key==external_key)).first()
        return None if not r else JiraIssue(id=UUID(r.id), external_key=r.external_key, summary=r.summary, description=r.description, resolution=r.resolution, error_code=r.error_code)
    def get_jira(self, id: UUID):
        r=self.s.get(JiraIssueRow,str(id));
        return None if not r else JiraIssue(id=UUID(r.id), external_key=r.external_key, summary=r.summary, description=r.description, resolution=r.resolution, error_code=r.error_code)
    def add_known_error(self, x: KnownError):
        self.s.add(KnownErrorRow(id=str(x.id), title=x.title, current_version_id=str(x.current_version_id) if x.current_version_id else None))
        self.s.flush()
    def get_known_error(self, id: UUID):
        r=self.s.get(KnownErrorRow,str(id));
        return None if not r else KnownError(id=UUID(r.id), title=r.title, current_version_id=UUID(r.current_version_id) if r.current_version_id else None)
    def list_known_errors(self):
        return [KnownError(id=UUID(r.id), title=r.title, current_version_id=UUID(r.current_version_id) if r.current_version_id else None) for r in self.s.scalars(select(KnownErrorRow)).all()]
    def set_current(self, known_error_id: UUID, version_id: UUID):
        self.s.flush()
        r=self.s.get(KnownErrorRow,str(known_error_id))
        if r is None:
            raise LookupError(f'KnownError {known_error_id} not found')
        r.current_version_id=str(version_id)
        self.s.flush()
    def add_version(self, x: ArticleVersion):
        self.s.add(ArticleVersionRow(id=str(x.id), known_error_id=str(x.known_error_id), version_number=x.version_number, title=x.title, problem=x.problem, root_cause=x.root_cause, solution=x.solution, status=x.status.value, source_jira_issue_id=str(x.source_jira_issue_id) if x.source_jira_issue_id else None, review_id=str(x.review_id) if x.review_id else None, published_at=x.published_at))
        self.s.flush()
    def get_version(self, id: UUID):
        r=self.s.get(ArticleVersionRow,str(id));
        return None if not r else self._version(r)
    def list_versions(self, known_error_id: UUID):
        rows=self.s.scalars(select(ArticleVersionRow).where(ArticleVersionRow.known_error_id==str(known_error_id)).order_by(ArticleVersionRow.version_number)).all()
        return [self._version(r) for r in rows]
    def _version(self,r):
        return ArticleVersion(id=UUID(r.id),known_error_id=UUID(r.known_error_id),version_number=r.version_number,title=r.title,problem=r.problem,root_cause=r.root_cause,solution=r.solution,status=ArticleStatus(r.status),source_jira_issue_id=UUID(r.source_jira_issue_id) if r.source_jira_issue_id else None,review_id=UUID(r.review_id) if r.review_id else None,published_at=r.published_at)
    def add_review(self, x: HumanReview):
        self.s.add(HumanReviewRow(id=str(x.id),workflow_id=str(x.workflow_id),decision=x.decision.value,reviewer=x.reviewer,feedback=x.feedback,modified_content=x.modified_content,created_at=x.created_at))
        self.s.flush()
    def latest_review(self, workflow_id: UUID):
        r=self.s.scalars(select(HumanReviewRow).where(HumanReviewRow.workflow_id==str(workflow_id)).order_by(HumanReviewRow.created_at.desc())).first()
        return None if not r else HumanReview(id=UUID(r.id),workflow_id=UUID(r.workflow_id),decision=ReviewDecision(r.decision),reviewer=r.reviewer,feedback=r.feedback,modified_content=r.modified_content,created_at=r.created_at)
    def add_outbox(self, article: ArticleVersion):
        self.s.add(PublicationOutboxRow(article_version_id=str(article.id),payload={'known_error_id':str(article.known_error_id),'article_version_id':str(article.id)}))

    def reserve_publication(self, keys, version_id):
        # Sorted acquisition prevents deadlocks when requests share several keys.
        try:
            with self.s.begin_nested():
                for key in sorted(keys):
                    self.s.add(PublicationClaimRow(key=key, article_version_id=str(version_id)))
                    self.s.flush()
        except IntegrityError:
            for key in keys:
                claim = self.s.get(PublicationClaimRow, key)
                if claim:
                    return self.get_version(UUID(claim.article_version_id))
            raise
        return None

    def find_publication(self, *, workflow_id, jira_issue_id, fingerprint):
        # Also protects records created before publication claims were introduced.
        from kedb.application.use_cases.publish import content_fingerprint
        identity_keys = [f"workflow:{workflow_id}", f"content:{fingerprint}"]
        if jira_issue_id:
            identity_keys.insert(1, f"ticket:{jira_issue_id}")
        for key in identity_keys:
            claim = self.s.get(PublicationClaimRow, key)
            if claim:
                version = self.get_version(UUID(claim.article_version_id))
                if version is None:
                    raise ValueError("Publication claim references a missing article")
                return version
        rows = self.s.scalars(select(ArticleVersionRow)).all()
        for row in rows:
            review = self.s.get(HumanReviewRow, row.review_id) if row.review_id else None
            if ((review and review.workflow_id == str(workflow_id))
                    or (jira_issue_id and row.source_jira_issue_id == str(jira_issue_id))
                    or content_fingerprint(row.problem, row.root_cause, row.solution) == fingerprint):
                return self._version(row)
        return None

    def lock_known_error(self, known_error_id):
        self.s.execute(select(KnownErrorRow).where(
            KnownErrorRow.id == str(known_error_id)).with_for_update())

    def bind_publication_identity(self, workflow_id, jira_issue_id, version_id):
        keys = [f"workflow:{workflow_id}"]
        if jira_issue_id:
            keys.append(f"ticket:{jira_issue_id}")
        for key in sorted(keys):
            if self.s.get(PublicationClaimRow, key):
                continue
            try:
                with self.s.begin_nested():
                    self.s.add(PublicationClaimRow(key=key, article_version_id=str(version_id)))
                    self.s.flush()
            except IntegrityError:
                if not self.s.get(PublicationClaimRow, key):
                    raise
