from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kedb_env: str = "dev"
    # Local development only. In Databricks, attached Lakebase PG* variables
    # take precedence automatically.
    kedb_database_url: str = "sqlite+pysqlite:///./kedb-local.db"

    databricks_host: str = ""
    databricks_token: str = ""
    databricks_ai_search_endpoint: str = ""
    databricks_ai_search_index: str = ""
    databricks_model_endpoint: str = ""
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
