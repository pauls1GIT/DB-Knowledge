"""Model Serving through the native Databricks LangChain integration."""
from kedb.observability import initialize


class DatabricksModelServingProvider:
    def __init__(self, *, model: str, workspace_client=None):
        initialize()
        from databricks_langchain import ChatDatabricks

        self.client = ChatDatabricks(
            model=model, workspace_client=workspace_client, temperature=0,
        )
        self.model = model

    def structured(self, *, system: str, user: str, schema):
        runnable = self.client.with_structured_output(schema, method="json_schema")
        result = runnable.invoke([("system", system), ("human", user)])
        return schema.model_validate(result)
