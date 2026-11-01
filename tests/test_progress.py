from kedb.application.workflows.progress import WorkflowProgress
from kedb.application.workflows.curator import CuratorWorkflow
import pytest


def test_parallel_progress_retains_both_nodes_and_clears_on_retry():
    progress = WorkflowProgress()
    progress.update("wf", "exact_search", "started")
    progress.update("wf", "hybrid_search", "started")
    assert set(progress.snapshot()["wf"]["active_steps"]) == {"exact_search", "hybrid_search"}
    progress.update("wf", "exact_search", "completed")
    assert progress.snapshot()["wf"]["active_steps"] == ["hybrid_search"]
    progress.update("wf", "hybrid_search", "failed")
    assert progress.snapshot()["wf"]["failed_steps"] == ["hybrid_search"]
    progress.update("wf", "retrieve_jira_fields", "started")
    assert progress.snapshot()["wf"]["failed_steps"] == []
    progress.clear("wf")
    assert progress.snapshot() == {}


def test_node_failure_records_step_and_propagates_original_error():
    progress = WorkflowProgress()
    workflow = CuratorWorkflow(None, None, progress=progress.update)
    def fail(state):
        raise ValueError("embedding failed")
    with pytest.raises(ValueError, match="embedding failed"):
        workflow.tracked_node("score_candidates", fail)({"workflow_id": "wf"})
    assert progress.snapshot()["wf"]["failed_steps"] == ["score_candidates"]


def test_progress_failure_does_not_stop_business_node():
    def broken(*args):
        raise RuntimeError("progress unavailable")
    workflow = CuratorWorkflow(None, None, progress=broken)
    assert workflow.tracked_node("test", lambda state: {"ok": True})({}) == {"ok": True}
