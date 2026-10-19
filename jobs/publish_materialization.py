"""Optional one-shot outbox consumer; the app also runs this in the background.

Use the same PG*/ENDPOINT_NAME authentication as the app, plus
DATABRICKS_WAREHOUSE_ID and KEDB_UC_CHUNK_TABLE. Run with PYTHONPATH=src.
"""
import argparse
from uuid import UUID

from kedb.config import Settings
from kedb.infrastructure.lakebase import Database
from kedb.infrastructure.delta.sql_chunks import SqlChunkSink
from kedb.application.use_cases.materialize import MaterializePublications


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    replay = parser.add_mutually_exclusive_group()
    replay.add_argument("--rebuild-current", action="store_true",
                        help="Requeue all current published articles, including processed/missing events")
    replay.add_argument("--article-version-id", type=UUID,
                        help="Requeue one current published article")
    args = parser.parse_args()
    settings = Settings()
    if not settings.databricks_ai_search_index:
        parser.error("DATABRICKS_AI_SEARCH_INDEX is required to request search indexing")
    database = Database(settings.kedb_database_url)
    sink = SqlChunkSink(warehouse_id=settings.databricks_warehouse_id,
                        table=settings.kedb_uc_chunk_table,
                        index_name=settings.databricks_ai_search_index)
    materializer = MaterializePublications(database, sink)
    print(f"Destination: {settings.kedb_uc_chunk_table}; index: {settings.databricks_ai_search_index}")
    if args.rebuild_current or args.article_version_id:
        count = materializer.requeue_current(args.article_version_id)
        print(f"Requeued {count} current published article(s)")
    total = 0
    while count := materializer.run_once():
        total += count
    print(f"Materialized {total} publication event(s); index sync requested, completion not verified")


if __name__ == "__main__":
    main()
