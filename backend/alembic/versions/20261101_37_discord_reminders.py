"""Reminders a member asked Ún to send later, in the channel they asked in.

Additive only: one new table. A reminder holds the member's own words and id, so it goes with the turn it was
made in (FK cascade) and with forget_member (scripts/forget_member.py). Nothing reads it while DISCORD_REMINDERS_ENABLED is off.

Revision ID: 20261101_37
Revises: 20261030_36
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261101_37"
down_revision = "20261030_36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discord_reminders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("guild_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text()),
        sa.Column("creator_id", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("discord_message_id", sa.Text()),
        sa.Column("error", sa.Text()),
        # Deleting the turn (a deleted conversation, forget_member) deletes the reminder made in it.
        sa.Column("source_turn_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("discord_session_turns.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending','sending','sent','failed','missed','cancelled')",
            name="ck_discord_reminders_status",
        ),
    )
    op.create_index("ix_discord_reminders_status_due", "discord_reminders", ["status", "due_at"])
    op.create_index("ix_discord_reminders_creator", "discord_reminders", ["guild_id", "creator_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_discord_reminders_creator", table_name="discord_reminders")
    op.drop_index("ix_discord_reminders_status_due", table_name="discord_reminders")
    op.drop_table("discord_reminders")
