"""Persist the citations of a RAG answer alongside its message.

Before this revision the sources were only ever sent in the HTTP response, so
reopening a stored conversation showed the answer without the passages it was
grounded in.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260818_20"
down_revision = "20260813_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_sources",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("chunk_id", sa.String(length=128), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "position", name="uq_message_sources_position"),
    )
    op.create_index("ix_message_sources_message_id", "message_sources", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_message_sources_message_id", table_name="message_sources")
    op.drop_table("message_sources")
