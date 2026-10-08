from fastapi.testclient import TestClient

from kedb.presentation.api import app as api_module
from kedb.infrastructure.lakebase import Database


def test_configured_warehouse_with_database_failure_reports_real_error(monkeypatch):
    monkeypatch.setattr(api_module.settings, "databricks_warehouse_id", "warehouse-id")
    monkeypatch.setattr(api_module, "startup_error", "ConnectionError: database unavailable")
    monkeypatch.setattr(api_module, "materializer", None)
    # Do not run lifespan: inspect the status after a failed startup.
    response = TestClient(api_module.app).get("/api/system/status")
    assert response.status_code == 200
    status = response.json()
    assert status["database_ready"] is False
    chunks = status["article_chunks"]
    assert chunks["warehouse_configured"] is True
    assert chunks["worker_running"] is False
    assert chunks["configuration_required"] is None
    assert "database unavailable" in chunks["last_error"]


def test_missing_warehouse_with_healthy_database_requests_configuration(tmp_path, monkeypatch):
    db = Database(f"sqlite+pysqlite:///{tmp_path / 'status.db'}")
    db.create_all()
    monkeypatch.setattr(api_module, "db", db)
    monkeypatch.setattr(api_module.settings, "databricks_warehouse_id", "")
    monkeypatch.setattr(api_module, "startup_error", None)
    monkeypatch.setattr(api_module, "materializer", None)
    chunks = TestClient(api_module.app).get("/api/system/status").json()["article_chunks"]
    assert chunks["warehouse_configured"] is False
    assert "DATABRICKS_WAREHOUSE_ID" in chunks["configuration_required"]
    assert chunks["last_error"] is None
