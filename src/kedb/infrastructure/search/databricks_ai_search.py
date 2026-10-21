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
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        from databricks.ai_search.client import AISearchClient

        kwargs = {"disable_notice": True}
        if workspace_url:
            workspace_url = workspace_url.strip().rstrip("/")
            if "://" not in workspace_url:
                workspace_url = "https://" + workspace_url
            kwargs["workspace_url"] = workspace_url
        if token:
            kwargs["personal_access_token"] = token
        elif client_id and client_secret:
            kwargs["service_principal_client_id"] = client_id
            kwargs["service_principal_client_secret"] = client_secret
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
                    vector_score=numeric_score if query_type == "ANN" else 0.0,
                    search_score=numeric_score,
                )
            )
        return candidates

    def search_exact_identifier(
        self, identifier: str, top_k: int = 5
    ) -> list[RetrievalCandidate]:
        identifier = identifier.strip().upper()
        if not identifier:
            return []

        result = self.index.similarity_search(
            columns=[
                "known_error_id",
                "article_version_id",
                "title",
                "error_codes",
            ],
            num_results=top_k,
            filters={
                "error_codes": identifier,
                "is_current": True,
                "status": "PUBLISHED",
            },
        )

        rows = result.get("result", {}).get("data_array", [])
        candidates = []
        seen = set()

        for row in rows:
            known_error_id, version_id, title, error_codes, _score = row

            if identifier not in (error_codes or []):
                continue

            key = (known_error_id, version_id)
            if key in seen:
                continue
            seen.add(key)

            candidates.append(
                RetrievalCandidate(
                    known_error_id=UUID(known_error_id),
                    article_version_id=UUID(version_id),
                    title=title,
                    exact_score=1.0,
                    lexical_score=0.0,
                    vector_score=0.0,
                    search_score=1.0,
                    final_score=1.0,
                    rank=len(candidates) + 1,
                )
            )

        return candidates
