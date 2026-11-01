"""Bulk article embedding cache and vectorized duplicate scoring."""
from functools import cached_property
import hashlib
import json
import logging
from time import perf_counter

import numpy as np
from sqlalchemy import select

from kedb.application.retrieval.cosine import article_text, validate_vector
from kedb.infrastructure.lakebase.models import ArticleEmbeddingRow, ArticleVersionRow, KnownErrorRow
from kedb.observability import traced_step

logger = logging.getLogger(__name__)


class DatabricksArticleEmbedder:
    def __init__(self, settings):
        self.settings = settings
        self.model = settings.databricks_embedding_endpoint
        self.model_version = settings.kedb_embedding_model_version
        self.batch_size = settings.kedb_embedding_batch_size

    @cached_property
    def client(self):
        from kedb.infrastructure.databricks_auth import workspace_client
        return workspace_client(self.settings)

    @traced_step("duplication.generate_embeddings")
    def embed_batch(self, texts):
        if not self.model:
            raise ValueError("Configure DATABRICKS_EMBEDDING_ENDPOINT for cosine duplicate scoring")
        vectors = []
        for offset in range(0, len(texts), self.batch_size):
            batch = texts[offset:offset + self.batch_size]
            response = self.client.serving_endpoints.query(name=self.model, input=batch)
            if not response.data or len(response.data) != len(batch):
                raise ValueError("Embedding endpoint returned an incorrect vector count")
            indexed = {}
            for item in response.data:
                index = item.get("index") if isinstance(item, dict) else item.index
                vector = item.get("embedding") if isinstance(item, dict) else item.embedding
                if type(index) is not int or not 0 <= index < len(batch) or index in indexed:
                    raise ValueError("Embedding response has invalid or duplicate indices")
                indexed[index] = validate_vector(vector).tolist()
            vectors.extend(indexed[i] for i in range(len(batch)))
        return vectors

    def embed(self, text):
        return self.embed_batch([text])[0]


class ArticleCosineScorer:
    # Bound SQL parameter counts for both SQLite and Postgres.
    cache_batch_size = 200

    def __init__(self, database, embedder):
        self.database = database
        self.embedder = embedder

    def _vectors(self, texts):
        keys = [hashlib.sha256(json.dumps([
            self.embedder.model, self.embedder.model_version, text
        ]).encode()).hexdigest() for text in texts]
        unique = dict(zip(keys, texts))
        vectors = {}
        unique_keys = list(unique)
        with self.database.sessions() as session:
            for offset in range(0, len(unique_keys), self.cache_batch_size):
                rows = session.scalars(select(ArticleEmbeddingRow).where(
                    ArticleEmbeddingRow.key.in_(unique_keys[offset:offset + self.cache_batch_size])))
                vectors.update((row.key, validate_vector(row.vector)) for row in rows)
        missing = [key for key in unique if key not in vectors]
        if missing:
            # Batch remote calls outside transactions; cache only complete, valid responses.
            generated = self.embedder.embed_batch([unique[key] for key in missing])
            if len(generated) != len(missing):
                raise ValueError("Embedding endpoint returned an incorrect vector count")
            generated = [validate_vector(vector) for vector in generated]
            if len({len(vector) for vector in [*vectors.values(), *generated]}) != 1:
                raise ValueError("Embedding dimensions differ; check the embedding model version")
            vectors.update(zip(missing, generated))
            dialect = self.database.engine.dialect.name
            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            elif dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert
            else:
                raise ValueError(f"Unsupported embedding cache database: {dialect}")
            with self.database.sessions.begin() as session:
                for offset in range(0, len(missing), self.cache_batch_size):
                    rows = [{"key": key, "model": self.embedder.model,
                             "model_version": self.embedder.model_version,
                             "vector": vectors[key].tolist()}
                            for key in missing[offset:offset + self.cache_batch_size]]
                    session.execute(insert(ArticleEmbeddingRow).values(rows).on_conflict_do_nothing(
                        index_elements=["key"]))
        return [vectors[key] for key in keys], len(missing)

    @traced_step("duplication.cosine_scores")
    def score(self, proposal, candidates):
        started = perf_counter()
        # Include current articles even if search missed them or index sync is pending.
        with self.database.sessions() as session:
            articles = session.scalars(select(ArticleVersionRow).join(
                KnownErrorRow, KnownErrorRow.current_version_id == ArticleVersionRow.id
            ).where(ArticleVersionRow.status == "PUBLISHED")).all()
        texts = [article_text(proposal)] + [article_text({
            "problem": article.problem, "root_cause": article.root_cause,
            "solution": article.solution}) for article in articles]
        vectors, misses = self._vectors(texts)
        if len({len(vector) for vector in vectors}) != 1:
            raise ValueError("Embedding dimensions differ; check the embedding model version")
        matrix = np.stack(vectors)
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
        scores = np.clip(matrix[1:] @ matrix[0], -1, 1)
        retrieved = {(str(c["known_error_id"]), str(c["article_version_id"])): c for c in candidates}
        scored = []
        for article, score in zip(articles, scores):
            row = dict(retrieved.get((article.known_error_id, article.id), {}))
            row.update(known_error_id=article.known_error_id, article_version_id=article.id,
                       title=article.title, root_cause=article.root_cause,
                       resolution=article.solution, cosine_score=float(score), final_score=float(score))
            row.setdefault("retrieval_methods", ["published_articles"])
            scored.append(row)
        scored.sort(key=lambda c: (-c["cosine_score"], c["article_version_id"]))
        for rank, row in enumerate(scored, 1):
            row["rank"] = rank
        logger.info("Cosine comparison articles=%d cache_misses=%d elapsed_seconds=%.3f",
                    len(articles), misses, perf_counter() - started)
        return scored
