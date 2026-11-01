"""Tool calls kept for a person to approve before they run (ticket 46).

Additive only: one new table. A row holds the arguments the model wrote (the member's words) and the
member's id, so it goes with the turn it was asked in (FK cascade) and with forget_member
(scripts/forget_member.py). Nothing reads it while DISCORD_APPROVALS_ENABLED is off.

Revision ID: 20261102_38
Revises: 20261101_37
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261102_38"
down_revision = "20261101_37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discord_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("guild_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text()),
        sa.Column("requester_id", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("arguments", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("result_code", sa.Text()),
        # Deleting the turn deletes the approval asked in it (nothing in app/ deletes a turn; forget_member clears by member).
        sa.Column("source_turn_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("discord_session_turns.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending','running','done','failed','denied','expired')",
            name="ck_discord_approvals_status",
        ),
    )
    op.create_index("ix_discord_approvals_status_expires", "discord_approvals", ["status", "expires_at"])
    op.create_index("ix_discord_approvals_requester", "discord_approvals", ["guild_id", "requester_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_discord_approvals_requester", table_name="discord_approvals")
    op.drop_index("ix_discord_approvals_status_expires", table_name="discord_approvals")
    op.drop_table("discord_approvals")
