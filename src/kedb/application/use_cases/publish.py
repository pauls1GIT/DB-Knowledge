from __future__ import annotations
from dataclasses import replace
from uuid import UUID
from kedb.application.dto import KnowledgeProposal
from kedb.domain.entities import ArticleChunk, ArticleStatus, ArticleVersion, HumanReview, KnownError
from kedb.domain.rules import validate_review_for_publication, ensure_can_embed


class PublishApprovedKnowledge:
    def __init__(self, repo, embeddings, vector_store): self.repo=repo; self.embeddings=embeddings; self.vector_store=vector_store
    def execute(self, issue_id: UUID, proposal: KnowledgeProposal, review: HumanReview, confidence: float=1.0):
        validate_review_for_publication(review.decision)
        if proposal.action=="CREATE":
            ke=self.repo.create_known_error(KnownError(title=proposal.title))
        else:
            if proposal.target_known_error_id is None: raise ValueError("UPDATE requires target_known_error_id")
            ke=self.repo.get_known_error(proposal.target_known_error_id)
            if ke is None: raise ValueError("Known error not found")
        v=ArticleVersion(known_error_id=ke.id, version_number=self.repo.next_version_number(ke.id), title=proposal.title, problem=proposal.problem, root_cause=proposal.root_cause, solution=proposal.solution, source_jira_issue_id=issue_id, review_id=review.id, status=ArticleStatus.PUBLISHED)
        ensure_can_embed(v)
        self.repo.save_review(review); self.repo.save_version(v); self.repo.set_current_version(ke.id,v.id); self.repo.link_issue(issue_id,ke.id,confidence)
        chunks=[ArticleChunk(article_version_id=v.id,chunk_index=0,section="problem",content=v.problem),ArticleChunk(article_version_id=v.id,chunk_index=1,section="root_cause",content=v.root_cause),ArticleChunk(article_version_id=v.id,chunk_index=2,section="solution",content=v.solution)]
        self.repo.save_chunks(chunks)
        vectors=self.embeddings.embed_batch([c.content for c in chunks])
        md=[{"known_error_id":str(ke.id),"article_version_id":str(v.id),"title":v.title,"section":c.section} for c in chunks]
        self.vector_store.upsert(chunks,vectors,md)
        return {"known_error_id":str(ke.id),"article_version_id":str(v.id),"version_number":v.version_number}
