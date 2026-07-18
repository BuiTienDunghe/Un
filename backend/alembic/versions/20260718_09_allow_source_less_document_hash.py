"""allow source-less legacy documents without fabricated hashes

Revision ID: 20260718_09
Revises: 20260718_08
"""
from alembic import op
import sqlalchemy as sa


revision = "20260718_09"
down_revision = "20260718_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("documents", "content_hash", existing_type=sa.String(length=64), nullable=True)


def downgrade() -> None:
    # Downgrade is intentionally blocked while source-less rows exist; forcing
    # an arbitrary hash would corrupt the migrated audit record.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM documents WHERE content_hash IS NULL) THEN
                RAISE EXCEPTION 'cannot restore NOT NULL content_hash while source-less documents exist';
            END IF;
        END $$;
    """)
    op.alter_column("documents", "content_hash", existing_type=sa.String(length=64), nullable=False)
