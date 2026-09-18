from kedb.domain import RetrievalCandidate


class InMemorySearch:
    def __init__(self, docs: list[dict]):
        self.docs = docs

    def search(
        self,
        query: str,
        exact_identifiers: list[str],
        top_k: int = 5,
        query_type: str = "HYBRID",
    ):
        query_tokens = set(query.lower().split())
        output = []
        for doc in self.docs:
            text = (doc["title"] + " " + doc.get("content", "")).lower()
            lexical = len(query_tokens & set(text.split())) / max(len(query_tokens), 1)
            exact = 1.0 if any(identifier.lower() in text for identifier in exact_identifiers) else 0.0
            # Local test adapter has no embeddings; lexical overlap stands in for ANN similarity.
            vector = lexical
            if query_type == "FULL_TEXT":
                score = lexical
            elif query_type == "ANN":
                score = vector
            else:
                score = 0.55 * vector + 0.30 * lexical + 0.15 * exact
            if score > 0 or exact > 0:
                output.append(
                    RetrievalCandidate(
                        known_error_id=doc["known_error_id"],
                        article_version_id=doc["article_version_id"],
                        title=doc["title"],
                        exact_score=exact,
                        lexical_score=lexical,
                        vector_score=vector,
                        search_score=score,
                    )
                )
        return sorted(output, key=lambda x: x.search_score, reverse=True)[:top_k]
