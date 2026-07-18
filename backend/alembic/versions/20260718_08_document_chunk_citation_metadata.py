"""preserve legacy document chunk citation metadata for Phase 5B

Revision ID: 20260718_08
Revises: 20260718_07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_08"
down_revision = "20260718_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("locations", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("document_chunks", sa.Column("heading_path", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "heading_path")
    op.drop_column("document_chunks", "locations")
