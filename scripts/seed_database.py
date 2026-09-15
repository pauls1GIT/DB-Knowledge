import argparse, json
from pathlib import Path
from kedb.domain.entities import JiraIssue
from kedb.infrastructure.persistence.repositories import SqlAlchemyKnowledgeRepository

if __name__=="__main__":
 p=argparse.ArgumentParser(); p.add_argument("file",nargs="?",default="mock_incidents.json"); a=p.parse_args()
 repo=SqlAlchemyKnowledgeRepository(); rows=json.loads(Path(a.file).read_text())
 for x in rows:
  x={k:v for k,v in x.items() if k!="kind"}; repo.save_issue(JiraIssue(**x))
 print(f"Seeded {len(rows)} Jira issues")
