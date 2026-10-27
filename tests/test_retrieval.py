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


def test_field_search_supports_database_fallback_and_combines_rankings():
    exact_id, shared_id, description_id = uuid4(), uuid4(), uuid4()
    docs = [
        {'known_error_id': exact_id, 'article_version_id': uuid4(),
         'title': 'ORA-12170', 'content': ''},
        {'known_error_id': shared_id, 'article_version_id': uuid4(),
         'title': 'ORA-12170 connection timeout', 'content': ''},
        {'known_error_id': description_id, 'article_version_id': uuid4(),
         'title': 'connection timeout', 'content': ''},
    ]
    retriever = RetrievalCoordinator(InMemorySearch(docs))
    assert retriever.search_by_fields(' ', ' ') == []
    assert retriever.search_by_fields('unsupported', '') == []
    exact = retriever.search_by_fields(' ora-12170 ', '')
    assert {c.known_error_id for c in exact} == {exact_id, shared_id}
    description = retriever.search_by_fields('', 'connection timeout')
    assert {c.known_error_id for c in description} == {shared_id, description_id}
    combined = retriever.search_by_fields('ORA-12170', 'connection timeout')
    assert combined[0].known_error_id == shared_id
    assert len(combined) == 3
    assert [c.rank for c in combined] == [1, 2, 3]
    assert len(retriever.search_by_fields('ORA-12170', 'connection timeout', top_k=1)) == 1
