import json
from openai import OpenAI

class DatabricksModelServingProvider:
    def __init__(self, *, base_url: str, token: str, model: str):
        self.client = OpenAI(api_key=token, base_url=base_url.rstrip('/') + '/serving-endpoints')
        self.model = model

    def structured(self, *, system: str, user: str, schema):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{'role':'system','content':system},{'role':'user','content':user}],
            response_format={
                'type':'json_schema',
                'json_schema': {'name': schema.__name__.lower(), 'schema': schema.model_json_schema()}
            },
            temperature=0,
        )
        return schema.model_validate(json.loads(response.choices[0].message.content))
