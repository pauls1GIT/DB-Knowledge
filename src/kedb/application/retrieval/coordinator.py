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

    def search(self, query: str, top_k: int = 5) -> list[RetrievalCandidate]:
        ids = self.identifiers(query)
        try:
            rows = self.search_port.search(
                query,
                ids,
                top_k=max(top_k * 2, 10),
                query_type="HYBRID",
            )
        except TypeError:
            rows = self.search_port.search(query, ids, top_k=max(top_k * 2, 10))
        rescored = []
        for candidate in rows:
            score = candidate.search_score + (self.exact_boost * candidate.exact_score)
            rescored.append(replace(candidate, final_score=score))
        rescored.sort(key=lambda x: x.final_score, reverse=True)
        return [replace(candidate, rank=i + 1) for i, candidate in enumerate(rescored[:top_k])]
