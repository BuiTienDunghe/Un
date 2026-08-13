"""Server-side conversation titles for the web UI conversation list."""

from alembic import op
import sqlalchemy as sa

revision = "20260813_19"
down_revision = "20260728_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("title", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "title")
