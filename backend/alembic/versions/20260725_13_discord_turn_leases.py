"""durable Discord turn leases and execution payload

Revision ID: 20260725_13
Revises: 20260725_12
"""
from alembic import op
import sqlalchemy as sa


revision = "20260725_13"
down_revision = "20260725_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("discord_session_turns", sa.Column("request_text", sa.Text(), nullable=True))
    op.add_column("discord_session_turns", sa.Column("system_prompt", sa.Text(), nullable=True))
    op.add_column("discord_session_turns", sa.Column("response_text", sa.Text(), nullable=True))
    op.add_column("discord_session_turns", sa.Column("model_used", sa.String(length=255), nullable=True))
    op.add_column("discord_session_turns", sa.Column("worker_id", sa.Text(), nullable=True))
    op.add_column("discord_session_turns", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("discord_session_turns", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "discord_session_turns",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "discord_session_turns",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
    )
    op.execute("UPDATE discord_session_turns SET request_text = '' WHERE request_text IS NULL")
    op.alter_column("discord_session_turns", "request_text", nullable=False)
    op.create_check_constraint(
        "ck_discord_session_turns_attempt_count",
        "discord_session_turns",
        "attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_discord_session_turns_max_attempts",
        "discord_session_turns",
        "max_attempts > 0",
    )
    op.create_index(
        "ix_discord_session_turn_stale_lease",
        "discord_session_turns",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("ix_discord_session_turn_stale_lease", table_name="discord_session_turns")
    op.drop_constraint(
        "ck_discord_session_turns_max_attempts",
        "discord_session_turns",
        type_="check",
    )
    op.drop_constraint(
        "ck_discord_session_turns_attempt_count",
        "discord_session_turns",
        type_="check",
    )
    op.drop_column("discord_session_turns", "max_attempts")
    op.drop_column("discord_session_turns", "attempt_count")
    op.drop_column("discord_session_turns", "heartbeat_at")
    op.drop_column("discord_session_turns", "lease_expires_at")
    op.drop_column("discord_session_turns", "worker_id")
    op.drop_column("discord_session_turns", "model_used")
    op.drop_column("discord_session_turns", "response_text")
    op.drop_column("discord_session_turns", "system_prompt")
    op.drop_column("discord_session_turns", "request_text")
