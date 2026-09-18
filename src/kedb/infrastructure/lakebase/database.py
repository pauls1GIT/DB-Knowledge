from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from kedb.infrastructure.lakebase.models import Base


class Database:
    """Database facade that uses Lakebase in Databricks and SQLite locally."""

    def __init__(self, local_url: str):
        if os.getenv("PGHOST"):
            self.mode = "lakebase"
            self.engine = self._create_lakebase_engine()
        else:
            self.mode = "sqlite"
            self.engine = create_engine(local_url, future=True)

        if self.engine.dialect.name == "sqlite":
            # Explicit transactions keep savepoints atomic with their outer transaction.
            @event.listens_for(self.engine, "connect")
            def sqlite_connect(connection, _record):
                connection.isolation_level = None

            @event.listens_for(self.engine, "begin")
            def sqlite_begin(connection):
                connection.exec_driver_sql("BEGIN")

        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)

    @staticmethod
    def _create_lakebase_engine():
        # Lazy imports keep local/unit-test mode independent from Databricks packages.
        import psycopg
        from databricks.sdk import WorkspaceClient

        workspace = WorkspaceClient()
        conninfo = " ".join(
            [
                f"dbname={os.environ.get('PGDATABASE', 'databricks_postgres')}",
                f"user={os.environ['PGUSER']}",
                f"host={os.environ['PGHOST']}",
                f"port={os.environ.get('PGPORT', '5432')}",
                f"sslmode={os.environ.get('PGSSLMODE', 'require')}",
            ]
        )

        def creator():
            endpoint = os.environ.get("ENDPOINT_NAME", "")
            if not endpoint or endpoint.startswith("CHANGE_ME"):
                raise RuntimeError(
                    "Lakebase is attached but ENDPOINT_NAME is not configured. "
                    "In Lakebase open the production branch -> Computes -> Get ID, "
                    "copy the endpoint resource name, and put it in app.yaml."
                )
            credential = workspace.postgres.generate_database_credential(endpoint=endpoint)
            return psycopg.connect(conninfo, password=credential.token)

        return create_engine(
            "postgresql+psycopg://",
            creator=creator,
            pool_pre_ping=True,
            pool_recycle=3000,
            future=True,
        )

    def create_all(self):
        Base.metadata.create_all(self.engine)

    def ping(self) -> bool:
        from sqlalchemy import text

        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
