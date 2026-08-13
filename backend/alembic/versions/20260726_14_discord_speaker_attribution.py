"""Discord speaker attribution metadata

Revision ID: 20260726_14
Revises: 20260725_13
"""
from alembic import op
import sqlalchemy as sa


revision = "20260726_14"
down_revision = "20260725_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable by design: the five production turns created before Sprint 2A
    # do not contain trustworthy author metadata and must not be guessed.
    op.add_column(
        "discord_session_turns",
        sa.Column("author_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "discord_session_turns",
        sa.Column("author_display_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "discord_session_turns",
        sa.Column("reply_to_discord_message_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("discord_session_turns", "reply_to_discord_message_id")
    op.drop_column("discord_session_turns", "author_display_name")
    op.drop_column("discord_session_turns", "author_id")
