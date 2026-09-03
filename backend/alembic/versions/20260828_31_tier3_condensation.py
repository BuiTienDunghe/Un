"""tier 3: condensation batches + propositions

memory_design.md §7.4-7.5. Two tables, not one integer cursor: §7.4 lists the
four cases a single ``last_condensed_message_id`` loses (edits, late
arrivals, threads, concurrent runs), so the batch carries status + lease the
same way discord_session_turns does, and coverage is marked PER MESSAGE via
discord_channel_messages.condensation_batch_id (a late message simply keeps
NULL and joins the next batch).

Propositions store the four fields §7.5 calls mandatory — content,
source_message_ids, speaker_id, said_at — which is also what makes §9.5's
hardest case (per-person deletion of a summary) a plain DELETE instead of an
irreversible loss.

Additive only: one nullable column on an existing table plus two new tables.
Downgrade drops them, which discards condensations but never raw messages.

Revision ID: 20260828_31
Revises: 20260828_30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY


revision = "20260828_31"
down_revision = "20260828_30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discord_channel_messages",
        sa.Column("condensation_batch_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_discord_channel_messages_uncondensed",
        "discord_channel_messages",
        ["guild_id", "channel_id", "sent_at"],
        postgresql_where=sa.text(
            "condensation_batch_id IS NULL AND deleted_at IS NULL"
        ),
    )

    op.create_table(
        "discord_condensation_batches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("guild_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("from_message_id", sa.Text(), nullable=False),
        sa.Column("to_message_id", sa.Text(), nullable=False),
        sa.Column("from_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("to_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("model_used", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed','stale','deleted')",
            name="ck_discord_condensation_batches_status",
        ),
        sa.CheckConstraint(
            "message_count > 0",
            name="ck_discord_condensation_batches_message_count",
        ),
        sa.UniqueConstraint(
            "channel_id",
            "from_message_id",
            name="uq_discord_condensation_batch_span",
        ),
    )
    op.create_index(
        "uq_discord_condensation_batch_one_running",
        "discord_condensation_batches",
        ["channel_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_discord_condensation_batches_dispatch",
        "discord_condensation_batches",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_discord_condensation_batches_guild_channel",
        "discord_condensation_batches",
        ["guild_id", "channel_id", "to_sent_at"],
    )

    op.create_table(
        "discord_condensation_propositions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("guild_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_message_ids", ARRAY(sa.Text()), nullable=False),
        sa.Column("speaker_id", sa.Text(), nullable=False),
        sa.Column("speaker_display_name", sa.Text(), nullable=True),
        sa.Column("said_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["discord_condensation_batches.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_discord_condensation_propositions_batch_id",
        "discord_condensation_propositions",
        ["batch_id"],
    )
    op.create_index(
        "ix_discord_condensation_propositions_read",
        "discord_condensation_propositions",
        ["guild_id", "channel_id", "said_at"],
    )
    op.create_index(
        "ix_discord_condensation_propositions_speaker",
        "discord_condensation_propositions",
        ["guild_id", "speaker_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discord_condensation_propositions_speaker",
        table_name="discord_condensation_propositions",
    )
    op.drop_index(
        "ix_discord_condensation_propositions_read",
        table_name="discord_condensation_propositions",
    )
    op.drop_index(
        "ix_discord_condensation_propositions_batch_id",
        table_name="discord_condensation_propositions",
    )
    op.drop_table("discord_condensation_propositions")
    op.drop_index(
        "ix_discord_condensation_batches_guild_channel",
        table_name="discord_condensation_batches",
    )
    op.drop_index(
        "ix_discord_condensation_batches_dispatch",
        table_name="discord_condensation_batches",
    )
    op.drop_index(
        "uq_discord_condensation_batch_one_running",
        table_name="discord_condensation_batches",
    )
    op.drop_table("discord_condensation_batches")
    op.drop_index(
        "ix_discord_channel_messages_uncondensed",
        table_name="discord_channel_messages",
    )
    op.drop_column("discord_channel_messages", "condensation_batch_id")
