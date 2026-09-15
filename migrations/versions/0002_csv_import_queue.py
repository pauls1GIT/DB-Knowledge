"""CSV import queue and richer Jira fields
Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jira_issue", sa.Column("external_id", sa.String(length=64), nullable=True))
    op.add_column("jira_issue", sa.Column("status", sa.String(length=64), nullable=True))
    op.add_column("jira_issue", sa.Column("priority", sa.String(length=64), nullable=True))
    op.add_column("jira_issue", sa.Column("issue_type", sa.String(length=64), nullable=True))
    op.add_column("jira_issue", sa.Column("environment", sa.Text(), nullable=True))
    op.add_column("jira_issue", sa.Column("parent_external_key", sa.String(length=64), nullable=True))
    op.add_column("jira_issue", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jira_issue", sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jira_issue", sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jira_issue", sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index("ix_jira_issue_status", "jira_issue", ["status"], unique=False)

    op.create_table(
        "import_batch",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="IMPORTING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_import_batch_status", "import_batch", ["status"], unique=False)

    op.create_table(
        "import_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("import_batch.id"), nullable=False),
        sa.Column("jira_issue_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jira_issue.id"), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("import_batch_id", "row_number"),
    )
    op.create_index("ix_import_item_import_batch_id", "import_item", ["import_batch_id"], unique=False)
    op.create_index("ix_import_item_jira_issue_id", "import_item", ["jira_issue_id"], unique=False)
    op.create_index("ix_import_item_status", "import_item", ["status"], unique=False)
    op.create_index("ix_import_item_workflow_id", "import_item", ["workflow_id"], unique=False)


def downgrade():
    op.drop_table("import_item")
    op.drop_table("import_batch")
    op.drop_index("ix_jira_issue_status", table_name="jira_issue")
    for name in ["raw_payload", "source_updated_at", "source_created_at", "resolved_at", "parent_external_key", "environment", "issue_type", "priority", "status", "external_id"]:
        op.drop_column("jira_issue", name)
