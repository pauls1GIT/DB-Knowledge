from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

from kedb import observability
from kedb.config import Settings
from kedb.application.workflows.curator import CuratorWorkflow


@pytest.fixture
def sdk(monkeypatch):
    events = []

    @contextmanager
    def workflow(**kwargs):
        events.append(kwargs)
        yield

    fake = SimpleNamespace(
        init=Mock(), shutdown=Mock(), flush=Mock(return_value=True),
        workflow=workflow, span=workflow,
    )
    monkeypatch.setattr(observability, "_sdk", None)
    monkeypatch.setitem(sys.modules, "ai_observability", fake)
    return fake, events


def test_opt_in_and_secret_configuration(sdk):
    fake, _ = sdk
    assert observability.initialize(Settings(_env_file=None)) is None
    fake.init.assert_not_called()
    settings = Settings(
        _env_file=None, kedb_observability_enabled=True,
        ai_observability_endpoint="http://collector:8000",
        ai_observability_api_key="test-key",
    )
    assert observability.initialize(settings) is fake
    observability.initialize(settings)
    fake.init.assert_called_once()
    assert fake.init.call_args.kwargs["capture_prompts"] is False
    assert fake.init.call_args.kwargs["api_key"] == "test-key"
    observability.shutdown()
    fake.flush.assert_called_once_with(timeout_millis=5000)
    fake.shutdown.assert_called_once()
    assert observability._sdk is None


def test_curator_identity_survives_review_and_publish(sdk, monkeypatch):
    fake, events = sdk
    monkeypatch.setattr(observability, "_sdk", fake)
    curator = CuratorWorkflow(None, None)
    monkeypatch.setattr(curator, "_start", lambda issue, workflow_id: {"workflow_id": workflow_id})
    monkeypatch.setattr(curator, "_apply_review", lambda state, review: state)
    monkeypatch.setattr(curator, "_publish", lambda state: state)
    state = curator.start({})
    curator.apply_review(state, {})
    curator.publish(state)
    assert state["workflow_id"]
    assert [event["workflow_id"] for event in events] == [state["workflow_id"]] * 3


def test_business_errors_propagate(sdk, monkeypatch):
    fake, events = sdk
    monkeypatch.setattr(observability, "_sdk", fake)

    @observability.traced_step("validation")
    def fail():
        raise ValueError("invalid output")

    with pytest.raises(ValueError, match="invalid output"):
        with observability.execution("test"):
            fail()
    assert [event["name"] for event in events] == ["test", "validation"]


def test_initialization_failure_does_not_break_application(sdk):
    fake, _ = sdk
    fake.init.side_effect = RuntimeError("unavailable")
    assert observability.initialize(Settings(
        _env_file=None, kedb_observability_enabled=True,
        ai_observability_endpoint="http://collector:8000",
        ai_observability_api_key="test-key",
    )) is None
