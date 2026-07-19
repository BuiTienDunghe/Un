"""allow keep-both uploads with generated display names

Revision ID: 20260719_11
Revises: 20260719_10
"""
from alembic import op


revision = "20260719_11"
down_revision = "20260719_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_documents_display_filename_normalized", "documents", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("uq_documents_display_filename_normalized", "documents", ["display_filename_normalized"])
