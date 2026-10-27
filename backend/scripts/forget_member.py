"""Hard-delete everything one Discord member said (memory_design.md §9.5).

The design said the deletion story did not exist; this is it. Scope, in the
order the foreign keys allow — the RESTRICT cluster around memories →
candidates → turns dictates it, and getting it wrong fails loudly rather than
half-deleting:

  1. Qdrant vectors + the web mirror row for each of their memories.
     (The point id is uuid5-derived, so deleting the Postgres row alone
     leaves an orphan vector that search would still return.)
  2. discord_memory_sources rows authored by them.
  3. condensation propositions they spoke; batches that lose text are marked
     stale so the worker rebuilds them WITHOUT that person.
  4. discord_memories about them — newest version first (the supersedes
     self-FK is RESTRICT).
  5. discord_memory_candidates from or about them.
  6. discord_session_turns they wrote (deliveries cascade).
  7. discord_channel_messages they wrote — a plain DELETE, because the FTS
     index is per row.
  8. the bot's COPIES of their words, which are filed under nobody (ticket 17):
     their requests in the guild's backend conversations (`messages`, role user),
     verbatim quotes of them in the bot's answers (`messages`, role assistant, and
     the response_text of other members' turns), and their items in the agent's
     search_history traces. Rewritten in place, not deleted — another member's
     lines in the same result stay. Their words are read BEFORE steps 6-7 delete
     them, since nothing else says what to look for. Only verbatim copies are
     found (app/stores/member_redaction.py); a paraphrase is not detectable.

Every step is scoped to the guild where the member asked (--guild-id). --all-guilds
widens every step to every guild they have anything in; it is never the default (the
owner's call, 27/10, ticket 19). The output names the guilds covered and counts what
is left alone in the others.

Dry-run by default: it prints what it would delete and touches nothing.
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import delete, func, or_, select, update

from app.config.settings import get_settings
from app.postgres.database import (
    create_postgres_engine,
    create_session_factory,
)
from app.postgres.models import (
    AgentTrace,
    AgentTraceSummary,
    DiscordChannelMessage,
    DiscordCondensationProposition,
    DiscordConversationSession,
    DiscordMemory,
    DiscordMemoryCandidate,
    DiscordMemorySource,
    DiscordSessionTurn,
    Message,
)
from app.services.discord_condensation_service import (
    DiscordCondensationService,
)
from app.stores.member_redaction import (
    LIMITS_NOTE,
    PLACEHOLDER,
    QuoteIndex,
    redact_arguments,
    redact_history_result,
    redact_quotes,
)
from app.stores.qdrant_store import QdrantStore


def _scope(model, guild_id: str | None) -> list:
    """The guild filter every step shares: one guild, or none under --all-guilds.
    Turns and memory sources carry no guild column — a turn's guild is its session's,
    a source's is that of the turn it cites, so every source citing a turn step 6
    deletes goes in step 2 first (the RESTRICT)."""
    if guild_id is None:
        return []
    if model is DiscordSessionTurn:
        return [DiscordSessionTurn.session_id.in_(
            select(DiscordConversationSession.id).where(DiscordConversationSession.guild_id == guild_id)
        )]
    if model is DiscordMemorySource:
        return [DiscordMemorySource.source_turn_id.in_(
            select(DiscordSessionTurn.id).where(*_scope(DiscordSessionTurn, guild_id))
        )]
    return [model.guild_id == guild_id]


def _member_guilds(database, author_id: str) -> list[str]:
    """Every guild where the member has something this script deletes."""
    queries = [
        select(DiscordChannelMessage.guild_id).where(DiscordChannelMessage.author_id == author_id),
        select(DiscordConversationSession.guild_id)
        .join(DiscordSessionTurn, DiscordSessionTurn.session_id == DiscordConversationSession.id)
        .where(DiscordSessionTurn.author_id == author_id),
        select(DiscordMemoryCandidate.guild_id).where(
            (DiscordMemoryCandidate.source_author_id == author_id)
            | (DiscordMemoryCandidate.subject_id == author_id)
        ),
        select(DiscordMemory.guild_id).where(DiscordMemory.subject_id == author_id),
        select(DiscordCondensationProposition.guild_id).where(DiscordCondensationProposition.speaker_id == author_id),
    ]
    return sorted({guild for query in queries for guild in database.scalars(query.distinct())})


def _member_words(database, guild_id: str, author_id: str) -> tuple[QuoteIndex, dict[str, set[str]]]:
    """What the member wrote in this guild — channel messages and turn requests —
    read before steps 6-7 delete it: the only record of what their copies look like.
    Requests come keyed by the backend conversation they were asked in."""
    channel = list(database.scalars(select(DiscordChannelMessage.content).where(
        DiscordChannelMessage.guild_id == guild_id, DiscordChannelMessage.author_id == author_id,
    )))
    requests: dict[str, set[str]] = {}
    for request_text, conversation_id in database.execute(
        select(DiscordSessionTurn.request_text, DiscordConversationSession.backend_conversation_id)
        .join(DiscordConversationSession, DiscordSessionTurn.session_id == DiscordConversationSession.id)
        .where(DiscordSessionTurn.author_id == author_id, DiscordConversationSession.guild_id == guild_id)
    ):
        requests.setdefault(str(conversation_id), set()).add(request_text)
    return QuoteIndex([*channel, *(text for texts in requests.values() for text in texts)]), requests


def _copies(database, guild_id: str, author_id: str, index: QuoteIndex, requests: dict[str, set[str]]) -> list[tuple[object, str, object]]:
    """(row, field, replacement) for every copy of the member's words in the guild's
    backend conversations. search_history only ever reads its own guild, so no other
    conversation can hold one."""
    conversations = [str(value) for value in database.scalars(
        select(DiscordConversationSession.backend_conversation_id).where(DiscordConversationSession.guild_id == guild_id)
    )]
    if not conversations:
        return []
    changes: list[tuple[object, str, object]] = []
    for row in database.scalars(select(Message).where(Message.conversation_id.in_(conversations))):
        if row.role == "user" and row.content in requests.get(row.conversation_id, ()):
            changes.append((row, "content", PLACEHOLDER))
        elif row.role == "assistant":
            redacted, changed = redact_quotes(row.content, index)
            if changed:
                changes.append((row, "content", redacted))
    # The bot's reply is also stored on EVERY turn (discord_repositories.py:422), so an
    # answer to another member that quoted them survives step 6, which only deletes
    # their own turns (fable's review). A NULL author is someone else too.
    for turn in database.scalars(
        select(DiscordSessionTurn)
        .join(DiscordConversationSession, DiscordSessionTurn.session_id == DiscordConversationSession.id)
        .where(
            DiscordConversationSession.guild_id == guild_id,
            or_(DiscordSessionTurn.author_id.is_(None), DiscordSessionTurn.author_id != author_id),
        )
    ):
        redacted, changed = redact_quotes(turn.response_text, index)
        if changed:
            changes.append((turn, "response_text", redacted))
    for row in database.scalars(select(AgentTrace).where(AgentTrace.conversation_id.in_(conversations))):
        if row.kind == "tool_result" and row.tool_name == "search_history":
            redacted, changed = redact_history_result(row.content, author_id, index)
            field = "content"
        elif row.kind == "tool_call":
            redacted, changed = redact_arguments(row.arguments, author_id, index)
            field = "arguments"
        elif row.kind == "final":
            redacted, changed = redact_quotes(row.content, index)
            field = "content"
        else:
            continue
        if changed:
            changes.append((row, field, redacted))
    return changes


def _all_copies(database, words: dict[str, tuple[QuoteIndex, dict[str, set[str]]]], author_id: str) -> list[tuple[object, str, object]]:
    """_copies guild by guild, each searched with what the member wrote THERE."""
    return [
        change
        for guild, (index, requests) in words.items()
        for change in _copies(database, guild, author_id, index, requests)
    ]


def _copy_counts(changes: list[tuple[object, str, object]]) -> dict[str, int]:
    return {
        "conversation_messages": sum(1 for row, _, _ in changes if isinstance(row, Message)),
        "agent_trace_steps": sum(1 for row, _, _ in changes if isinstance(row, AgentTrace)),
        "turn_responses": sum(1 for row, _, _ in changes if isinstance(row, DiscordSessionTurn)),
    }


def _counts(database, guild_id: str | None, author_id: str) -> dict[str, int]:
    def count(model, *conditions) -> int:
        return int(
            database.scalar(select(func.count()).select_from(model).where(*conditions, *_scope(model, guild_id)))
            or 0
        )

    return {
        "channel_messages": count(
            DiscordChannelMessage,
            DiscordChannelMessage.author_id == author_id,
        ),
        "session_turns": count(
            DiscordSessionTurn, DiscordSessionTurn.author_id == author_id
        ),
        "candidates": count(
            DiscordMemoryCandidate,
            (DiscordMemoryCandidate.source_author_id == author_id)
            | (DiscordMemoryCandidate.subject_id == author_id),
        ),
        "memories": count(
            DiscordMemory,
            DiscordMemory.subject_id == author_id,
        ),
        "memory_sources": count(
            DiscordMemorySource, DiscordMemorySource.source_author_id == author_id
        ),
        "propositions": count(
            DiscordCondensationProposition,
            DiscordCondensationProposition.speaker_id == author_id,
        ),
    }


def forget(guild_id: str, author_id: str, *, apply: bool, all_guilds: bool = False) -> dict[str, object]:
    """Forget the member in `guild_id`, where they asked — or in every guild, only
    when `all_guilds` says so."""
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    factory = create_session_factory(
        create_postgres_engine(str(settings.database_url))
    )
    scope = None if all_guilds else guild_id

    with factory() as database:
        member_guilds = _member_guilds(database, author_id)
        guilds = member_guilds if all_guilds else [guild_id]
        planned = _counts(database, scope, author_id)
        # Read now: steps 6-7 delete the only record of what their words were.
        words = {guild: _member_words(database, guild, author_id) for guild in guilds}
        planned.update(_copy_counts(_all_copies(database, words, author_id)))
        memory_ids = list(
            database.scalars(
                select(DiscordMemory.id).where(
                    *_scope(DiscordMemory, scope),
                    DiscordMemory.subject_id == author_id,
                )
            )
        )
        # Shown, not implied: what this run leaves in the member's other guilds.
        left_alone = {
            guild: _counts(database, guild, author_id)
            for guild in member_guilds
            if guild not in guilds
        }
    payload: dict[str, object] = {
        "guild_id": guild_id,
        "author_id": author_id,
        "mode": "apply" if apply else "dry-run",
        "scope": {"all_guilds": all_guilds, "guilds": guilds, "left_alone": left_alone},
        "planned": planned,
        "mirror_ids": [f"mem_dc_{value.hex}" for value in memory_ids],
        "limits": LIMITS_NOTE,
    }
    if not apply:
        payload["side_effects"] = False
        return payload

    # 1. Vectors first: a Postgres-only delete would leave them searchable.
    removed_vectors = 0
    if memory_ids:
        # Model registry: one collection pair per embedding version, and an inactive
        # pair is frozen, not mirrored — so the delete sweeps every registered
        # memories collection, or the revoked vectors come back on demotion.
        collections = settings.qdrant_collections()
        store = QdrantStore(
            settings.qdrant_url,
            settings.qdrant_timeout_seconds,
            collections.memories,
            collections.documents,
            memories_sweep=collections.all_memories,
            documents_sweep=collections.all_documents,
        )
        for value in memory_ids:
            try:
                store.delete_memory(f"mem_dc_{value.hex}")
                removed_vectors += 1
            except Exception as error:  # keep going; report at the end
                payload.setdefault("vector_errors", []).append(str(error))

    # 3. condensation propositions — the service owns this rule (it also
    #    marks the affected batches stale), so it is called, not re-written.
    #    It works one guild at a time.
    stale_batches = 0
    for guild in guilds:
        _removed_propositions, stale = DiscordCondensationService(
            factory
        ).forget_member(guild_id=guild, speaker_id=author_id)
        stale_batches += stale

    with factory.begin() as database:
        # 8. the bot's copies of their words — in the same transaction as the deletes,
        #    so a failure leaves neither half done. A rewritten trace step's summary
        #    hash no longer matches what is stored: cleared (ticket 17, Q3).
        copies = _all_copies(database, words, author_id)
        for row, field, value in copies:
            setattr(row, field, value)
            if isinstance(row, AgentTrace) and field == "content":
                database.execute(
                    update(AgentTraceSummary)
                    .where(
                        AgentTraceSummary.conversation_id == row.conversation_id,
                        AgentTraceSummary.message_id == row.message_id,
                        AgentTraceSummary.step_index == row.step_index,
                    )
                    .values(content_sha256=None)
                )
        payload["copies_rewritten"] = _copy_counts(copies)

        # 2. sources (RESTRICT-references memories, candidates and turns)
        database.execute(
            delete(DiscordMemorySource).where(
                DiscordMemorySource.source_author_id == author_id,
                *_scope(DiscordMemorySource, scope),
            )
        )
        if memory_ids:
            database.execute(
                delete(DiscordMemorySource).where(
                    DiscordMemorySource.memory_id.in_(memory_ids)
                )
            )

        # 4. memories — clear the pointers that RESTRICT-block them first.
        if memory_ids:
            database.execute(
                update(DiscordMemoryCandidate)
                .where(DiscordMemoryCandidate.target_memory_id.in_(memory_ids))
                .values(target_memory_id=None)
            )
            database.execute(
                update(DiscordMemory)
                .where(DiscordMemory.supersedes_memory_id.in_(memory_ids))
                .values(supersedes_memory_id=None)
            )
            database.execute(
                delete(DiscordMemory).where(DiscordMemory.id.in_(memory_ids))
            )

        # 5. candidates from or about them
        database.execute(
            delete(DiscordMemoryCandidate).where(
                *_scope(DiscordMemoryCandidate, scope),
                (DiscordMemoryCandidate.source_author_id == author_id)
                | (DiscordMemoryCandidate.subject_id == author_id),
            )
        )

        # 6. their turns (deliveries cascade) — in this guild only, like every
        #    other step; this one used to take every guild (ticket 19).
        database.execute(
            delete(DiscordSessionTurn).where(
                DiscordSessionTurn.author_id == author_id,
                *_scope(DiscordSessionTurn, scope),
            )
        )

        # 7. their raw messages
        database.execute(
            delete(DiscordChannelMessage).where(
                *_scope(DiscordChannelMessage, scope),
                DiscordChannelMessage.author_id == author_id,
            )
        )

    with factory() as database:
        payload["remaining"] = _counts(database, scope, author_id)
        # Recounted with the words read before the deletes: a copy left behind shows here.
        payload["remaining"].update(_copy_counts(_all_copies(database, words, author_id)))
    payload["vectors_removed"] = removed_vectors
    payload["stale_batches"] = stale_batches
    payload["side_effects"] = True
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--guild-id",
        required=True,
        help="server nơi thành viên yêu cầu; mặc định chỉ xóa trong server này",
    )
    parser.add_argument("--author-id", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="thực sự xóa; mặc định chỉ in ra những gì sẽ xóa",
    )
    parser.add_argument(
        "--all-guilds",
        action="store_true",
        help="xóa ở MỌI server thành viên có mặt, không riêng --guild-id",
    )
    arguments = parser.parse_args(argv)
    payload = forget(
        arguments.guild_id,
        arguments.author_id,
        apply=arguments.apply,
        all_guilds=arguments.all_guilds,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    remaining = payload.get("remaining")
    if isinstance(remaining, dict) and any(remaining.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
