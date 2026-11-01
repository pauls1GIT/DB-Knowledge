"""Lightweight live progress for the app's single API process.

Final states remain in database checkpoints. Live node updates do not add a
database round trip to every graph node and never mutate resumable state.
"""
from collections import OrderedDict
from datetime import datetime, timezone
from threading import Lock


class WorkflowProgress:
    def __init__(self, limit=1024):
        self.limit = limit
        self.lock = Lock()
        self.rows = OrderedDict()

    def update(self, workflow_id, node, event):
        if not workflow_id:
            return
        with self.lock:
            if node == "retrieve_jira_fields" and event == "started":
                self.rows.pop(workflow_id, None)
            row = self.rows.setdefault(workflow_id, {"active_steps": [], "failed_steps": []})
            if event == "started":
                if node not in row["active_steps"]:
                    row["active_steps"].append(node)
                row["failed_steps"] = [step for step in row["failed_steps"] if step != node]
            else:
                row["active_steps"] = [step for step in row["active_steps"] if step != node]
                if event == "failed":
                    row["failed_steps"].append(node)
            row["last_step"] = node
            row["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.rows.move_to_end(workflow_id)
            while len(self.rows) > self.limit:
                self.rows.popitem(last=False)

    def snapshot(self):
        with self.lock:
            return {key: {**row, "active_steps": list(row["active_steps"]),
                          "failed_steps": list(row["failed_steps"])}
                    for key, row in self.rows.items()}

    def clear(self, workflow_id):
        with self.lock:
            self.rows.pop(workflow_id, None)
