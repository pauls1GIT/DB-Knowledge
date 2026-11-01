from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr, model_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kedb_env: str = "dev"
    kedb_observability_enabled: bool = False
    ai_observability_endpoint: str = ""
    ai_observability_api_key: SecretStr = SecretStr("")
    # Local development only. In Databricks, attached Lakebase PG* variables
    # take precedence automatically.
    kedb_database_url: str = "sqlite+pysqlite:///./kedb-local.db"

    databricks_host: str = ""
    databricks_token: str = ""
    databricks_client_id: str = ""
    databricks_client_secret: str = ""
    databricks_ai_search_endpoint: str = ""
    databricks_ai_search_index: str = ""
    databricks_model_endpoint: str = ""
    databricks_embedding_endpoint: str = "databricks-qwen3-embedding-0-6b"
    kedb_embedding_model_version: str = "v1"
    kedb_duplicate_threshold: float = Field(default=0.90, ge=-1, le=1, allow_inf_nan=False)
    kedb_auto_approve_threshold: float = Field(default=0.60, ge=-1, le=1, allow_inf_nan=False)
    kedb_embedding_batch_size: int = Field(default=16, ge=1, le=64)

    @model_validator(mode="after")
    def validate_cosine_thresholds(self):
        if self.kedb_auto_approve_threshold >= self.kedb_duplicate_threshold:
            raise ValueError("Auto-approve threshold must be below duplicate rejection threshold")
        return self

    kedb_search_top_k: int = 5
    databricks_warehouse_id: str = ""
    kedb_uc_chunk_table: str = "kedb_dev.knowledge.article_chunks"

    kedb_json_path: str = ""
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_jql: str = "statusCategory = Done ORDER BY key ASC"
    # Custom field containing actual remediation text, e.g. customfield_10042.
    jira_resolution_field: str = "resolution"

    jira_webhook_token: str = ""
    kedb_email_delivery: str = "jira"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_from: str = ""
