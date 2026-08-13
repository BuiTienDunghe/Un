"""add isolated PostgreSQL Discord memory foundation

Revision ID: 20260728_16
Revises: 20260728_15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.postgres.discord_memory_constants import (
    DISCORD_MEMORY_CANDIDATE_DECISIONS_V1,
    DISCORD_MEMORY_FILTER_DECISIONS_V1,
    DISCORD_MEMORY_INDEX_STATUSES_V1,
    DISCORD_MEMORY_OPERATIONS_V1,
    DISCORD_MEMORY_SCOPES_V1,
    DISCORD_MEMORY_SOURCE_ROLES_V1,
    DISCORD_MEMORY_STATUSES_V1,
    DISCORD_MEMORY_VALIDATION_STATUSES_V1,
)


revision = "20260728_16"
down_revision = "20260728_15"
branch_labels = None
depends_on = None


def _quoted(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def upgrade() -> None:
    # Create candidates without target_memory_id's FK first. The FK is added
    # after discord_memories exists to preserve both sides of the audit link.
    op.create_table(
        "discord_memory_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_discord_message_id", sa.Text(), nullable=False),
        sa.Column("source_author_id", sa.Text(), nullable=False),
        sa.Column("source_author_display_name", sa.Text(), nullable=True),
        sa.Column("guild_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=True),
        sa.Column("extractor_schema_version", sa.Text(), nullable=False),
        sa.Column("extractor_model", sa.Text(), nullable=True),
        sa.Column("filter_decision", sa.Text(), nullable=False),
        sa.Column("filter_reason_code", sa.Text(), nullable=False),
        sa.Column("raw_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("normalized_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("operation", sa.Text(), nullable=True),
        sa.Column("memory_type", sa.Text(), nullable=True),
        sa.Column("subject_type", sa.Text(), nullable=True),
        sa.Column("subject_id", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("fact_key", sa.Text(), nullable=True),
        sa.Column("canonical_fact", sa.Text(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("target_memory_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("validation_status", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("conflict_key", sa.Text(), nullable=True),
        sa.Column("proposed_value_hash", sa.Text(), nullable=True),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
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
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_discord_memory_candidates_confidence",
        ),
        sa.CheckConstraint(
            f"operation IS NULL OR operation IN ({_quoted(DISCORD_MEMORY_OPERATIONS_V1)})",
            name="ck_discord_memory_candidates_operation",
        ),
        sa.CheckConstraint(
            f"scope IS NULL OR scope IN ({_quoted(DISCORD_MEMORY_SCOPES_V1)})",
            name="ck_discord_memory_candidates_scope",
        ),
        sa.CheckConstraint(
            f"filter_decision IN ({_quoted(DISCORD_MEMORY_FILTER_DECISIONS_V1)})",
            name="ck_discord_memory_candidates_filter_decision",
        ),
        sa.CheckConstraint(
            f"validation_status IN ({_quoted(DISCORD_MEMORY_VALIDATION_STATUSES_V1)})",
            name="ck_discord_memory_candidates_validation_status",
        ),
        sa.CheckConstraint(
            f"decision IN ({_quoted(DISCORD_MEMORY_CANDIDATE_DECISIONS_V1)})",
            name="ck_discord_memory_candidates_decision",
        ),
        sa.ForeignKeyConstraint(
            ["source_turn_id"],
            ["discord_session_turns.id"],
            name="fk_discord_memory_candidates_source_turn",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["discord_conversation_sessions.id"],
            name="fk_discord_memory_candidates_session",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_turn_id",
            "extractor_schema_version",
            name="uq_discord_memory_candidate_turn_schema",
        ),
        sa.UniqueConstraint(
            "source_discord_message_id",
            "extractor_schema_version",
            name="uq_discord_memory_candidate_message_schema",
        ),
    )
    op.create_index(
        "ix_discord_memory_candidates_decision_not_before",
        "discord_memory_candidates",
        ["decision", "not_before"],
    )
    op.create_index(
        "ix_discord_memory_candidates_conflict_decision_created",
        "discord_memory_candidates",
        ["conflict_key", "decision", "created_at"],
    )
    op.create_index(
        "ix_discord_memory_candidates_expires_at",
        "discord_memory_candidates",
        ["expires_at"],
    )
    op.create_index(
        "ix_discord_memory_candidates_guild_author_created",
        "discord_memory_candidates",
        ["guild_id", "source_author_id", "created_at"],
    )

    op.create_table(
        "discord_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guild_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=True),
        sa.Column("thread_id", sa.Text(), nullable=True),
        sa.Column("memory_type", sa.Text(), nullable=False),
        sa.Column("fact_key", sa.Text(), nullable=False),
        sa.Column("canonical_fact", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("origin_candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supersedes_memory_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extractor_model", sa.Text(), nullable=False),
        sa.Column("extractor_schema_version", sa.Text(), nullable=False),
        sa.Column("validation_status", sa.Text(), nullable=False),
        sa.Column("index_status", sa.Text(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_error", sa.Text(), nullable=True),
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
            "version >= 1",
            name="ck_discord_memories_version",
        ),
        sa.CheckConstraint(
            f"status IN ({_quoted(DISCORD_MEMORY_STATUSES_V1)})",
            name="ck_discord_memories_status",
        ),
        sa.CheckConstraint(
            f"scope IN ({_quoted(DISCORD_MEMORY_SCOPES_V1)})",
            name="ck_discord_memories_scope",
        ),
        sa.CheckConstraint(
            f"index_status IN ({_quoted(DISCORD_MEMORY_INDEX_STATUSES_V1)})",
            name="ck_discord_memories_index_status",
        ),
        sa.CheckConstraint(
            f"validation_status IN ({_quoted(DISCORD_MEMORY_VALIDATION_STATUSES_V1)})",
            name="ck_discord_memories_validation_status",
        ),
        sa.CheckConstraint(
            "("
            "(scope IN ('member_in_guild','guild') AND channel_id IS NULL AND thread_id IS NULL)"
            " OR (scope = 'channel' AND channel_id IS NOT NULL AND thread_id IS NULL)"
            " OR (scope = 'thread' AND channel_id IS NOT NULL AND thread_id IS NOT NULL)"
            ")",
            name="ck_discord_memories_scope_location",
        ),
        sa.ForeignKeyConstraint(
            ["origin_candidate_id"],
            ["discord_memory_candidates.id"],
            name="fk_discord_memories_origin_candidate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_memory_id"],
            ["discord_memories.id"],
            name="fk_discord_memories_supersedes",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "origin_candidate_id",
            name="uq_discord_memories_origin_candidate",
        ),
    )

    active_predicates = {
        "member": "status = 'active' AND scope = 'member_in_guild'",
        "guild": "status = 'active' AND scope = 'guild'",
        "channel": "status = 'active' AND scope = 'channel'",
        "thread": "status = 'active' AND scope = 'thread'",
    }
    op.create_index(
        "uq_discord_memory_active_member",
        "discord_memories",
        ["guild_id", "subject_type", "subject_id", "fact_key"],
        unique=True,
        postgresql_where=sa.text(active_predicates["member"]),
    )
    op.create_index(
        "uq_discord_memory_active_guild",
        "discord_memories",
        ["guild_id", "subject_type", "subject_id", "fact_key"],
        unique=True,
        postgresql_where=sa.text(active_predicates["guild"]),
    )
    op.create_index(
        "uq_discord_memory_active_channel",
        "discord_memories",
        ["guild_id", "channel_id", "subject_type", "subject_id", "fact_key"],
        unique=True,
        postgresql_where=sa.text(active_predicates["channel"]),
    )
    op.create_index(
        "uq_discord_memory_active_thread",
        "discord_memories",
        ["guild_id", "channel_id", "thread_id", "subject_type", "subject_id", "fact_key"],
        unique=True,
        postgresql_where=sa.text(active_predicates["thread"]),
    )

    version_specs = (
        (
            "uq_discord_memory_member_version",
            ["guild_id", "subject_type", "subject_id", "fact_key", "version"],
            "scope = 'member_in_guild'",
        ),
        (
            "uq_discord_memory_guild_version",
            ["guild_id", "subject_type", "subject_id", "fact_key", "version"],
            "scope = 'guild'",
        ),
        (
            "uq_discord_memory_channel_version",
            ["guild_id", "channel_id", "subject_type", "subject_id", "fact_key", "version"],
            "scope = 'channel'",
        ),
        (
            "uq_discord_memory_thread_version",
            ["guild_id", "channel_id", "thread_id", "subject_type", "subject_id", "fact_key", "version"],
            "scope = 'thread'",
        ),
    )
    for name, columns, predicate in version_specs:
        op.create_index(
            name,
            "discord_memories",
            columns,
            unique=True,
            postgresql_where=sa.text(predicate),
        )

    op.create_foreign_key(
        "fk_discord_memory_candidates_target_memory",
        "discord_memory_candidates",
        "discord_memories",
        ["target_memory_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "discord_memory_sources",
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_discord_message_id", sa.Text(), nullable=False),
        sa.Column("source_author_id", sa.Text(), nullable=False),
        sa.Column("source_role", sa.Text(), nullable=False),
        sa.Column("evidence_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            f"source_role IN ({_quoted(DISCORD_MEMORY_SOURCE_ROLES_V1)})",
            name="ck_discord_memory_sources_role",
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["discord_memories.id"],
            name="fk_discord_memory_sources_memory",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["discord_memory_candidates.id"],
            name="fk_discord_memory_sources_candidate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_turn_id"],
            ["discord_session_turns.id"],
            name="fk_discord_memory_sources_turn",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "memory_id",
            "candidate_id",
            "source_turn_id",
            "source_role",
            name="pk_discord_memory_sources",
        ),
        sa.UniqueConstraint(
            "memory_id",
            "source_turn_id",
            "source_role",
            name="uq_discord_memory_source_role",
        ),
    )


def downgrade() -> None:
    op.drop_table("discord_memory_sources")
    op.drop_constraint(
        "fk_discord_memory_candidates_target_memory",
        "discord_memory_candidates",
        type_="foreignkey",
    )
    op.drop_table("discord_memories")
    op.drop_table("discord_memory_candidates")
