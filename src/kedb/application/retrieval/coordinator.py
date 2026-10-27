from kedb.observability import traced_step

import re
from dataclasses import replace

from kedb.domain import RetrievalCandidate

IDENTIFIER_RE = re.compile(r"\b(?:ORA-\d+|HTTP\s?\d{3}|[A-Z]{2,}(?:-[A-Z0-9]+){1,})\b", re.I)


class RetrievalCoordinator:
    def __init__(self, search_port, exact_boost: float = 0.25):
        self.search_port = search_port
        self.exact_boost = exact_boost

    def identifiers(self, query: str) -> list[str]:
        return list(
            dict.fromkeys(
                m.group(0).upper().replace("HTTP ", "HTTP ")
                for m in IDENTIFIER_RE.finditer(query)
            )
        )

    @traced_step("coordinator.search_port")
    def _search_port(self, query: str, *, query_type: str, top_k: int) -> list[RetrievalCandidate]:
        ids = self.identifiers(query)
        try:
            return self.search_port.search(
                query,
                ids,
                top_k=max(top_k * 2, 10),
                query_type=query_type,
            )
        except TypeError:
            # Compatibility with older/custom SearchPort implementations.
            return self.search_port.search(query, ids, top_k=max(top_k * 2, 10))

    def exact_search(self, query: str, top_k: int = 5) -> list[RetrievalCandidate]:
        rows = self._search_port(query, query_type="FULL_TEXT", top_k=top_k)
        exact = [replace(c, final_score=max(c.final_score, c.exact_score)) for c in rows if c.exact_score > 0]
        exact.sort(key=lambda c: (c.exact_score, c.search_score), reverse=True)
        return [replace(c, rank=i + 1) for i, c in enumerate(exact[:top_k])]

    def full_text_search(self, query: str, top_k: int = 5) -> list[RetrievalCandidate]:
        rows = self._search_port(query, query_type="FULL_TEXT", top_k=top_k)
        rescored = [replace(c, final_score=c.lexical_score or c.search_score) for c in rows]
        rescored.sort(key=lambda c: c.final_score, reverse=True)
        return [replace(c, rank=i + 1) for i, c in enumerate(rescored[:top_k])]

    def vector_search(self, query: str, top_k: int = 5) -> list[RetrievalCandidate]:
        rows = self._search_port(query, query_type="ANN", top_k=top_k)
        rescored = [replace(c, final_score=c.vector_score or c.search_score) for c in rows]
        rescored.sort(key=lambda c: c.final_score, reverse=True)
        return [replace(c, rank=i + 1) for i, c in enumerate(rescored[:top_k])]

    def hybrid_search(self, query: str, top_k: int = 5) -> list[RetrievalCandidate]:
        rows = self._search_port(query, query_type="HYBRID", top_k=top_k)
        # Preserve the backend's fused score; collapse multiple chunks per article.
        unique = {}
        for candidate in sorted(rows, key=lambda c: c.search_score, reverse=True):
            key = (candidate.known_error_id, candidate.article_version_id)
            unique.setdefault(key, candidate)
        return [replace(c, final_score=c.search_score, rank=i + 1)
                for i, c in enumerate(list(unique.values())[:top_k])]

    @traced_step("coordinator.search_by_fields")
    def search_by_fields(
        self, identifier_query: str, description_query: str, top_k: int = 5
    ) -> list[RetrievalCandidate]:
        identifier_query = identifier_query.strip()
        description_query = description_query.strip()
        if not identifier_query and not description_query:
            return []

        exact = {}
        for identifier in self.identifiers(identifier_query):
            for candidate in self.exact_search(identifier, top_k):
                key = (candidate.known_error_id, candidate.article_version_id)
                exact.setdefault(key, candidate)
        exact_results = list(exact.values())[:top_k]
        if not description_query:
            return [replace(c, rank=i + 1) for i, c in enumerate(exact_results)]

        description_results = self.search(description_query, top_k)
        if not identifier_query:
            return description_results

        # Reciprocal rank fusion rewards articles returned by both searches.
        candidates, scores = {}, {}
        for rows in (exact_results, description_results):
            for position, candidate in enumerate(rows, start=1):
                key = (candidate.known_error_id, candidate.article_version_id)
                candidates.setdefault(key, candidate)
                scores[key] = scores.get(key, 0.0) + 1.0 / (60 + position)
        ranked = sorted(scores, key=scores.get, reverse=True)[:top_k]
        return [replace(candidates[key], final_score=scores[key], rank=i + 1)
                for i, key in enumerate(ranked)]

    def search(self, query: str, top_k: int = 5) -> list[RetrievalCandidate]:
        merged = {}
        for channel, rows in (("lexical_score", self.full_text_search(query, top_k)),
                              ("vector_score", self.vector_search(query, top_k))):
            for candidate in rows:
                key = (candidate.known_error_id, candidate.article_version_id)
                current = merged.setdefault(key, replace(candidate, lexical_score=0, vector_score=0))
                merged[key] = replace(current, **{channel: max(getattr(current, channel), candidate.final_score)})
        rescored = [replace(c, final_score=0.5 * c.lexical_score + 0.5 * c.vector_score)
                    for c in merged.values()]
        rescored.sort(key=lambda c: c.final_score, reverse=True)
        return [replace(c, rank=i + 1) for i, c in enumerate(rescored[:top_k])]
