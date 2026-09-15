from __future__ import annotations
import json, re, httpx
from pydantic import BaseModel
from kedb.config import settings


class OllamaQwenLLM:
    def __init__(self, base_url=None, model=None):
        self.base_url=(base_url or settings.ollama_base_url).rstrip('/')
        self.model=model or settings.ollama_llm_model
    def structured(self, system_prompt: str, user_prompt: str, schema: type[BaseModel]):
        payload={"model":self.model,"stream":False,"format":schema.model_json_schema(),"messages":[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}]}
        r=httpx.post(f"{self.base_url}/api/chat",json=payload,timeout=180); r.raise_for_status()
        content=r.json()["message"]["content"]
        return schema.model_validate(json.loads(content))
