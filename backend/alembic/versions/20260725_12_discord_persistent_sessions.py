"""persistent Discord sessions and FIFO turn foundation

Revision ID: 20260725_12
Revises: 20260719_11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260725_12"
down_revision = "20260719_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discord_conversation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guild_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=True),
        sa.Column("backend_conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False, server_default=sa.text("'discord'")),
        sa.Column("visibility", sa.Text(), nullable=False, server_default=sa.text("'internal'")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orphaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active','closed','expired','orphaned','deleted')", name="ck_discord_conversation_sessions_status"),
        sa.CheckConstraint("origin = 'discord'", name="ck_discord_conversation_sessions_origin"),
        sa.CheckConstraint("visibility IN ('internal','admin')", name="ck_discord_conversation_sessions_visibility"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_discord_active_channel_session",
        "discord_conversation_sessions",
        ["guild_id", "channel_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND thread_id IS NULL"),
    )
    op.create_index(
        "uq_discord_active_thread_session",
        "discord_conversation_sessions",
        ["guild_id", "channel_id", "thread_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND thread_id IS NOT NULL"),
    )
    op.create_index(
        "ix_discord_session_canonical_lookup",
        "discord_conversation_sessions",
        ["guild_id", "channel_id", "thread_id", "status"],
    )
    op.create_index(
        "ix_discord_session_backend_conversation",
        "discord_conversation_sessions",
        ["backend_conversation_id"],
    )

    op.create_table(
        "discord_session_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("discord_message_id", sa.Text(), nullable=False),
        sa.Column("sequence_number", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_discord_session_turns_status"),
        sa.CheckConstraint("sequence_number > 0", name="ck_discord_session_turns_positive_sequence"),
        sa.ForeignKeyConstraint(["session_id"], ["discord_conversation_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "discord_message_id", name="uq_discord_session_turn_message"),
        sa.UniqueConstraint("session_id", "sequence_number", name="uq_discord_session_turn_sequence"),
    )
    op.create_index(
        "uq_discord_session_turn_one_running",
        "discord_session_turns",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_discord_session_turn_dispatch",
        "discord_session_turns",
        ["status", "available_at", "session_id", "sequence_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_discord_session_turn_dispatch", table_name="discord_session_turns")
    op.drop_index("uq_discord_session_turn_one_running", table_name="discord_session_turns")
    op.drop_table("discord_session_turns")
    op.drop_index("ix_discord_session_backend_conversation", table_name="discord_conversation_sessions")
    op.drop_index("ix_discord_session_canonical_lookup", table_name="discord_conversation_sessions")
    op.drop_index("uq_discord_active_thread_session", table_name="discord_conversation_sessions")
    op.drop_index("uq_discord_active_channel_session", table_name="discord_conversation_sessions")
    op.drop_table("discord_conversation_sessions")
