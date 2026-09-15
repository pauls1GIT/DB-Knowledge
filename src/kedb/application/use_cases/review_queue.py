from __future__ import annotations
from uuid import UUID, uuid4


class ReviewQueue:
    def __init__(self, repo, graph):
        self.repo = repo
        self.graph = graph

    def next_item(self, batch_id: UUID) -> dict | None:
        item = self.repo.get_next_import_item(batch_id)
        if not item:
            return None
        issue = self.repo.get_issue(item["jira_issue_id"]) if item.get("jira_issue_id") else None
        return {**item, "issue": self.repo.issue_to_dict(issue) if issue else None}

    def process_item(self, batch_id: UUID, item_id: UUID) -> dict:
        item = self.repo.get_import_item(batch_id, item_id)
        if not item or not item.get("jira_issue_id"):
            raise ValueError("Import item not found or has no Jira issue")
        workflow_id = uuid4()
        self.repo.update_import_item(item_id, status="PROCESSING", workflow_id=workflow_id)
        cfg = {"configurable": {"thread_id": str(workflow_id)}}
        result = self.graph.invoke(
            {"workflow_id": str(workflow_id), "issue_id": str(item["jira_issue_id"]), "revision_count": 0},
            config=cfg,
        )
        status = "AWAITING_REVIEW" if "__interrupt__" in result else "COMPLETED"
        self.repo.update_import_item(item_id, status=status, workflow_id=workflow_id)
        return {
            "batch_id": str(batch_id), "item_id": str(item_id), "workflow_id": str(workflow_id),
            "status": status, "proposal": result.get("proposal"), "evaluation": result.get("evaluation"),
            "candidates": result.get("candidates", []),
        }

    def sync_review_result(self, workflow_id: UUID, result: dict) -> None:
        if "__interrupt__" in result:
            status = "AWAITING_REVIEW"
        else:
            decision=(result.get("review") or {}).get("decision")
            status = "PUBLISHED" if decision == "APPROVE" else "REJECTED"
        self.repo.update_import_item_by_workflow(workflow_id, status=status)

    def skip_item(self, batch_id: UUID, item_id: UUID) -> dict:
        item=self.repo.get_import_item(batch_id,item_id)
        if not item:
            raise ValueError("Import item not found")
        if item.get("status") in {"PUBLISHED","REJECTED","SKIPPED"}:
            raise ValueError(f"Import item is already terminal: {item.get('status')}")
        self.repo.update_import_item(item_id,status="SKIPPED")
        return {"batch_id":str(batch_id),"item_id":str(item_id),"status":"SKIPPED"}
