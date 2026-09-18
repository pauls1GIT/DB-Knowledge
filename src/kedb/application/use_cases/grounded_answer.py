from kedb.application.dto import GroundedAnswer

class GenerateGroundedAnswer:
    def __init__(self, llm): self.llm=llm
    def execute(self, question: str, evidence: list[dict]) -> GroundedAnswer:
        if not evidence: raise ValueError('Grounded answer requires published evidence')
        context='\n\n'.join(f"[{i}] {e['title']} v{e.get('version_number','?')}\n{e['content']}" for i,e in enumerate(evidence,1))
        return self.llm.structured(system='Answer only from supplied approved KEDB evidence. Return evidence references.', user=f'Question:\n{question}\n\nEvidence:\n{context}', schema=GroundedAnswer)
