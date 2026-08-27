from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.postgres.discord_memory_constants import (
    DISCORD_MEMORY_CANDIDATE_VALIDATION_STATUSES_V2,
    DISCORD_MEMORY_CANDIDATE_DECISIONS_V1,
    DISCORD_MEMORY_FILTER_DECISIONS_V3,
    DISCORD_MEMORY_FILTER_REASON_CODES_V2,
    DISCORD_MEMORY_INDEX_STATUSES_V1,
    DISCORD_MEMORY_OPERATIONS_V1,
    DISCORD_MEMORY_SCOPES_V1,
    DISCORD_MEMORY_SOURCE_ROLES_V1,
    DISCORD_MEMORY_STATUSES_V1,
    DISCORD_MEMORY_VALIDATION_STATUSES_V1,
    DISCORD_MEMORY_VERIFICATION_RESULTS_V1,
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def sql_values(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # T1 (20260820_24): uniqueness only among LIVE rows. The full-table
        # constraint from 20260717_01 kept the hash of soft-deleted documents
        # reserved forever, so re-uploading previously deleted content crashed
        # with a 500. Deduplication lookups already excluded deleted rows —
        # the database now agrees with them.
        Index(
            "uq_documents_content_hash_active",
            "content_hash",
            unique=True,
            postgresql_where=text("status != 'deleted'"),
        ),
        # Exists in the database since 20260717_01 but was never declared.
        # Kept rather than dropped: migrations here are additive only.
        Index("ix_documents_cleanup_status", "status", "deleted_requested_at"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=lambda: new_id("doc"))
    original_filename: Mapped[str] = mapped_column(Text)
    # The user-visible name is a separate identity from the immutable byte
    # hash.  New uploads populate this normalized key so a name identifies one
    # live document while the service can present an explicit conflict choice.
    display_filename_normalized: Mapped[str | None] = mapped_column(String(1024), index=True, nullable=True)
    stored_filename: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(Integer)
    # A legacy source-less document has no trustworthy byte hash.  Phase 5B
    # preserves that fact instead of inventing a value; upload/reindex paths
    # still supply a real hash for normal documents.
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="uploaded")
    active_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_available: Mapped[bool] = mapped_column(Boolean, default=True)
    source_removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_policy: Mapped[str] = mapped_column(String(32), default="permanent")
    # `nullable=True` matches the database: these were created with a server
    # default and no NOT NULL, so the annotation alone was claiming otherwise.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    deleted_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number", name="uq_document_version_number"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=lambda: new_id("ver"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True, default="staging")
    parser_name: Mapped[str | None] = mapped_column(String(128))
    parser_version: Mapped[str | None] = mapped_column(String(128))
    ocr_model: Mapped[str | None] = mapped_column(String(255))
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    chunking_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=lambda: new_id("ing"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="queued")
    current_stage: Mapped[str] = mapped_column(String(32), default="queued")
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    processed_pages: Mapped[int] = mapped_column(Integer, default=0)
    ocr_pages: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    embedded_chunks: Mapped[int] = mapped_column(Integer, default=0)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("version_id", "page_number", name="uq_document_page_version_number"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=lambda: new_id("page"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    native_text: Mapped[str | None] = mapped_column(Text)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    selected_text: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(String(16), default="native")
    native_quality_score: Mapped[float | None] = mapped_column(nullable=True)
    ocr_quality_score: Mapped[float | None] = mapped_column(nullable=True)
    render_dpi: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    error_message: Mapped[str | None] = mapped_column(Text)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "version_id", "chunk_index", name="uq_document_chunk_version_index"),
        UniqueConstraint("chunk_uid", name="uq_document_chunk_uid"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=lambda: new_id("chunk"))
    # Uniqueness comes from uq_document_chunk_uid above, which is the form the
    # database has; the column flags asked for a second index nobody created.
    chunk_uid: Mapped[str] = mapped_column(String(128))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    # P4-2 (20260821_25): generated situating context that embedding and BM25
    # index in front of the content. NULL = index the bare content; citations
    # always show `content`, never this text.
    retrieval_context: Mapped[str | None] = mapped_column(Text)
    # Written on insert, never used as a query predicate anywhere in backend/.
    content_hash: Mapped[str] = mapped_column(String(64))
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    # Phase 5B preserves the citation positions and semantic heading path that
    # legacy SQLite stored beside canonical chunk text.  A heading path is
    # represented as an ordered JSON array, including a one-item array for the
    # historical scalar heading value.
    locations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    heading_path: Mapped[list[str] | None] = mapped_column(JSONB)
    section_title: Mapped[str | None] = mapped_column(Text)
    block_type: Mapped[str] = mapped_column(String(32), default="paragraph")
    token_count: Mapped[int | None] = mapped_column(Integer)
    extraction_method: Mapped[str] = mapped_column(String(16), default="native")
    status: Mapped[str] = mapped_column(String(32), default="staging")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)


class ChunkFeedback(Base):
    """P4-5 phase 2: a mark on a chunk, living OUTSIDE document_chunks.

    replace_chunks deletes and recreates chunk rows on every reindex, so a
    column there would silently lose every mark. chunk_uid pins the mark
    within a version; content_hash is the bridge across reindexing — identical
    content in a new version can be matched back to its marks, changed content
    is a different chunk and old marks stop applying.
    """

    __tablename__ = "chunk_feedback"
    __table_args__ = (
        UniqueConstraint("chunk_uid", "label", name="uq_chunk_feedback_uid_label"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=lambda: new_id("cfb"))
    chunk_uid: Mapped[str] = mapped_column(String(128), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(32), default="bad")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # These constraints exist in the database under these names since
        # 20260717_03. Declaring them by name (instead of a bare `unique=True`)
        # is what lets Alembic compare them at all.
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        UniqueConstraint("redis_job_id", name="uq_jobs_redis_job_id"),
        Index("ix_jobs_status_available", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=lambda: new_id("job"))
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    ingestion_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="CASCADE"), index=True)
    # ix_jobs_status_available above already covers every status predicate;
    # a standalone index here would be a new redundant one.
    status: Mapped[str] = mapped_column(String(32), default="queued")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    redis_job_id: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_outbox_events_idempotency_key"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=lambda: new_id("outbox"))
    # Neither of these is a query predicate in application code; the dedup
    # lookups go through the unique constraint's own index.
    event_type: Mapped[str] = mapped_column(String(64))
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    job_id: Mapped[str | None] = mapped_column(String(128), index=True)
    redis_job_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)


