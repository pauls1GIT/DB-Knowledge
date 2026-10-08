import json
from openai import OpenAI


class OllamaModelProvider:
    def __init__(self, model: str = "llama3.2:3b"):
        self.client = OpenAI(
            api_key="ollama",
            base_url="http://localhost:11434/v1",
        )
        self.model = model


    def structured(self, *, system: str, user: str, schema):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__.lower(),
                    "schema": schema.model_json_schema(),
                },
            },
            temperature=0,
        )

        return schema.model_validate(
            json.loads(response.choices[0].message.content)
        )
