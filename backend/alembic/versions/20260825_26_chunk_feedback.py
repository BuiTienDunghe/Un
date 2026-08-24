"""chunk_feedback: marks on chunks that survive a reindex (P4-5 phase 2).

A flag column on document_chunks would silently lose every mark: replace_chunks
deletes and recreates the chunk rows on each reindex. So marks live in their
own table, keyed by chunk_uid (stable within a version) and carrying the
chunk's content_hash — the bridge across reindexing: a new version whose chunk
has identical content can be matched back to its old marks, while a chunk
whose content changed is genuinely a different chunk and old marks stop
applying.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260825_26"
down_revision = "20260821_25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chunk_feedback",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("chunk_uid", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.String(length=128), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=32), nullable=False, server_default="bad"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_chunk_feedback_chunk_uid", "chunk_feedback", ["chunk_uid"])
    op.create_index("ix_chunk_feedback_document_id", "chunk_feedback", ["document_id"])
    # One mark per chunk per label: marking twice is idempotent, not a pile-up.
    op.create_unique_constraint("uq_chunk_feedback_uid_label", "chunk_feedback", ["chunk_uid", "label"])


def downgrade() -> None:
    op.drop_table("chunk_feedback")
