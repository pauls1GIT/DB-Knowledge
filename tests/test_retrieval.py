from uuid import uuid4
from kedb.infrastructure.search.in_memory import InMemorySearch
from kedb.application.retrieval import RetrievalCoordinator

def test_exact_identifier_boosts_expected_candidate():
    ke1,ke2,v1,v2=uuid4(),uuid4(),uuid4(),uuid4()
    search=InMemorySearch([
      {'known_error_id':ke1,'article_version_id':v1,'title':'Oracle timeout ORA-12170','content':'connection timeout'},
      {'known_error_id':ke2,'article_version_id':v2,'title':'Generic Oracle issue','content':'connection timeout'}])
    rows=RetrievalCoordinator(search).search('Oracle connection timeout ORA-12170')
    assert rows[0].known_error_id==ke1
    assert rows[0].rank==1
