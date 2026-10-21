import sys
from types import ModuleType
from unittest.mock import Mock
import pytest
from kedb.infrastructure.search.databricks_ai_search import DatabricksAISearch

@pytest.mark.parametrize('credentials,expected', [
    ({'client_id': 'app-id', 'client_secret': 'app-secret'}, {'service_principal_client_id': 'app-id', 'service_principal_client_secret': 'app-secret'}),
    ({'token': 'test-token', 'client_id': 'app-id', 'client_secret': 'app-secret'}, {'personal_access_token': 'test-token'}),
    ({}, {}),
])
@pytest.mark.parametrize("workspace_url", ["https://workspace", "workspace", " https://workspace/ "])
def test_search_authentication(monkeypatch, credentials, expected, workspace_url):
    module = ModuleType('databricks_langchain')
    module.DatabricksVectorSearch = Mock()
    monkeypatch.setitem(sys.modules, 'databricks_langchain', module)
    adapter = DatabricksAISearch('endpoint', 'catalog.schema.index', workspace_url=workspace_url, **credentials)
    kwargs = module.DatabricksVectorSearch.call_args.kwargs
    assert kwargs["client_args"] == dict(disable_notice=True, workspace_url="https://workspace", **expected)
    assert kwargs["index_name"] == "catalog.schema.index"
    # Managed embeddings infer the source column; explicitly passing it is rejected.
    assert "text_column" not in kwargs
    assert "status" in kwargs["columns"]
