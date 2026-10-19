from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from kedb.application.dto import KnowledgeProposal
from kedb.application.use_cases.publish import PublishApprovedKnowledge, semantic_chunks
from kedb.application.use_cases.materialize import MaterializePublications
from kedb.domain import HumanReview, ReviewDecision
from kedb.infrastructure.lakebase import Database, SqlRepositories
from kedb.infrastructure.lakebase.models import PublicationOutboxRow


class Sink:
    def __init__(self):
        self.rows = {}
        self.fail_sync = False
        self.syncs = 0

    def write(self, rows):
        keys = {row["known_error_id"] for row in rows}
        for row in self.rows.values():
            if row["known_error_id"] in keys:
                row["is_current"] = False
        self.rows.update({row["chunk_id"]: dict(row) for row in rows})

    def sync(self):
        self.syncs += 1
        if self.fail_sync:
            raise RuntimeError("sync unavailable")


def setup(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path / 'materialization.db'}")
    db.create_all()
    return db


def publish(db, *, target=None, solution="fix"):
    with db.sessions.begin() as session:
        return PublishApprovedKnowledge(SqlRepositories(session)).execute(
            proposal=KnowledgeProposal(action="UPDATE" if target else "CREATE",
                target_known_error_id=target, title="Timeout", problem="ORA-12170 timeout",
                root_cause="", solution=solution),
            review=HumanReview(workflow_id=uuid4(), decision=ReviewDecision.APPROVE, reviewer="test"))


def test_pending_approvals_become_chunks_and_retries_do_not_duplicate(tmp_path):
    db = setup(tmp_path)
    article = publish(db)
    assert [c.id for c in semantic_chunks(article)] == [c.id for c in semantic_chunks(article)]
    assert len(semantic_chunks(article)) == 2  # Empty sections do not produce empty embeddings.
    sink = Sink()
    materializer = MaterializePublications(db, sink)
    sink.fail_sync = True
    with pytest.raises(RuntimeError): materializer.run_once()
    with db.sessions() as session:
        event = session.scalar(select(PublicationOutboxRow))
        assert not event.processed and event.attempts == 1
    assert len(sink.rows) == 2
    sink.fail_sync = False
    assert materializer.run_once() == 1
    assert materializer.run_once() == 0
    assert len(sink.rows) == 2
    assert materializer.last_error is None
    assert all(row["error_codes"] == ["ORA-12170"] for row in sink.rows.values())
    with db.sessions() as session:
        event = session.scalar(select(PublicationOutboxRow))
        assert event.processed and event.attempts == 2


def test_replaying_older_event_keeps_current_article_searchable(tmp_path):
    db = setup(tmp_path)
    first = publish(db)
    second = publish(db, target=first.known_error_id, solution="better fix")
    sink = Sink()
    materializer = MaterializePublications(db, sink)
    assert materializer.run_once(limit=1) == 1
    assert {row["article_version_id"] for row in sink.rows.values() if row["is_current"]} == {str(second.id)}
    assert materializer.run_once(limit=1) == 1
    assert len(sink.rows) == 4
    assert {row["article_version_id"] for row in sink.rows.values() if row["is_current"]} == {str(second.id)}


def test_sql_sink_binds_content_and_uses_single_atomic_merge():
    from kedb.infrastructure.delta.sql_chunks import SqlChunkSink
    calls = []
    def execute_statement(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status=SimpleNamespace(state=SimpleNamespace(value="SUCCEEDED")))
    workspace = SimpleNamespace(statement_execution=SimpleNamespace(execute_statement=execute_statement))
    sink = SqlChunkSink(warehouse_id="wh", table="catalog.schema.chunks", workspace=workspace)
    content = "quoted ' content; not SQL"
    sink.write([{"known_error_id": "ke", "content": content}])
    assert len(calls) == 1
    assert content not in calls[0]["statement"]
    assert content in calls[0]["parameters"][0].value
    assert "WHEN NOT MATCHED BY SOURCE" in calls[0]["statement"]
    with pytest.raises(ValueError):
        SqlChunkSink(warehouse_id="wh", table="bad; DROP TABLE t")

@pytest.mark.parametrize("missing_event", [False, True])
def test_rebuild_recovers_missing_chunks_without_republishing(tmp_path, missing_event):
    from sqlalchemy import func, delete
    from kedb.infrastructure.lakebase.models import ArticleVersionRow
    db = setup(tmp_path)
    article = publish(db)
    sink = Sink()
    materializer = MaterializePublications(db, sink)
    assert materializer.run_once() == 1
    sink.rows.clear()
    if missing_event:
        with db.sessions.begin() as session:
            session.execute(delete(PublicationOutboxRow))
    assert materializer.requeue_current(article.id) == 1
    assert materializer.run_once() == 1
    assert len(sink.rows) == 2
    assert materializer.run_once() == 0
    with db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ArticleVersionRow)) == 1


def test_rebuild_reports_absent_article(tmp_path):
    materializer = MaterializePublications(setup(tmp_path), Sink())
    with pytest.raises(ValueError, match="No current published articles"):
        materializer.requeue_current(uuid4())


def test_worker_wakes_without_waiting_for_poll_interval():
    from threading import Event
    from kedb.application.use_cases.materialize import MaterializationWorker
    first = Event()
    second = Event()
    class Materializer:
        calls = 0
        def run_once(self):
            self.calls += 1
            (first if self.calls == 1 else second).set()
            return 0
    worker = MaterializationWorker(Materializer(), interval=3600)
    worker.start()
    try:
        assert first.wait(2)
        worker.wake()
        assert second.wait(2)
    finally:
        worker.stop()
    assert not worker.thread.is_alive()
