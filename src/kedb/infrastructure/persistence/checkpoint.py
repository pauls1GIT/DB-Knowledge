from langgraph.checkpoint.memory import InMemorySaver
from kedb.config import settings


def build_checkpointer():
    try:
        from psycopg import Connection
        from langgraph.checkpoint.postgres import PostgresSaver
        conn=Connection.connect(settings.langgraph_checkpoint_url, autocommit=True)
        saver=PostgresSaver(conn)
        saver.setup()
        saver._kedb_connection=conn
        return saver
    except Exception:
        # Local fallback lets unit tests/demo boot before PostgreSQL is available.
        return InMemorySaver()
