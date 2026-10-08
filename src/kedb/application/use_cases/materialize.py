"""Retryable publication outbox delivery to Unity Catalog."""
from __future__ import annotations

import hashlib
import logging
from threading import Event, Lock, Thread
from uuid import UUID

from sqlalchemy import select

from kedb.application.incidents import extract_error_code
from kedb.application.use_cases.publish import semantic_chunks
from kedb.infrastructure.lakebase.models import PublicationOutboxRow
from kedb.infrastructure.lakebase.repositories import SqlRepositories

logger = logging.getLogger(__name__)


def chunk_rows(article, *, is_current):
    return [dict(chunk_id=str(chunk.id), known_error_id=str(article.known_error_id),
                 article_version_id=str(article.id), version_number=article.version_number,
                 title=article.title, section=chunk.section, content=chunk.content,
                 error_codes=list(filter(None, [extract_error_code(article.problem, article.solution)])),
                 source_jira_issue_id=str(article.source_jira_issue_id) if article.source_jira_issue_id else None,
                 review_id=str(article.review_id), status="PUBLISHED", is_current=is_current,
                 published_at=article.published_at.isoformat() if article.published_at else None,
                 content_hash=hashlib.sha256(chunk.content.encode()).hexdigest())
            for chunk in semantic_chunks(article)]


class MaterializePublications:
    def __init__(self, database, sink):
        self.database = database
        self.sink = sink
        self.lock = Lock()
        self.last_error = None
        self.last_count = 0

    def run_once(self, limit=100):
        if not self.lock.acquire(blocking=False):
            return 0
        event_ids = []
        try:
            with self.database.sessions() as session:
                events = session.scalars(select(PublicationOutboxRow).where(
                    PublicationOutboxRow.processed.is_(False)).order_by(
                    PublicationOutboxRow.created_at, PublicationOutboxRow.id).limit(limit)).all()
                event_ids = [event.id for event in events]
                if not events:
                    return 0
                repo = SqlRepositories(session)
                articles, current = {}, {}
                for event in events:
                    article = repo.get_version(UUID(event.article_version_id))
                    if article is None or not article.can_embed:
                        raise ValueError("Publication event references a missing or unapproved article")
                    articles[article.id] = article
                    known_error = repo.get_known_error(article.known_error_id)
                    if known_error is None or known_error.current_version_id is None:
                        raise ValueError("Published article has no current version")
                    current[article.known_error_id] = known_error.current_version_id
                    latest = repo.get_version(known_error.current_version_id)
                    if latest is None or not latest.can_embed:
                        raise ValueError("Current article version is missing or unapproved")
                    # Always include the current version, even when replaying an old event.
                    articles[latest.id] = latest
            rows = [row for article in articles.values() for row in chunk_rows(
                article, is_current=current[article.known_error_id] == article.id)]
            self.sink.write(rows)
            self.sink.sync()
            # A failed write or sync leaves every event pending for an idempotent retry.
            with self.database.sessions.begin() as session:
                for event_id in event_ids:
                    event = session.get(PublicationOutboxRow, event_id)
                    event.processed = True
                    event.attempts += 1
            self.last_count = len(event_ids)
            self.last_error = None
            return len(event_ids)
        except Exception as exc:
            self.last_error = str(exc)
            if event_ids:
                with self.database.sessions.begin() as session:
                    for event_id in event_ids:
                        session.get(PublicationOutboxRow, event_id).attempts += 1
            raise
        finally:
            self.lock.release()


class MaterializationWorker:
    def __init__(self, materializer, interval=30):
        self.materializer = materializer
        self.interval = interval
        self.stopping = Event()
        self.thread = Thread(target=self.run, name="article-chunks", daemon=True)

    def start(self): self.thread.start()

    def stop(self):
        self.stopping.set()
        self.thread.join(timeout=5)

    def run(self):
        while not self.stopping.is_set():
            try:
                count = self.materializer.run_once()
                if count:
                    continue
            except Exception:
                logger.exception("Article chunk materialization failed; retrying later")
            self.stopping.wait(self.interval)
