"""add normalized display filename identity for upload decisions

Revision ID: 20260719_10
Revises: 20260718_09
"""
from alembic import op
import sqlalchemy as sa


revision = "20260719_10"
down_revision = "20260718_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("display_filename_normalized", sa.String(length=1024), nullable=True))
    op.execute("UPDATE documents SET display_filename_normalized = lower(trim(original_filename)) WHERE status != 'deleted'")
    op.create_unique_constraint("uq_documents_display_filename_normalized", "documents", ["display_filename_normalized"])
    op.create_index("ix_documents_display_filename_normalized", "documents", ["display_filename_normalized"])


def downgrade() -> None:
    op.drop_index("ix_documents_display_filename_normalized", table_name="documents")
    op.drop_constraint("uq_documents_display_filename_normalized", "documents", type_="unique")
    op.drop_column("documents", "display_filename_normalized")
