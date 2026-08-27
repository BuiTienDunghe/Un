"""0c (memory_design.md §3.4): memory reaches the Discord answer as an
unconditional, FILTERED ledger SELECT — not via the unfiltered Qdrant mirror
and not via a tool the model may or may not call (measured: 4/19 turns).

Step 4 (28/08) widened the read to GUILD-wide member facts: both observed
production uses cross the asker boundary (PA asking about Dũng's birthday,
Dũng asking what PA stated about him). The privacy boundary that stays
absolute is the GUILD — exercised here by asking from a second guild.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.discord_memory_repositories import DiscordMemoryRepository
from app.postgres.models import (
    Conversation,
    DiscordConversationSession,
    DiscordMemory,
    DiscordMemoryCandidate,
    DiscordSessionTurn,
)
from app.services.discord_session_service import DiscordSessionService
from app.services.discord_turn_service import DiscordTurnService

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


class RecordingChatService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def respond_with_context(
        self,
        message,
        conversation_id,
        *,
        model_history,
        current_model_message,
        context_system_prompt,
        system_prompt=None,
        use_tools=False,
        tool_context=None,
    ):
        self.calls.append({
            "message": message,
            "context_system_prompt": context_system_prompt,
        })
        return f"answer:{message}", "fake-model", conversation_id, 1


@pytest.fixture
def injection_world():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    prefix = f"meminj-{uuid4().hex}"
    resolver = DiscordSessionService(factory)
    chat = RecordingChatService()
    service = DiscordTurnService(factory, resolver, chat, lease_seconds=30)
    yield factory, prefix, resolver, chat, service
    with factory.begin() as database:
        session_ids = list(
            database.scalars(
                select(DiscordConversationSession.id).where(
                    DiscordConversationSession.guild_id.like(f"{prefix}%")
                )
            )
        )
        conversation_ids = [
            str(value)
            for value in database.scalars(
                select(DiscordConversationSession.backend_conversation_id).where(
                    DiscordConversationSession.guild_id.like(f"{prefix}%")
                )
            )
        ]
        database.execute(
            delete(DiscordMemory).where(DiscordMemory.guild_id.like(f"{prefix}%"))
        )
        database.execute(
            delete(DiscordMemoryCandidate).where(
                DiscordMemoryCandidate.guild_id.like(f"{prefix}%")
            )
        )
        if session_ids:
            database.execute(
                delete(DiscordSessionTurn).where(DiscordSessionTurn.session_id.in_(session_ids))
            )
        database.execute(
            delete(DiscordConversationSession).where(
                DiscordConversationSession.guild_id.like(f"{prefix}%")
            )
        )
        if conversation_ids:
            database.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))


def _seed_active_member_fact(factory, *, guild_id, session_id, turn_id, author_id, fact):
    """One active ledger row for `author_id`, satisfying the candidate FK the
    same way production does: candidate first, memory second."""
    with factory.begin() as database:
        turn = database.get(DiscordSessionTurn, turn_id)
        candidate, _ = DiscordMemoryRepository(database).create_or_get_candidate(
            source_turn_id=turn_id,
            session_id=session_id,
            source_discord_message_id=turn.discord_message_id,
            source_author_id=author_id,
            source_author_display_name="Author One",
            guild_id=guild_id,
            channel_id="chan-mem",
            thread_id=None,
            extractor_schema_version="discord-memory-v1",
            filter_decision="candidate",
            filter_reason_code="durable_preference",
        )
        database.add(
            DiscordMemory(
                id=uuid4(),
                guild_id=guild_id,
                scope="member_in_guild",
                subject_type="discord_member",
                subject_id=author_id,
                memory_type="preference",
                fact_key="user.favorite_drink",
                canonical_fact=fact,
                status="active",
                version=1,
                origin_candidate_id=candidate.id,
                valid_from=func.now(),
                extractor_model="test",
                extractor_schema_version="discord-memory-v1",
                validation_status="accepted",
                index_status="not_required",
            )
        )


def test_active_ledger_fact_is_injected_guild_wide_with_subject_label(injection_world):
    factory, prefix, resolver, chat, service = injection_world
    session = resolver.resolve(prefix, "chan-mem")

    seed = service.enqueue(
        session.session_id, "m-seed", "tôi thích trà sữa", None,
        author_id="author-1", author_display_name="Author One",
    )
    _seed_active_member_fact(
        factory,
        guild_id=prefix,
        session_id=session.session_id,
        turn_id=seed.turn_id,
        author_id="author-1",
        fact="author-1 thích uống trà sữa",
    )

    # The member the fact is about: it must be in the prompt, unconditionally,
    # and the line must name its subject so the model can join it against the
    # speaker labels in the history.
    execution = service.execute(seed.turn_id)
    service.complete(seed.turn_id, execution.execution_token or "", ["bot-seed"])
    assert "author-1 thích uống trà sữa" in chat.calls[-1]["context_system_prompt"]
    assert (
        "[user.favorite_drink | về author_id=author-1]"
        in chat.calls[-1]["context_system_prompt"]
    )

    # Step 4: a DIFFERENT member asking in the same guild sees it too — both
    # observed production uses cross the asker boundary, and the ledger holds
    # only public-in-server, human-approved statements.
    other = service.enqueue(
        session.session_id, "m-other", "author-1 thích uống gì", None,
        author_id="author-2", author_display_name="Author Two",
    )
    execution = service.execute(other.turn_id)
    service.complete(other.turn_id, execution.execution_token or "", ["bot-other"])
    assert "trà sữa" in chat.calls[-1]["context_system_prompt"]


def test_member_facts_never_cross_the_guild_boundary(injection_world):
    factory, prefix, resolver, chat, service = injection_world
    home = resolver.resolve(prefix, "chan-mem")
    seed = service.enqueue(
        home.session_id, "m-seed3", "tôi thích trà sữa", None,
        author_id="author-1", author_display_name="Author One",
    )
    _seed_active_member_fact(
        factory,
        guild_id=prefix,
        session_id=home.session_id,
        turn_id=seed.turn_id,
        author_id="author-1",
        fact="author-1 thích uống trà sữa",
    )

    # The SAME member asking from another guild: absolutely nothing leaks —
    # the guild boundary is the isolation attrib-04 pins (§3.2).
    foreign = resolver.resolve(f"{prefix}-g2", "chan-mem")
    other = service.enqueue(
        foreign.session_id, "m-foreign", "tôi thích uống gì", None,
        author_id="author-1", author_display_name="Author One",
    )
    execution = service.execute(other.turn_id)
    service.complete(other.turn_id, execution.execution_token or "", ["bot-foreign"])
    assert "trà sữa" not in chat.calls[-1]["context_system_prompt"]


def test_superseded_facts_stay_out_of_the_prompt(injection_world):
    factory, prefix, resolver, chat, service = injection_world
    session = resolver.resolve(prefix, "chan-mem")
    seed = service.enqueue(
        session.session_id, "m-seed2", "tôi thích trà sữa", None,
        author_id="author-1", author_display_name="Author One",
    )
    _seed_active_member_fact(
        factory,
        guild_id=prefix,
        session_id=session.session_id,
        turn_id=seed.turn_id,
        author_id="author-1",
        fact="author-1 thích uống trà sữa",
    )
    with factory.begin() as database:
        memory = database.scalar(
            select(DiscordMemory).where(DiscordMemory.guild_id == prefix)
        )
        memory.status = "superseded"
        memory.valid_until = func.now()

    execution = service.execute(seed.turn_id)
    service.complete(seed.turn_id, execution.execution_token or "", ["bot-seed2"])
    assert "trà sữa" not in chat.calls[-1]["context_system_prompt"]