# Auxiliary-domain schema added in SQLite-to-PostgreSQL Phase 2.  These models
# are deliberately not wired into runtime services until data migration and
# domain-by-domain cutover have been verified.
class User(Base):
    """Web account (P3-1). Roles are deliberately just admin/member; the
    Discord bot and CLI tools authenticate with the API key instead."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin','member')", name="ck_users_role"),
        CheckConstraint("username = lower(username)", name="ck_users_username_lower"),
        UniqueConstraint("username", name="uq_users_username"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RefreshToken(Base):
    """One long-lived refresh credential per login, stored hashed and
    revocable. Deliberately NOT rotated on use: rotation with reuse-detection
    turns every multi-tab refresh race into a mass logout on a LAN tool."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    # String preserves legacy opaque IDs without assuming every historical ID is
    # a valid UUID.
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str | None] = mapped_column(String(200))
    # NULL = created before accounts existed (or with auth off); such rows are
    # admin-only once auth is on.
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class DiscordConversationSession(Base):
    __tablename__ = "discord_conversation_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active','closed','expired','orphaned','deleted')", name="ck_discord_conversation_sessions_status"),
        CheckConstraint("origin = 'discord'", name="ck_discord_conversation_sessions_origin"),
        CheckConstraint("visibility IN ('internal','admin')", name="ck_discord_conversation_sessions_visibility"),
        Index(
            "uq_discord_active_channel_session",
            "guild_id",
            "channel_id",
            unique=True,
            postgresql_where=text("status = 'active' AND thread_id IS NULL"),
        ),
        Index(
            "uq_discord_active_thread_session",
            "guild_id",
            "channel_id",
            "thread_id",
            unique=True,
            postgresql_where=text("status = 'active' AND thread_id IS NOT NULL"),
        ),
        Index("ix_discord_session_canonical_lookup", "guild_id", "channel_id", "thread_id", "status"),
        Index("ix_discord_session_backend_conversation", "backend_conversation_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    guild_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(Text)
    # conversations.id remains VARCHAR(128) to preserve legacy opaque IDs.
    # The resolver stores UUID conversations as canonical strings and checks
    # their existence transactionally; a cross-type foreign key is therefore
    # intentionally not declared here.
    backend_conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False, default="discord", server_default="discord")
    visibility: Mapped[str] = mapped_column(Text, nullable=False, default="internal", server_default="internal")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    orphaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class DiscordSessionTurn(Base):
    __tablename__ = "discord_session_turns"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_discord_session_turns_status"),
        CheckConstraint("sequence_number > 0", name="ck_discord_session_turns_positive_sequence"),
        CheckConstraint("attempt_count >= 0", name="ck_discord_session_turns_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_discord_session_turns_max_attempts"),
        UniqueConstraint("session_id", "discord_message_id", name="uq_discord_session_turn_message"),
        UniqueConstraint("session_id", "sequence_number", name="uq_discord_session_turn_sequence"),
        Index(
            "uq_discord_session_turn_one_running",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
        Index("ix_discord_session_turn_dispatch", "status", "available_at", "session_id", "sequence_number"),
        Index(
            "ix_discord_session_turn_stale_lease",
            "lease_expires_at",
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("discord_conversation_sessions.id", ondelete="CASCADE"), nullable=False)
    discord_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable only for turns created before Sprint 2A. New API input requires
    # both author fields and treats author_id as the stable identity.
    author_id: Mapped[str | None] = mapped_column(Text)
    author_display_name: Mapped[str | None] = mapped_column(Text)
    reply_to_discord_message_id: Mapped[str | None] = mapped_column(Text)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    response_text: Mapped[str | None] = mapped_column(Text)
    model_used: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued", server_default="queued")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class DiscordChannelMessage(Base):
    """Sổ gốc (tier 1, memory_design.md §5.2): one row per Discord message the
    bot passively hears in a listened channel — bot rows included, tagged
    ``is_bot`` (§9.3 decided 28/08: stored for dialogue coherence, but memory
    EXTRACTION never consumes bot-authored rows).

    Deliberately NOT discord_session_turns (§5.1): that table is a work queue;
    passive messages are not work items. Append-only in STRUCTURE (invariant
    #3); the ``content`` cell is mutable — an edit moves the first version
    into ``content_original`` (set once, §5.3) and a Discord delete clears
    both texts while keeping the row skeleton for audit (§9.5 minimal form;
    per-person hard delete is a plain DELETE because the FTS index is per-row).

    ``sent_at`` is derived from the snowflake AT WRITE TIME (§5.2) so a wrong
    host clock cannot corrupt message chronology. ``content_tokens`` is a
    'simple'-config tsvector over tokenize_vietnamese output (§13.5 option c:
    incremental, no rebuild cliff).
    """

    __tablename__ = "discord_channel_messages"
    __table_args__ = (
        UniqueConstraint(
            "discord_message_id",
            name="uq_discord_channel_messages_message",
        ),
        Index(
            "ix_discord_channel_messages_guild_channel_sent",
            "guild_id",
            "channel_id",
            "sent_at",
        ),
        Index(
            "ix_discord_channel_messages_guild_author_sent",
            "guild_id",
            "author_id",
            "sent_at",
        ),
        Index(
            "ix_discord_channel_messages_content_tokens",
            "content_tokens",
            postgresql_using="gin",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(Text)
    discord_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[str] = mapped_column(Text, nullable=False)
    author_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    content: Mapped[str | None] = mapped_column(Text)
    content_original: Mapped[str | None] = mapped_column(Text)
    content_tokens = mapped_column(TSVECTOR)
    reply_to_message_id: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class DiscordChannelPolicy(Base):
    """Per-channel listening policy (memory_design.md §5.4): auditable record
    of which channels feed the raw ledger, per invariant #6. The env var
    DISCORD_LISTEN_CHANNEL_IDS stays the operational switch today; rows are
    upserted with enabled_by="env" the first time a channel delivers, so the
    audit trail exists before the env var is ever replaced by this table.
    Threads follow their parent channel; DMs are never recorded.
    """

    __tablename__ = "discord_channel_policies"
    __table_args__ = (
        UniqueConstraint(
            "guild_id",
            "channel_id",
            name="uq_discord_channel_policies_channel",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    listening_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    enabled_by: Mapped[str] = mapped_column(Text, nullable=False)
    enabled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscordTurnDelivery(Base):
    __tablename__ = "discord_turn_deliveries"
    __table_args__ = (
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_discord_turn_deliveries_chunk_index",
        ),
        UniqueConstraint(
            "turn_id",
            "chunk_index",
            name="uq_discord_turn_delivery_chunk",
        ),
        UniqueConstraint(
            "discord_message_id",
            name="uq_discord_turn_delivery_message",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    turn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("discord_session_turns.id", ondelete="CASCADE"),
        nullable=False,
    )
    discord_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DiscordMemoryCandidate(Base):
    __tablename__ = "discord_memory_candidates"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_discord_memory_candidates_confidence",
        ),
        CheckConstraint(
            f"operation IS NULL OR operation IN ({sql_values(DISCORD_MEMORY_OPERATIONS_V1)})",
            name="ck_discord_memory_candidates_operation",
        ),
        CheckConstraint(
            f"scope IS NULL OR scope IN ({sql_values(DISCORD_MEMORY_SCOPES_V1)})",
            name="ck_discord_memory_candidates_scope",
        ),
        CheckConstraint(
            f"filter_decision IN ({sql_values(DISCORD_MEMORY_FILTER_DECISIONS_V3)})",
            name="ck_discord_memory_candidates_filter_decision",
        ),
        CheckConstraint(
            f"filter_reason_code IN ({sql_values(DISCORD_MEMORY_FILTER_REASON_CODES_V2)})",
            name="ck_discord_memory_candidates_filter_reason_code",
        ),
        CheckConstraint(
            f"validation_status IN ({sql_values(DISCORD_MEMORY_CANDIDATE_VALIDATION_STATUSES_V2)})",
            name="ck_discord_memory_candidates_validation_status",
        ),
        CheckConstraint(
            f"decision IN ({sql_values(DISCORD_MEMORY_CANDIDATE_DECISIONS_V1)})",
            name="ck_discord_memory_candidates_decision",
        ),
        CheckConstraint(
            "verification_result IS NULL OR verification_result IN "
            f"({sql_values(DISCORD_MEMORY_VERIFICATION_RESULTS_V1)})",
            name="ck_discord_memory_candidates_verification_result",
        ),
        UniqueConstraint(
            "source_turn_id",
            "extractor_schema_version",
            name="uq_discord_memory_candidate_turn_schema",
        ),
        UniqueConstraint(
            "source_discord_message_id",
            "extractor_schema_version",
            name="uq_discord_memory_candidate_message_schema",
        ),
        Index(
            "ix_discord_memory_candidates_decision_not_before",
            "decision",
            "not_before",
        ),
        Index(
            "ix_discord_memory_candidates_conflict_decision_created",
            "conflict_key",
            "decision",
            "created_at",
        ),
        Index(
            "ix_discord_memory_candidates_expires_at",
            "expires_at",
        ),
        Index(
            "ix_discord_memory_candidates_guild_author_created",
            "guild_id",
            "source_author_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_turn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("discord_session_turns.id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("discord_conversation_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_discord_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_author_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_author_display_name: Mapped[str | None] = mapped_column(Text)
    guild_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(Text)
    extractor_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    extractor_model: Mapped[str | None] = mapped_column(Text)
    filter_decision: Mapped[str] = mapped_column(Text, nullable=False)
    filter_reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    normalized_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    operation: Mapped[str | None] = mapped_column(Text)
    memory_type: Mapped[str | None] = mapped_column(Text)
    subject_type: Mapped[str | None] = mapped_column(Text)
    subject_id: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text)
    fact_key: Mapped[str | None] = mapped_column(Text)
    canonical_fact: Mapped[str | None] = mapped_column(Text)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    target_memory_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("discord_memories.id", ondelete="RESTRICT"),
    )
    validation_status: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    conflict_key: Mapped[str | None] = mapped_column(Text)
    proposed_value_hash: Mapped[str | None] = mapped_column(Text)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    # Job 4: the 1-vs-1 verifier's verdict (fact vs its source), and how it
    # was reached (e.g. "nli-1v1:qwen3.5:9b"). NULL = not verified yet.
    verification_method: Mapped[str | None] = mapped_column(Text)
    verification_result: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DiscordMemory(Base):
    __tablename__ = "discord_memories"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_discord_memories_version"),
        CheckConstraint(
            f"status IN ({sql_values(DISCORD_MEMORY_STATUSES_V1)})",
            name="ck_discord_memories_status",
        ),
        CheckConstraint(
            f"scope IN ({sql_values(DISCORD_MEMORY_SCOPES_V1)})",
            name="ck_discord_memories_scope",
        ),
        CheckConstraint(
            f"index_status IN ({sql_values(DISCORD_MEMORY_INDEX_STATUSES_V1)})",
            name="ck_discord_memories_index_status",
        ),
        CheckConstraint(
            f"validation_status IN ({sql_values(DISCORD_MEMORY_VALIDATION_STATUSES_V1)})",
            name="ck_discord_memories_validation_status",
        ),
        CheckConstraint(
            "("
            "(scope IN ('member_in_guild','guild') AND channel_id IS NULL AND thread_id IS NULL)"
            " OR (scope = 'channel' AND channel_id IS NOT NULL AND thread_id IS NULL)"
            " OR (scope = 'thread' AND channel_id IS NOT NULL AND thread_id IS NOT NULL)"
            ")",
            name="ck_discord_memories_scope_location",
        ),
        UniqueConstraint(
            "origin_candidate_id",
            name="uq_discord_memories_origin_candidate",
        ),
        Index(
            "uq_discord_memory_active_member",
            "guild_id",
            "subject_type",
            "subject_id",
            "fact_key",
            unique=True,
            postgresql_where=text("status = 'active' AND scope = 'member_in_guild'"),
        ),
        Index(
            "uq_discord_memory_active_guild",
            "guild_id",
            "subject_type",
            "subject_id",
            "fact_key",
            unique=True,
            postgresql_where=text("status = 'active' AND scope = 'guild'"),
        ),
        Index(
            "uq_discord_memory_active_channel",
            "guild_id",
            "channel_id",
            "subject_type",
            "subject_id",
            "fact_key",
            unique=True,
            postgresql_where=text("status = 'active' AND scope = 'channel'"),
        ),
        Index(
            "uq_discord_memory_active_thread",
            "guild_id",
            "channel_id",
            "thread_id",
            "subject_type",
            "subject_id",
            "fact_key",
            unique=True,
            postgresql_where=text("status = 'active' AND scope = 'thread'"),
        ),
        Index(
            "uq_discord_memory_member_version",
            "guild_id",
            "subject_type",
            "subject_id",
            "fact_key",
            "version",
            unique=True,
            postgresql_where=text("scope = 'member_in_guild'"),
        ),
        Index(
            "uq_discord_memory_guild_version",
            "guild_id",
            "subject_type",
            "subject_id",
            "fact_key",
            "version",
            unique=True,
            postgresql_where=text("scope = 'guild'"),
        ),
        Index(
            "uq_discord_memory_channel_version",
            "guild_id",
            "channel_id",
            "subject_type",
            "subject_id",
            "fact_key",
            "version",
            unique=True,
            postgresql_where=text("scope = 'channel'"),
        ),
        Index(
            "uq_discord_memory_thread_version",
            "guild_id",
            "channel_id",
            "thread_id",
            "subject_type",
            "subject_id",
            "fact_key",
            "version",
            unique=True,
            postgresql_where=text("scope = 'thread'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    guild_id: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[str | None] = mapped_column(Text)
    thread_id: Mapped[str | None] = mapped_column(Text)
    memory_type: Mapped[str] = mapped_column(Text, nullable=False)
    fact_key: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_fact: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    origin_candidate_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("discord_memory_candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    supersedes_memory_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("discord_memories.id", ondelete="RESTRICT"),
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extractor_model: Mapped[str] = mapped_column(Text, nullable=False)
    extractor_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    validation_status: Mapped[str] = mapped_column(Text, nullable=False)
    index_status: Mapped[str] = mapped_column(Text, nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    index_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DiscordMemorySource(Base):
    __tablename__ = "discord_memory_sources"
    __table_args__ = (
        CheckConstraint(
            f"source_role IN ({sql_values(DISCORD_MEMORY_SOURCE_ROLES_V1)})",
            name="ck_discord_memory_sources_role",
        ),
        UniqueConstraint(
            "memory_id",
            "source_turn_id",
            "source_role",
            name="uq_discord_memory_source_role",
        ),
    )

    memory_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("discord_memories.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("discord_memory_candidates.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    source_turn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("discord_session_turns.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    source_discord_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_author_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_role: Mapped[str] = mapped_column(Text, primary_key=True)
    evidence_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Message(Base):
    __tablename__ = "messages"

    # BigInteger keeps SQLite INTEGER primary keys during migration.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MessageSource(Base):
    """The citations that were actually placed in the prompt for one answer.

    Written in the same transaction as the assistant message, so a stored
    answer never exists without the sources it was grounded in.  Rows are a
    snapshot: the filename and excerpt stay as they were when the answer was
    given, even if the document is later replaced or deleted.  ``chunk_id``
    keeps the link to the chunk that produced it for verification.
    """

    __tablename__ = "message_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    # Citation order as shown to the user; [Source 1] is position 1.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    chunk_id: Mapped[str] = mapped_column(String(128), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    heading_path: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("message_id", "position", name="uq_message_sources_position"),)


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_type: Mapped[str] = mapped_column(String(64), nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AgentTrace(Base):
    """One step of an agent-mode answer (P2-2): which tool ran, with what
    arguments, what came back, and the final synthesis.

    Rows are written after the assistant message is persisted and cascade with
    it — a trace never outlives the answer it explains.
    """

    __tablename__ = "agent_traces"
    __table_args__ = (
        Index("ix_agent_traces_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(128))
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    content: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RequestLog(Base):
    __tablename__ = "request_logs"
    __table_args__ = (
        Index("ix_request_logs_message_id", "message_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(255))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    # D4-lite: the join key that turns three existing records into one tree —
    # message_sources (what was retrieved) + messages (the answer) + this row
    # (how long it took). Deliberately NOT a ForeignKey: agent_traces cascades
    # with the conversation and holds 0 rows with its sequence at 20 — every
    # trace died with the chat it explained. Telemetry outlives its subject.
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    # Ollama's own prompt_eval_count / eval_count, previously parsed and
    # discarded. NULL when the provider reports nothing (Gemini/DeepSeek).
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    # sha256 of the ASSEMBLED system prompt (post injection-defense wrapping):
    # answers "did the prompt change on Tuesday?" without a registry, and is
    # the only kind of check that catches a version label on the wrong text.
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class OcrRun(Base):
    __tablename__ = "ocr_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class OcrCache(Base):
    __tablename__ = "ocr_cache"
    __table_args__ = (UniqueConstraint("input_hash", "engine", "model_name", "model_revision", "config_fingerprint", name="uq_ocr_cache_key"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=lambda: new_id("ocrcache"))
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    engine: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(255), nullable=False)
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EmbeddingCache(Base):
    __tablename__ = "embedding_cache"
    __table_args__ = (UniqueConstraint("content_hash", "model_name", "model_revision", "dimensions", "config_fingerprint", "normalization_fingerprint", name="uq_embedding_cache_key"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=lambda: new_id("embedcache"))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(255), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
