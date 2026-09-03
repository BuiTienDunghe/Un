"""raw ledger: Discord's own edit timestamp as an ordering token

``edited_at`` is our receipt stamp — the moment the backend processed an
edit — so two edits of the same message in flight at once are ordered by HTTP
arrival, not by what the member typed last (review finding 28/08). Discord's
``edited_timestamp`` is the only monotonic token for that, and it now has its
own column so the receipt keeps its meaning.

Additive only: one nullable column. NULL means "no Discord token seen yet",
under which record_edit behaves exactly as before.

Revision ID: 20260828_32
Revises: 20260828_31
"""

import sqlalchemy as sa
from alembic import op


revision = "20260828_32"
down_revision = "20260828_31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discord_channel_messages",
        sa.Column("source_edited_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("discord_channel_messages", "source_edited_at")
