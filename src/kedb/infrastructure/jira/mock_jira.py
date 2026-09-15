from __future__ import annotations
from uuid import UUID
from kedb.domain.entities import JiraIssue


class MockJiraGateway:
    """MVP Jira adapter backed by the authoritative local repository."""
    def __init__(self, repo): self.repo=repo
    def get_issue(self, issue_id: UUID) -> JiraIssue | None: return self.repo.get_issue(issue_id)
    def ingest(self, issue: JiraIssue) -> JiraIssue: return self.repo.save_issue(issue)
