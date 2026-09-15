from uuid import uuid4
from kedb.domain.entities import JiraIssue, RetrievalCandidate
from kedb.application.retrieval.hybrid import HybridRetrievalCoordinator

K=uuid4(); V=uuid4()
class Exact:
 def search(self,*a,**k): return [RetrievalCandidate(K,V,"A",exact_score=1)]
class Lex:
 def search(self,*a,**k): return [RetrievalCandidate(K,V,"A",lexical_score=.8)]
class Vec:
 def search(self,*a,**k): return [RetrievalCandidate(K,V,"A",vector_score=.9)]
class Emb:
 def embed(self,*a): return [0.1,0.2]

def test_merge_deduplicates_same_article():
 r=HybridRetrievalCoordinator(Exact(),Lex(),Vec(),Emb()).search(JiraIssue("I","s","d","r"))
 assert len(r)==1 and r[0].rank==1 and r[0].exact_score==1 and r[0].vector_score==.9
