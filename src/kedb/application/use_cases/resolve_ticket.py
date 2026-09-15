from kedb.application.dto import GroundedAnswer
from pathlib import Path

class ResolveTicket:
    def __init__(self,retrieval,llm): self.retrieval=retrieval; self.llm=llm
    def execute(self,issue):
        candidates=self.retrieval.search(issue,limit=5)
        evidence=[{"known_error_id":str(c.known_error_id),"article_version_id":str(c.article_version_id),"title":c.title,"score":c.final_score} for c in candidates]
        prompt=(Path(__file__).resolve().parents[4]/"prompts/grounded_answer/v1.md").read_text()
        return self.llm.structured(prompt,f"ISSUE={issue}\nAPPROVED EVIDENCE={evidence}",GroundedAnswer)
