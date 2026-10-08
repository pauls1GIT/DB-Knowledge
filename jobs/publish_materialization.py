"""Optional one-shot outbox consumer; the app also runs this in the background.

Use the same PG*/ENDPOINT_NAME authentication as the app, plus
DATABRICKS_WAREHOUSE_ID and KEDB_UC_CHUNK_TABLE. Run with PYTHONPATH=src.
"""
from kedb.config import Settings
from kedb.infrastructure.lakebase import Database
from kedb.infrastructure.delta.sql_chunks import SqlChunkSink
from kedb.application.use_cases.materialize import MaterializePublications


def main():
    settings = Settings()
    database = Database(settings.kedb_database_url)
    sink = SqlChunkSink(warehouse_id=settings.databricks_warehouse_id,
                        table=settings.kedb_uc_chunk_table,
                        index_name=settings.databricks_ai_search_index)
    materializer = MaterializePublications(database, sink)
    total = 0
    while count := materializer.run_once():
        total += count
    print(f"Materialized {total} publication event(s)")


if __name__ == "__main__":
    main()
