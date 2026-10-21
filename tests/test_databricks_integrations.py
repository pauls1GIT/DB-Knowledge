import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from kedb.application.dto import RetrievalPlan
from kedb.infrastructure.llm.databricks_model import DatabricksModelServingProvider
from kedb.infrastructure.search.databricks_ai_search import DatabricksAISearch


@pytest.fixture
def native(monkeypatch):
    module = ModuleType("databricks_langchain")
    module.ChatDatabricks = Mock()
    module.DatabricksVectorSearch = Mock()
    monkeypatch.setitem(sys.modules, "databricks_langchain", module)
    monkeypatch.setattr("kedb.infrastructure.llm.databricks_model.initialize", lambda: None)
    return module


def test_native_model_uses_workspace_credentials_and_validated_schema(native):
    workspace = object()
    model = DatabricksModelServingProvider(model="endpoint", workspace_client=workspace)
    runnable = native.ChatDatabricks.return_value.with_structured_output.return_value
    runnable.invoke.return_value = {"semantic_query": "connection timeout"}
    result = model.structured(system="Extract a plan", user="incident", schema=RetrievalPlan)
    assert result.semantic_query == "connection timeout"
    native.ChatDatabricks.assert_called_once_with(
        model="endpoint", workspace_client=workspace, temperature=0,
    )
    model.client.with_structured_output.assert_called_once_with(
        RetrievalPlan, method="json_schema",
    )
    runnable.invoke.assert_called_once_with([("system", "Extract a plan"), ("human", "incident")])


def test_native_model_failure_is_not_swallowed(native):
    provider = DatabricksModelServingProvider(model="endpoint")
    native.ChatDatabricks.return_value.with_structured_output.return_value.invoke.side_effect = (
        RuntimeError("Model unavailable")
    )
    with pytest.raises(RuntimeError, match="Model unavailable"):
        provider.structured(system="plan", user="incident", schema=RetrievalPlan)


@pytest.mark.parametrize("mode,lexical,vector", [
    ("FULL_TEXT", .75, 0), ("ANN", 0, .75), ("HYBRID", 0, 0),
])
def test_native_search_preserves_filters_metadata_and_channel_scores(native, mode, lexical, vector):
    adapter = DatabricksAISearch("endpoint", "catalog.schema.index")
    known_error, version = uuid4(), uuid4()
    document = SimpleNamespace(page_content="Fix the connection", metadata={
        "known_error_id": str(known_error), "article_version_id": str(version),
        "title": "Timeout", "error_codes": ["ORA-12170"],
    })
    adapter.store.similarity_search_with_score.return_value = [(document, .75)]
    result = adapter.search("timeout", ["ORA-12170"], top_k=3, query_type=mode)
    adapter.store.similarity_search_with_score.assert_called_once_with(
        "timeout", k=3, query_type=mode, filter={"is_current": True, "status": "PUBLISHED"},
    )
    assert result[0].known_error_id == known_error
    assert result[0].article_version_id == version
    assert result[0].exact_score == 1
    assert result[0].search_score == .75
    assert result[0].lexical_score == lexical
    assert result[0].vector_score == vector


def test_workspace_client_keeps_oauth_credentials_refreshable(monkeypatch):
    from kedb.infrastructure import databricks_auth
    from kedb.config import Settings

    client = Mock()
    monkeypatch.setattr(databricks_auth, "WorkspaceClient", client)
    settings = Settings(_env_file=None, databricks_host="https://workspace/",
                        databricks_client_id="app", databricks_client_secret="secret")
    assert databricks_auth.workspace_client(settings) is client.return_value
    client.assert_called_once_with(host="https://workspace", client_id="app",
                                   client_secret="secret", auth_type="oauth-m2m")
