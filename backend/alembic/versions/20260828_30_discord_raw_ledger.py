"""job 1+2: raw message ledger (sổ gốc) + channel listening policy

The three §12 decisions were made 28/08 (see .scratch/five-steps-hardening/
SPEC.md and memory_design.md §13):
- §9.3 is_bot: bot rows ARE stored, tagged is_bot — the condensation tier
  needs them; memory extraction never consumes them.
- §5.3 content_original: the table is append-only in STRUCTURE (invariant
  #3); the content cell is mutable. An edit moves the first version into
  content_original exactly once; a Discord delete clears both texts and
  stamps deleted_at, keeping the row skeleton for audit.
- §9.5 deletion: soft delete via deleted_at + text clearing at event time;
  per-person hard delete is a plain DELETE by author_id — the FTS index is
  per-row (no rebuild), which is why §13.5 option (c) won.

sent_at is derived from the snowflake at write time (§5.2). content_tokens
is a 'simple'-config tsvector over tokenize_vietnamese output — incremental,
no rebuild-on-read cliff (§13.5: 4.6s/year projected for BM25 vs milliseconds
here).

Additive only: two new tables, nothing existing is touched. Downgrade drops
them (and with them any passively collected rows — acceptable while the env
var remains the operational listening switch).

Revision ID: 20260828_30
Revises: 20260828_29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR


revision = "20260828_30"
down_revision = "20260828_29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discord_channel_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("guild_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=True),
        sa.Column("discord_message_id", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Text(), nullable=False),
        sa.Column("author_display_name", sa.Text(), nullable=False),
        sa.Column(
            "is_bot",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_original", sa.Text(), nullable=True),
        sa.Column("content_tokens", TSVECTOR(), nullable=True),
        sa.Column("reply_to_message_id", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "discord_message_id",
            name="uq_discord_channel_messages_message",
        ),
    )
    op.create_index(
        "ix_discord_channel_messages_guild_channel_sent",
        "discord_channel_messages",
        ["guild_id", "channel_id", "sent_at"],
    )
    op.create_index(
        "ix_discord_channel_messages_guild_author_sent",
        "discord_channel_messages",
        ["guild_id", "author_id", "sent_at"],
    )
    op.create_index(
        "ix_discord_channel_messages_content_tokens",
        "discord_channel_messages",
        ["content_tokens"],
        postgresql_using="gin",
    )

    op.create_table(
        "discord_channel_policies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("guild_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column(
            "listening_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("enabled_by", sa.Text(), nullable=False),
        sa.Column(
            "enabled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "guild_id",
            "channel_id",
            name="uq_discord_channel_policies_channel",
        ),
    )


def downgrade() -> None:
    op.drop_table("discord_channel_policies")
    op.drop_index(
        "ix_discord_channel_messages_content_tokens",
        table_name="discord_channel_messages",
    )
    op.drop_index(
        "ix_discord_channel_messages_guild_author_sent",
        table_name="discord_channel_messages",
    )
    op.drop_index(
        "ix_discord_channel_messages_guild_channel_sent",
        table_name="discord_channel_messages",
    )
    op.drop_table("discord_channel_messages")
