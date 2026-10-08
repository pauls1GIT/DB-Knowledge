"""Write Delta chunks through a SQL warehouse; no Spark runtime required in the app."""
from __future__ import annotations

import json
import re
import time


class SqlChunkSink:
    def __init__(self, *, warehouse_id, table, index_name="", workspace=None):
        if not warehouse_id:
            raise ValueError("DATABRICKS_WAREHOUSE_ID is required to materialize article chunks")
        parts = table.split(".")
        if len(parts) != 3 or not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in parts):
            raise ValueError("KEDB_UC_CHUNK_TABLE must be catalog.schema.table")
        self.table = ".".join(f"`{part}`" for part in parts)
        self.warehouse_id = warehouse_id
        self.index_name = index_name
        self._workspace = workspace

    @property
    def workspace(self):
        if self._workspace is None:
            from databricks.sdk import WorkspaceClient
            self._workspace = WorkspaceClient()
        return self._workspace

    def execute(self, statement, parameters):
        from databricks.sdk.service.sql import StatementParameterListItem
        response = self.workspace.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id, statement=statement, wait_timeout="50s",
            parameters=[StatementParameterListItem(name=key, value=value, type="STRING")
                        for key, value in parameters.items()])
        deadline = time.monotonic() + 300
        while response.status and response.status.state.value in {"PENDING", "RUNNING"}:
            if time.monotonic() >= deadline:
                self.workspace.statement_execution.cancel_execution(response.statement_id)
                raise TimeoutError("Chunk SQL statement exceeded five minutes")
            time.sleep(1)
            response = self.workspace.statement_execution.get_statement(response.statement_id)
        if not response.status or response.status.state.value != "SUCCEEDED":
            error = response.status.error if response.status else None
            raise RuntimeError(f"Chunk SQL failed: {error}")

    def write(self, rows):
        if not rows:
            return
        schema = ("ARRAY<STRUCT<chunk_id:STRING,known_error_id:STRING,article_version_id:STRING,"
                  "version_number:INT,title:STRING,section:STRING,content:STRING,error_codes:ARRAY<STRING>,"
                  "source_jira_issue_id:STRING,review_id:STRING,status:STRING,is_current:BOOLEAN,"
                  "published_at:STRING,content_hash:STRING>>")
        keys = sorted({row["known_error_id"] for row in rows})
        params = {"payload": json.dumps(rows), **{f"ke{i}": key for i, key in enumerate(keys)}}
        key_sql = ", ".join(f":ke{i}" for i in range(len(keys)))
        self.execute(f"""
            MERGE INTO {self.table} t
            USING (
                SELECT r.chunk_id, r.known_error_id, r.article_version_id, r.version_number,
                       r.title, r.section, r.content, r.error_codes, r.source_jira_issue_id,
                       r.review_id, r.status, r.is_current,
                       CAST(r.published_at AS TIMESTAMP) AS published_at, r.content_hash
                FROM (SELECT explode(from_json(:payload, '{schema}')) AS r)
            ) s ON t.article_version_id = s.article_version_id AND t.section = s.section
            WHEN MATCHED THEN UPDATE SET *
            WHEN NOT MATCHED THEN INSERT *
            WHEN NOT MATCHED BY SOURCE AND t.known_error_id IN ({key_sql})
                THEN UPDATE SET t.is_current = false
        """, params)

    def sync(self):
        if self.index_name:
            self.workspace.vector_search_indexes.sync_index(index_name=self.index_name)
