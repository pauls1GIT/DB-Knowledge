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
