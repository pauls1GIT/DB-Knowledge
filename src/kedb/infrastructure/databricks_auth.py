"""Use refreshable SDK credentials for Databricks-native integrations."""
from databricks.sdk import WorkspaceClient

from kedb.config import Settings


def workspace_client(settings: Settings) -> WorkspaceClient:
    kwargs = {}
    if settings.databricks_host:
        kwargs["host"] = settings.databricks_host.strip().rstrip("/")
    if settings.databricks_token:
        kwargs["token"] = settings.databricks_token
        kwargs["auth_type"] = "pat"
    elif settings.databricks_client_id and settings.databricks_client_secret:
        kwargs.update(
            client_id=settings.databricks_client_id,
            client_secret=settings.databricks_client_secret,
            auth_type="oauth-m2m",
        )
    return WorkspaceClient(**kwargs)
