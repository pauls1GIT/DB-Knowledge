from __future__ import annotations
import httpx
from kedb.config import settings


class OllamaEmbeddingProvider:
    def __init__(self, base_url=None, model=None):
        self.base_url=(base_url or settings.ollama_base_url).rstrip('/')
        self.model=model or settings.ollama_embed_model
    def embed(self, text: str) -> list[float]:
        r=httpx.post(f"{self.base_url}/api/embed", json={"model":self.model,"input":text}, timeout=120)
        r.raise_for_status(); return r.json()["embeddings"][0]
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        r=httpx.post(f"{self.base_url}/api/embed", json={"model":self.model,"input":texts}, timeout=120)
        r.raise_for_status(); return r.json()["embeddings"]
