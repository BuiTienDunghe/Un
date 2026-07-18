"""phase 2 document retention and active-version indexes

Revision ID: 20260717_02
Revises: 20260717_01
"""

from alembic import op
import sqlalchemy as sa

revision = "20260717_02"
down_revision = "20260717_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("source_removed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("documents", sa.Column("retention_policy", sa.String(length=32), nullable=False, server_default="permanent"))
    op.create_index("ix_documents_active_version_id", "documents", ["active_version_id"])
    op.create_index("ix_document_chunks_version_id", "document_chunks", ["version_id"])


def downgrade() -> None:
    op.drop_index("ix_document_chunks_version_id", table_name="document_chunks")
    op.drop_index("ix_documents_active_version_id", table_name="documents")
    op.drop_column("documents", "retention_policy")
    op.drop_column("documents", "pinned")
    op.drop_column("documents", "source_removed_at")
