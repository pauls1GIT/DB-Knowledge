from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://kedb:kedb123@127.0.0.1:55432/kedb"
    langgraph_checkpoint_url: str = "postgresql://kedb:kedb123@127.0.0.1:55432/kedb"
    chroma_path: str = ".chroma"
    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_model: str = "qwen3:4b"
    ollama_embed_model: str = "nomic-embed-text"
    retrieval_exact_weight: float = 0.45
    retrieval_vector_weight: float = 0.35
    retrieval_lexical_weight: float = 0.20
    api_base_url: str = "http://localhost:8000"


settings = Settings()
