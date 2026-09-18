from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_play_keeps_background_running_and_advances_reviews(tmp_path, monkeypatch):
    import requests
    app_file = tmp_path / "app.py"
    app_file.write_text(Path("src/kedb/presentation/streamlit/app.py").read_text(encoding="utf-8"), encoding="utf-8")
    state = {"workflow_id": "wf", "status": "WAITING_FOR_REVIEW",
             "issue": {"external_key": "T-1", "summary": "Timeout", "description": "Failed", "resolution": "Retry"},
             "proposal": {"action": "CREATE", "title": "AI title", "problem": "AI problem", "solution": "AI solution"},
             "evaluation": {"reasoning": "Needs review"}}
    item = {"workflow_id": "wf", "external_key": "T-1", "summary": "Timeout", "status": "WAITING_FOR_REVIEW"}
    batch = {"batch_id": "batch", "source": "data/tickets_clean.csv", "status": "RUNNING",
             "processed": 1, "total": 5, "waiting": [item], "results": [item], "error": None}
    started = False
    calls = []
    class Response:
        ok = True
        def __init__(self, data): self.data = data
        def json(self): return self.data
    def request(method, url, **kwargs):
        nonlocal started
        calls.append((method, url))
        if url.endswith("/status"): return Response({"status": "ok"})
        if url.endswith("/play"):
            started = True
            return Response({"batch_id": "batch"})
        if url.endswith("/current"): return Response(batch if started else None)
        if url.endswith("/batches/batch"): return Response(batch)
        if url.endswith("/workflows/wf"): return Response(state)
        if url.endswith("/review"):
            batch["waiting"] = []
            return Response({**state, "status": "REJECTED"})
        raise AssertionError(url)
    monkeypatch.setattr(requests, "request", request)
    app = AppTest.from_file(str(app_file)).run()
    assert not app.exception
    next(button for button in app.button if button.label == "Play").click().run()
    assert not app.exception
    assert any(metric.value == "RUNNING" for metric in app.metric)
    assert not any(control.label in {"Action", "Root cause", "Ingest only"}
                   for control in [*app.selectbox, *app.text_area, *app.button])
    next(control for control in app.selectbox if control.label == "Review decision").select("REJECT")
    next(button for button in app.button if button.label == "Submit decision").click().run()
    assert not app.exception
    assert batch["status"] == "RUNNING"
    assert not any(url.endswith("/pause") or url.endswith("/api/publications") for _, url in calls)
