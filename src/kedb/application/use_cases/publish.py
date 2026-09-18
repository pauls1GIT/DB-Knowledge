import hashlib
import json
import unicodedata
from uuid import UUID, uuid4
from kedb.domain import KnownError, HumanReview, ReviewDecision, create_new_version, ArticleChunk
from kedb.application.dto import KnowledgeProposal

class PublishApprovedKnowledge:
    def __init__(self, repos):
        self.repos = repos

    def execute(self, *, proposal: KnowledgeProposal, review: HumanReview, jira_issue_id: UUID | None = None):
        if review.decision != ReviewDecision.APPROVE:
            raise ValueError('Cannot publish without human approval')

        content = {
            'title': proposal.title, 'problem': proposal.problem,
            'root_cause': proposal.root_cause, 'solution': proposal.solution,
            'source_jira_issue_id': jira_issue_id,
        }
        fingerprint = content_fingerprint(proposal.problem, proposal.root_cause, proposal.solution)
        previous = self.repos.find_publication(
            workflow_id=review.workflow_id, jira_issue_id=jira_issue_id, fingerprint=fingerprint)
        if previous:
            self.repos.bind_publication_identity(review.workflow_id, jira_issue_id, previous.id)
            return previous
        version_id = uuid4()
        keys = [f"workflow:{review.workflow_id}", f"content:{fingerprint}"]
        if jira_issue_id:
            keys.append(f"ticket:{jira_issue_id}")
        previous = self.repos.reserve_publication(keys, version_id)
        if previous:
            self.repos.bind_publication_identity(review.workflow_id, jira_issue_id, previous.id)
            return previous

        if proposal.action == 'CREATE':
            ke = KnownError(title=content['title'])
            self.repos.add_known_error(ke)
            existing=[]
        else:
            if proposal.target_known_error_id is None:
                raise ValueError('UPDATE requires target_known_error_id')
            self.repos.lock_known_error(proposal.target_known_error_id)
            ke = self.repos.get_known_error(proposal.target_known_error_id)
            if ke is None: raise LookupError('KnownError not found')
            existing=self.repos.list_versions(ke.id)

        draft=create_new_version(existing, ke.id, id=version_id, **content)
        published=draft.publish(review)
        # Persist parent/review rows before the ArticleVersion foreign keys are flushed.
        self.repos.add_review(review)
        self.repos.add_version(published)
        self.repos.set_current(ke.id, published.id)
        self.repos.add_outbox(published)
        return published


def semantic_chunks(article):
    if not article.can_embed:
        raise ValueError('Only approved/published articles may be chunked for production search')
    data=[('problem', f'{article.title}\n{article.problem}'),('root_cause',article.root_cause),('solution',article.solution)]
    return [ArticleChunk(known_error_id=article.known_error_id, article_version_id=article.id, chunk_index=i, section=s, content=c) for i,(s,c) in enumerate(data)]


def content_fingerprint(problem, root_cause, solution):
    normalized = [" ".join(unicodedata.normalize("NFKC", text).casefold().split())
                  for text in (problem, root_cause, solution)]
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False).encode()).hexdigest()
