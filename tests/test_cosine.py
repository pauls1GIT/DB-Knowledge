from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from kedb.application.retrieval.cosine import article_text, cosine_similarity
from kedb.infrastructure.lakebase import Database
from kedb.infrastructure.lakebase.models import ArticleEmbeddingRow, ArticleVersionRow, KnownErrorRow
from kedb.infrastructure.search.article_cosine import ArticleCosineScorer, DatabricksArticleEmbedder


@pytest.mark.parametrize("left,right,expected", [
    ([1, 0], [2, 0], 1), ([1, 0], [0, 1], 0), ([1, 0], [-1, 0], -1),
    ([3, 4], [1, 0], .6),
])
def test_cosine_known_vectors(left, right, expected):
    assert cosine_similarity(left, right) == pytest.approx(expected)


@pytest.mark.parametrize("invalid", [[], [0, 0], [float("nan"), 1], [float("inf"), 1], [[1, 2]]])
def test_invalid_vectors_fail(invalid):
    with pytest.raises(ValueError):
        cosine_similarity(invalid, [1, 0])


def test_dimension_mismatch_fails():
    with pytest.raises(ValueError, match="dimensions"):
        cosine_similarity([1, 0], [1, 0, 0])


def test_cached_article_scoring_covers_index_lag_and_model_version(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path / 'cosine.db'}")
    db.create_all()
    proposal = dict(problem="p", root_cause="r", solution="s")
    calls = []
    embedder = SimpleNamespace(model="test", model_version="1",
                              embed_batch=lambda texts: calls.append(texts) or [[1, 0] for _ in texts])
    ids = [str(uuid4()) for _ in range(4)]
    with db.sessions.begin() as session:
        session.add(KnownErrorRow(id=ids[0], title="t", current_version_id=ids[1]))
        session.flush()
        for version, status, number in [(ids[1], "PUBLISHED", 2), (ids[2], "PUBLISHED", 1),
                                         (ids[3], "DRAFT", 3)]:
            session.add(ArticleVersionRow(id=version, known_error_id=ids[0], title="t",
                                         version_number=number, status=status, **proposal))
    scorer = ArticleCosineScorer(db, embedder)
    rows = scorer.score(proposal, [])  # Not yet returned by the search index.
    assert len(rows) == 1
    assert rows[0]["article_version_id"] == ids[1]
    assert rows[0]["cosine_score"] == 1
    assert len(calls) == 1  # Identical proposal and article share the cache.
    scorer.score(proposal, [])
    assert len(calls) == 1
    embedder.model_version = "2"
    scorer.score(proposal, [])
    assert len(calls) == 2
    with db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ArticleEmbeddingRow)) == 2


def test_databricks_adapter_uses_embedding_endpoint(monkeypatch):
    from kedb.config import Settings
    from kedb.infrastructure import databricks_auth
    calls = []
    client = SimpleNamespace(serving_endpoints=SimpleNamespace(query=lambda **kwargs:
        calls.append(kwargs) or SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[3, 4])])) )
    monkeypatch.setattr(databricks_auth, "workspace_client", lambda settings: client)
    embedder = DatabricksArticleEmbedder(Settings(_env_file=None, databricks_embedding_endpoint="embedding-test"))
    assert embedder.embed("article") == [3, 4]
    assert calls == [{"name": "embedding-test", "input": ["article"]}]


def test_article_representation_is_consistent():
    assert article_text(dict(problem="  p\n x ", root_cause="r", solution="s")) == (
        "Problem: p x\n\nRoot cause: r\n\nResolution: s")



def test_bulk_cache_and_embedding_batches_reuse_client(tmp_path, monkeypatch):
    from sqlalchemy import event
    from kedb.config import Settings
    from kedb.infrastructure import databricks_auth
    db = Database(f"sqlite+pysqlite:///{tmp_path / 'bulk.db'}")
    db.create_all()
    with db.sessions.begin() as session:
        for index in range(40):
            key, version = str(uuid4()), str(uuid4())
            session.add(KnownErrorRow(id=key, title=str(index), current_version_id=version))
            session.flush()
            session.add(ArticleVersionRow(id=version, known_error_id=key, title=str(index),
                version_number=1, status="PUBLISHED", problem=f"problem {index}",
                root_cause="cause", solution="fix"))
    requests, clients, statements = [], [], []

    def query(**kwargs):
        requests.append(kwargs["input"])
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[1, 0])
                                     for i in reversed(range(len(kwargs["input"])))])

    client = SimpleNamespace(serving_endpoints=SimpleNamespace(query=query))
    monkeypatch.setattr(databricks_auth, "workspace_client", lambda settings: clients.append(True) or client)
    embedder = DatabricksArticleEmbedder(Settings(_env_file=None, kedb_embedding_batch_size=16))
    scorer = ArticleCosineScorer(db, embedder)
    event.listen(db.engine, "before_cursor_execute", lambda conn, cursor, statement, *args:
                 statements.append(statement) if statement.lstrip().upper().startswith("SELECT") else None)
    proposal = dict(problem="new", root_cause="cause", solution="fix")
    rows = scorer.score(proposal, [])
    assert len(rows) == 40
    assert all(row["cosine_score"] == 1 for row in rows)
    assert [len(batch) for batch in requests] == [16, 16, 9]
    assert len(clients) == 1
    assert len(statements) == 2  # One corpus read + one cache read, not 41 cache reads.
    statements.clear()
    assert scorer.score(proposal, []) == rows
    assert len(requests) == 3  # Entirely cached: no new embedding requests.
    assert len(statements) == 2
    scorer.score({**proposal, "problem": "another"}, [])
    assert len(requests) == 4
    assert len(requests[-1]) == 1
    assert len(clients) == 1


@pytest.mark.parametrize("data", [
    [],
    [SimpleNamespace(index=0, embedding=[1, 0])],
    [SimpleNamespace(index=0, embedding=[1, 0]), SimpleNamespace(index=0, embedding=[0, 1])],
    [SimpleNamespace(index=0, embedding=[1, 0]), SimpleNamespace(index=3, embedding=[0, 1])],
])
def test_malformed_batch_responses_fail(data):
    from kedb.config import Settings
    embedder = DatabricksArticleEmbedder(Settings(_env_file=None))
    embedder.client = SimpleNamespace(serving_endpoints=SimpleNamespace(
        query=lambda **kwargs: SimpleNamespace(data=data)))
    with pytest.raises(ValueError):
        embedder.embed_batch(["a", "b"])


def test_response_indices_preserve_input_order():
    from kedb.config import Settings
    embedder = DatabricksArticleEmbedder(Settings(_env_file=None))
    embedder.client = SimpleNamespace(serving_endpoints=SimpleNamespace(query=lambda **kwargs:
        SimpleNamespace(data=[SimpleNamespace(index=1, embedding=[0, 1]),
                              SimpleNamespace(index=0, embedding=[1, 0])])))
    assert embedder.embed_batch(["a", "b"]) == [[1, 0], [0, 1]]
