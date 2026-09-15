from __future__ import annotations
from kedb.config import settings
from kedb.domain.entities import JiraIssue, RetrievalCandidate


class HybridRetrievalCoordinator:
    def __init__(self, exact, lexical, vector, embeddings):
        self.exact=exact; self.lexical=lexical; self.vector=vector; self.embeddings=embeddings
    def search(self, issue: JiraIssue, query: str | None=None, limit: int=5):
        q=query or f"{issue.summary} {issue.description} {issue.error_code or ''}".strip()
        buckets=[self.exact.search(issue,limit*2), self.lexical.search(q,limit*2), self.vector.search(self.embeddings.embed(q),limit*2)]
        merged={}
        for bucket in buckets:
            for c in bucket:
                key=(c.known_error_id,c.article_version_id)
                target=merged.setdefault(key, RetrievalCandidate(known_error_id=c.known_error_id, article_version_id=c.article_version_id, title=c.title))
                target.exact_score=max(target.exact_score,c.exact_score)
                target.lexical_score=max(target.lexical_score,c.lexical_score)
                target.vector_score=max(target.vector_score,c.vector_score)
        for c in merged.values():
            c.final_score=(settings.retrieval_exact_weight*c.exact_score + settings.retrieval_lexical_weight*c.lexical_score + settings.retrieval_vector_weight*c.vector_score)
        ranked=sorted(merged.values(),key=lambda x:x.final_score,reverse=True)[:limit]
        for i,c in enumerate(ranked,1): c.rank=i
        return ranked
