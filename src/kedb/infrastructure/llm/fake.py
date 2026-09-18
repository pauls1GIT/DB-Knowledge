class FakeLLM:
    def __init__(self, responses: dict[type, object]): self.responses=responses
    def structured(self, *, system: str, user: str, schema):
        value=self.responses[schema]
        return value if isinstance(value,schema) else schema.model_validate(value)
