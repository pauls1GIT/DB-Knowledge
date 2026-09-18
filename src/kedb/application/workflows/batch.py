"""Persistent CSV progress with one background worker per API process."""
from __future__ import annotations

import logging
from threading import Event, Thread

from sqlalchemy import select

from kedb.infrastructure.lakebase.models import CsvBatchRow

logger = logging.getLogger(__name__)


class BatchWorker:
    def __init__(self, database, process):
        self.database = database
        self.process = process
        self.stopping = Event()
        self.thread = Thread(target=self.run, name="csv-curator", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.thread.join(timeout=5)

    def run(self):
        while not self.stopping.is_set():
            try:
                if self.process_next():
                    continue
            except Exception:
                logger.exception("Background CSV worker failed; will retry")
            self.stopping.wait(1)

    def process_next(self):
        with self.database.sessions() as session:
            batch = session.scalars(select(CsvBatchRow).where(
                CsvBatchRow.status == "RUNNING").order_by(CsvBatchRow.created_at)).first()
            if batch is None:
                return False
            batch_id, position = batch.id, batch.position
            if position >= len(batch.items):
                return False
            item = batch.items[position]
        try:
            state = self.process(item)
        except Exception as exc:
            logger.exception("CSV ticket processing failed")
            with self.database.sessions.begin() as session:
                batch = session.get(CsvBatchRow, batch_id)
                batch.status = "ERROR"
                batch.error = str(getattr(exc, "detail", None) or exc)
            return True
        # WAITING_FOR_REVIEW is a prepared result, never a reason to stop the worker.
        with self.database.sessions.begin() as session:
            batch = session.get(CsvBatchRow, batch_id)
            batch.results = [*batch.results, {
                "workflow_id": state["workflow_id"], "external_key": item["external_key"],
                "summary": item["summary"], "status": state["status"],
            }]
            batch.position = position + 1
            if batch.position == len(batch.items):
                batch.status = "COMPLETE"
            batch.error = None
        return True
