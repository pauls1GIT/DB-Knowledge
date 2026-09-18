from uuid import UUID

from kedb.domain import RetrievalCandidate


class DatabricksAISearch:
    """Databricks AI Search adapter supporting ANN, FULL_TEXT and HYBRID query modes."""

    def __init__(
        self,
        endpoint_name: str,
        index_name: str,
        workspace_url: str | None = None,
        token: str | None = None,
    ):
        from databricks.ai_search.client import AISearchClient

        kwargs = {"disable_notice": True}
        if workspace_url:
            kwargs["workspace_url"] = workspace_url
        if token:
            kwargs["personal_access_token"] = token
        self.client = AISearchClient(**kwargs)
        self.index = self.client.get_index(endpoint_name=endpoint_name, index_name=index_name)

    def search(
        self,
        query: str,
        exact_identifiers: list[str],
        top_k: int = 5,
        query_type: str = "HYBRID",
    ) -> list[RetrievalCandidate]:
        result = self.index.similarity_search(
            query_text=query,
            columns=[
                "known_error_id",
                "article_version_id",
                "title",
                "content",
                "error_codes",
                "is_current",
                "status",
            ],
            num_results=top_k,
            query_type=query_type,
            filters={"is_current": True, "status": "PUBLISHED"},
        )
        rows = result.get("result", {}).get("data_array", [])
        candidates = []
        for row in rows:
            known_error_id, version_id, title, _content, error_codes, _cur, _status, score = row
            haystack = " ".join(error_codes or []) if isinstance(error_codes, list) else str(error_codes or "")
            exact = 1.0 if any(identifier in haystack.upper() for identifier in exact_identifiers) else 0.0
            numeric_score = float(score)
            candidates.append(
                RetrievalCandidate(
                    known_error_id=UUID(known_error_id),
                    article_version_id=UUID(version_id),
                    title=title,
                    exact_score=exact,
                    lexical_score=numeric_score if query_type == "FULL_TEXT" else 0.0,
                    vector_score=numeric_score if query_type in {"ANN", "HYBRID"} else 0.0,
                    search_score=numeric_score,
                )
            )
        return candidates
