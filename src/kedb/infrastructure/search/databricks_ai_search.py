from uuid import UUID

from kedb.domain import RetrievalCandidate


class DatabricksAISearch:
    """LangChain vector store over the Databricks managed-embedding index."""

    def __init__(
        self,
        endpoint_name: str,
        index_name: str,
        workspace_url: str | None = None,
        token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        from databricks_langchain import DatabricksVectorSearch

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
        # The native integration infers the endpoint from the full index name.
        self.store = DatabricksVectorSearch(
            index_name=index_name,
            columns=["known_error_id", "article_version_id", "title",
                     "error_codes", "is_current", "status"],
            client_args=kwargs,
        )

    def search(
        self,
        query: str,
        exact_identifiers: list[str],
        top_k: int = 5,
        query_type: str = "HYBRID",
    ) -> list[RetrievalCandidate]:
        rows = self.store.similarity_search_with_score(
            query,
            k=top_k,
            query_type=query_type,
            filter={"is_current": True, "status": "PUBLISHED"},
        )
        candidates = []
        for document, score in rows:
            metadata = document.metadata
            error_codes = metadata.get("error_codes", [])
            haystack = " ".join(error_codes or []) if isinstance(error_codes, list) else str(error_codes or "")
            exact = 1.0 if any(identifier in haystack.upper() for identifier in exact_identifiers) else 0.0
            numeric_score = float(score)
            candidates.append(
                RetrievalCandidate(
                    known_error_id=UUID(str(metadata["known_error_id"])),
                    article_version_id=UUID(str(metadata["article_version_id"])),
                    title=metadata.get("title", ""),
                    exact_score=exact,
                    lexical_score=numeric_score if query_type == "FULL_TEXT" else 0.0,
                    vector_score=numeric_score if query_type == "ANN" else 0.0,
                    search_score=numeric_score,
                )
            )
        return candidates
