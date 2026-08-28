"""Sổ gốc (tier 1) + history search (job 1+2, memory_design.md §5, §13.5-6).

Write path: the Discord bot fires one authenticated POST per heard message in
a listened channel; failures are swallowed on the bot side so the answering
path never depends on this service. No model calls anywhere here; every
method is one short transaction (invariants #2, #7).

Search: Postgres FTS ('simple' config) over tokenize_vietnamese output —
§13.5 option (c). Incremental per-row indexing means there is no
rebuild-on-read cliff to fall off, and per-person hard deletion stays a
plain DELETE. The guild filter lives in SQL, never post-ranking (§6.1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.postgres.models import DiscordChannelMessage, DiscordChannelPolicy
from app.utils.vi_tokenizer import tokenize_vietnamese

# Discord epoch: 2015-01-01T00:00:00Z, in milliseconds.
_DISCORD_EPOCH_MS = 1_420_070_400_000


def snowflake_to_datetime(discord_message_id: str) -> datetime:
    """§5.2: sent_at derives from the snowflake at write time, so a wrong
    host clock can never corrupt message chronology."""
    timestamp_ms = (int(discord_message_id) >> 22) + _DISCORD_EPOCH_MS
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


def _token_text(content: str) -> str:
    return " ".join(tokenize_vietnamese(content))


_SAFE_LEXEME = re.compile(r"[^0-9a-zA-Zà-ỹÀ-ỸđĐ_]+")


def _or_query_text(query: str) -> str:
    """OR-of-lexemes: a question ("tôi nói 'chốt dùng Postgres' khi nào?")
    must match the short message it asks about; plainto's AND semantics can
    never do that. ts_rank then floats the densest match to the top."""
    lexemes = []
    for token in tokenize_vietnamese(query):
        cleaned = _SAFE_LEXEME.sub("", token)
        if cleaned:
            lexemes.append(cleaned)
    return " | ".join(dict.fromkeys(lexemes))


@dataclass(frozen=True)
class DiscordHistoryHit:
    discord_message_id: str
    channel_id: str
    thread_id: str | None
    author_id: str
    author_display_name: str
    is_bot: bool
    content: str
    sent_at: datetime
    link: str


class DiscordHistoryService:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def record_message(
        self,
        *,
        guild_id: str,
        channel_id: str,
        thread_id: str | None,
        discord_message_id: str,
        author_id: str,
        author_display_name: str,
        is_bot: bool,
        content: str,
        reply_to_message_id: str | None = None,
    ) -> bool:
        """Append one heard message; returns False on a duplicate delivery,
        a malformed message id, or a channel the policy table has revoked."""
        try:
            sent_at = snowflake_to_datetime(discord_message_id)
        except (ValueError, OverflowError, OSError):
            # Non-numeric or out-of-range id: keep the recorded=False
            # contract instead of leaking a 500 (review finding 28/08).
            return False
        try:
            with self.sessions.begin() as database:
                if not self._ensure_policy_row(database, guild_id, channel_id):
                    return False
                database.add(
                    DiscordChannelMessage(
                        guild_id=guild_id,
                        channel_id=channel_id,
                        thread_id=thread_id,
                        discord_message_id=discord_message_id,
                        author_id=author_id,
                        author_display_name=author_display_name,
                        is_bot=is_bot,
                        content=content,
                        content_tokens=func.to_tsvector(
                            "simple", _token_text(content)
                        ),
                        reply_to_message_id=reply_to_message_id,
                        sent_at=sent_at,
                    )
                )
        except IntegrityError:
            return False
        return True

    @staticmethod
    def _ensure_policy_row(database, guild_id: str, channel_id: str) -> bool:
        """Invariant #6: every channel that ever delivered has a policy row,
        and the row's listening_enabled is an effective operator kill-switch
        (flip it in the DB to stop recording without touching .env). The
        first-sight insert runs in a savepoint so a concurrent creation
        cannot abort the message insert (review findings 28/08)."""
        row = database.scalar(
            select(DiscordChannelPolicy).where(
                DiscordChannelPolicy.guild_id == guild_id,
                DiscordChannelPolicy.channel_id == channel_id,
            )
        )
        if row is not None:
            return bool(row.listening_enabled)
        try:
            with database.begin_nested():
                database.add(
                    DiscordChannelPolicy(
                        guild_id=guild_id,
                        channel_id=channel_id,
                        listening_enabled=True,
                        enabled_by="env",
                    )
                )
                database.flush()
        except IntegrityError:
            # Lost the creation race — the winner's row decides.
            row = database.scalar(
                select(DiscordChannelPolicy).where(
                    DiscordChannelPolicy.guild_id == guild_id,
                    DiscordChannelPolicy.channel_id == channel_id,
                )
            )
            return bool(row.listening_enabled) if row is not None else True
        return True

    def record_edit(self, *, discord_message_id: str, content: str) -> bool:
        """§5.3: keep the latest text in `content`, the FIRST version in
        `content_original` — set exactly once, never overwritten."""
        with self.sessions.begin() as database:
            row = database.scalar(
                select(DiscordChannelMessage).where(
                    DiscordChannelMessage.discord_message_id
                    == discord_message_id
                )
            )
            if row is None or row.deleted_at is not None:
                return False
            if row.content_original is None:
                row.content_original = row.content
            row.content = content
            row.content_tokens = func.to_tsvector("simple", _token_text(content))
            row.edited_at = datetime.now(UTC)
        return True

    def record_delete(
        self,
        *,
        discord_message_id: str,
        guild_id: str | None = None,
        channel_id: str | None = None,
    ) -> bool:
        """§9.5 minimal deletion: honor the Discord delete immediately —
        clear both texts and the index entry, keep the row skeleton for
        audit. Per-person hard delete stays a plain DELETE by author_id.

        A delete that arrives BEFORE the fire-and-forget insert leaves a
        TOMBSTONE (when the event carries guild+channel): the racing insert
        then dies on the unique message id and the deleted text is never
        stored (review finding 28/08)."""
        with self.sessions.begin() as database:
            row = database.scalar(
                select(DiscordChannelMessage).where(
                    DiscordChannelMessage.discord_message_id
                    == discord_message_id
                )
            )
            if row is None:
                if not guild_id or not channel_id:
                    return False
                try:
                    sent_at = snowflake_to_datetime(discord_message_id)
                except (ValueError, OverflowError, OSError):
                    return False
                database.add(
                    DiscordChannelMessage(
                        guild_id=guild_id,
                        channel_id=channel_id,
                        thread_id=None,
                        discord_message_id=discord_message_id,
                        author_id="",
                        author_display_name="",
                        is_bot=False,
                        content=None,
                        content_original=None,
                        content_tokens=None,
                        sent_at=sent_at,
                        deleted_at=datetime.now(UTC),
                    )
                )
                return True
            row.content = None
            row.content_original = None
            row.content_tokens = None
            row.deleted_at = datetime.now(UTC)
        return True

    def search(
        self,
        *,
        guild_id: str,
        query: str,
        author_id: str | None = None,
        days: int | None = None,
        limit: int = 5,
    ) -> list[DiscordHistoryHit]:
        """Verbatim history hits for THIS guild only (§8: no summarizing —
        the caller gets the exact message, speaker, time, and link)."""
        bounded_limit = max(1, min(int(limit), 10))
        if not guild_id:
            return []
        token_query = _or_query_text(query)
        if not token_query.strip():
            return []
        tsquery = func.to_tsquery("simple", token_query)
        conditions = [
            DiscordChannelMessage.guild_id == guild_id,
            DiscordChannelMessage.deleted_at.is_(None),
            DiscordChannelMessage.content.is_not(None),
            DiscordChannelMessage.content_tokens.op("@@")(tsquery),
        ]
        if author_id:
            conditions.append(DiscordChannelMessage.author_id == author_id)
        if days is not None and days > 0:
            # Clamp before SQL: an unclamped model-supplied value would blow
            # up make_interval (review finding 28/08). 10 years covers the
            # ledger's whole lifetime.
            bounded_days = min(int(days), 3650)
            cutoff = func.now() - func.make_interval(0, 0, 0, bounded_days)
            conditions.append(DiscordChannelMessage.sent_at >= cutoff)
        with self.sessions() as database:
            rows = database.execute(
                select(DiscordChannelMessage)
                .where(*conditions)
                .order_by(
                    func.ts_rank(
                        DiscordChannelMessage.content_tokens, tsquery
                    ).desc(),
                    DiscordChannelMessage.sent_at.desc(),
                )
                .limit(bounded_limit)
            ).scalars()
            return [_hit(row) for row in rows]

    def recent(
        self,
        *,
        guild_id: str,
        limit: int = 20,
        author_id: str | None = None,
    ) -> list[DiscordHistoryHit]:
        """The latest heard messages by sent_at, returned in CHRONOLOGICAL
        order — the 'tóm tắt N tin gần nhất' read. No query, no ranking;
        pure time order over the guild's raw ledger."""
        bounded_limit = max(1, min(int(limit), 25))
        if not guild_id:
            return []
        conditions = [
            DiscordChannelMessage.guild_id == guild_id,
            DiscordChannelMessage.deleted_at.is_(None),
            DiscordChannelMessage.content.is_not(None),
        ]
        if author_id:
            conditions.append(DiscordChannelMessage.author_id == author_id)
        with self.sessions() as database:
            rows = database.execute(
                select(DiscordChannelMessage)
                .where(*conditions)
                .order_by(
                    DiscordChannelMessage.sent_at.desc(),
                    DiscordChannelMessage.id.desc(),
                )
                .limit(bounded_limit)
            ).scalars()
            hits = [_hit(row) for row in rows]
        # Newest-first from SQL; oldest-first for reading a conversation.
        hits.reverse()
        return hits


def _hit(row: DiscordChannelMessage) -> DiscordHistoryHit:
    return DiscordHistoryHit(
        discord_message_id=row.discord_message_id,
        channel_id=row.channel_id,
        thread_id=row.thread_id,
        author_id=row.author_id,
        author_display_name=row.author_display_name,
        is_bot=row.is_bot,
        content=row.content or "",
        sent_at=row.sent_at,
        link=(
            "https://discord.com/channels/"
            f"{row.guild_id}/{row.thread_id or row.channel_id}/"
            f"{row.discord_message_id}"
        ),
    )


def history_hit_payload(hit: DiscordHistoryHit) -> dict[str, Any]:
    """The tool-facing shape (§8): verbatim + speaker + exact time + link."""
    return {
        "speaker": hit.author_display_name,
        "author_id": hit.author_id,
        "is_bot": hit.is_bot,
        "sent_at": hit.sent_at.isoformat(),
        "message": hit.content,
        "link": hit.link,
    }
