from kedb.application.dto import GroundedAnswer

class GenerateGroundedAnswer:
    def __init__(self, llm): self.llm=llm
    def execute(self, question: str, evidence: list[dict], history: list[dict] | None = None) -> GroundedAnswer:
        if not evidence:
            raise ValueError('Grounded answer requires published evidence')

        context = '\n\n'.join(
            f"[{i}] {e['title']} v{e.get('version_number','?')}\n{e['content']}"
            for i, e in enumerate(evidence, 1)
        )

        history = history or []
        conversation = '\n'.join(
            f"{m.get('role', 'user')}: {m.get('content', '')}"
            for m in history
        )

        return self.llm.structured(
            system='Answer only from supplied approved KEDB evidence. Use the conversation history to understand follow-up questions. Return evidence references.',
            user=f'Conversation:\n{conversation}\n\nQuestion:\n{question}\n\nEvidence:\n{context}',
            schema=GroundedAnswer
        )