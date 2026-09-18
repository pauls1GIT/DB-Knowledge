from threading import Event
from uuid import uuid4

from kedb.application.workflows.batch import BatchWorker
from kedb.infrastructure.lakebase import Database
from kedb.infrastructure.lakebase.models import CsvBatchRow, WorkflowCheckpointRow


def setup_batch(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path / 'batch.db'}")
    db.create_all()
    items = [{"external_key": f"T-{i}", "summary": "test"} for i in range(3)]
    with db.sessions.begin() as session:
        session.add(CsvBatchRow(id="batch", source="test", items=items, position=0,
                                results=[], status="RUNNING"))
    return db


def test_worker_continues_past_review_and_can_pause_resume(tmp_path):
    db = setup_batch(tmp_path)
    def process(item):
        return {"workflow_id": str(uuid4()), "status": "WAITING_FOR_REVIEW"}
    worker = BatchWorker(db, process)
    assert worker.process_next()
    with db.sessions.begin() as session:
        row = session.get(CsvBatchRow, "batch")
        assert row.position == 1
        assert row.status == "RUNNING"
        row.status = "PAUSED"
    assert not worker.process_next()
    with db.sessions.begin() as session:
        session.get(CsvBatchRow, "batch").status = "RUNNING"
    # A fresh worker resumes saved progress, without reprocessing the first ticket.
    worker = BatchWorker(db, process)
    assert worker.process_next()
    assert worker.process_next()
    assert not worker.process_next()
    with db.sessions() as session:
        row = session.get(CsvBatchRow, "batch")
        assert row.position == 3
        assert row.status == "COMPLETE"
        assert len(row.results) == 3


def test_worker_failure_preserves_position_for_retry(tmp_path):
    db = setup_batch(tmp_path)
    def fail(_): raise ValueError("model unavailable")
    worker = BatchWorker(db, fail)
    worker.process_next()
    with db.sessions() as session:
        row = session.get(CsvBatchRow, "batch")
        assert row.status == "ERROR"
        assert row.position == 0
        assert row.error == "model unavailable"
    assert not worker.process_next()


def test_review_is_available_while_next_ticket_runs_in_background(tmp_path):
    db = setup_batch(tmp_path)
    second_started, release_second = Event(), Event()
    first_id = str(uuid4())
    def process(item):
        if item["external_key"] == "T-0":
            with db.sessions.begin() as session:
                session.add(WorkflowCheckpointRow(workflow_id=first_id, status="WAITING_FOR_REVIEW",
                    current_step="review", state={"status": "WAITING_FOR_REVIEW"}))
            return {"workflow_id": first_id, "status": "WAITING_FOR_REVIEW"}
        second_started.set()
        assert release_second.wait(5)
        return {"workflow_id": str(uuid4()), "status": "REJECTED"}
    worker = BatchWorker(db, process)
    worker.start()
    try:
        assert second_started.wait(5)
        with db.sessions.begin() as session:
            row = session.get(CsvBatchRow, "batch")
            assert row.position == 1
            assert row.results[0]["workflow_id"] == first_id
            session.get(WorkflowCheckpointRow, first_id).status = "REJECTED"
    finally:
        release_second.set()
        worker.stop()
