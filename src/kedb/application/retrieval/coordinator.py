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

    def search_exact_identifier(
        self, query: str, top_k: int = 5
    ) -> list[RetrievalCandidate]:
        identifiers = self.identifiers(query)

        if not identifiers:
            return []

        results = {}

        for identifier in identifiers:
            candidates = self.search_port.search_exact_identifier(
                identifier, top_k=top_k
            )

            for candidate in candidates:
                key = (candidate.known_error_id, candidate.article_version_id)
                results.setdefault(key, candidate)

        return [
            replace(candidate, rank=i + 1)
            for i, candidate in enumerate(list(results.values())[:top_k])
        ]

    def search_by_fields(
        self,
        identifier_query: str,
        description_query: str,
        top_k: int = 5,
    ) -> list[RetrievalCandidate]:
        identifier_query = identifier_query.strip()
        description_query = description_query.strip()

        if not identifier_query and not description_query:
            return []

        # Identifier-only: exact matching.
        if identifier_query and not description_query:
            return self.search_exact_identifier(identifier_query, top_k)

        # Description-only: lexical + vector retrieval.
        if description_query and not identifier_query:
            return self.search(description_query, top_k)

        # Both fields: retrieve independently, then combine rankings.
        exact_results = self.search_exact_identifier(identifier_query, top_k)
        description_results = self.search(description_query, top_k)

        rrf_k = 60
        fused = {}

        for results in (exact_results, description_results):
            for position, candidate in enumerate(results, start=1):
                key = (candidate.known_error_id, candidate.article_version_id)

                if key not in fused:
                    fused[key] = {
                        "candidate": candidate,
                        "score": 0.0,
                    }

                fused[key]["score"] += 1.0 / (rrf_k + position)

        ranked = sorted(
            fused.values(),
            key=lambda item: item["score"],
            reverse=True,
        )

        return [
            replace(
                item["candidate"],
                final_score=item["score"],
                rank=i + 1,
            )
            for i, item in enumerate(ranked[:top_k])
        ]