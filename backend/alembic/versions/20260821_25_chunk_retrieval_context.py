"""Chunk retrieval context for contextual retrieval (P4-2).

One nullable text column on document_chunks: the generated 50-100 token
situating context that the embedding and the BM25 index see in front of the
chunk. NULL means "index the bare content", which keeps every existing
version valid — old versions simply have no context until re-indexed, and
citations always show `content`, never the generated text.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260821_25"
down_revision = "20260820_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("retrieval_context", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "retrieval_context")
