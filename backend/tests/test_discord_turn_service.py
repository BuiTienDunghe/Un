from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.discord_repositories import DiscordSessionRepository
from app.postgres.models import Conversation, DiscordConversationSession, DiscordSessionTurn
from app.services.chat_service import ConversationNotFoundError
from app.services.discord_session_service import DiscordSessionService
from app.services.discord_turn_service import (
    DiscordTurnOwnershipError,
    DiscordTurnService,
)


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


class FakeChatService:
    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing
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
        self.calls.append(
            {
                "message": message,
                "conversation_id": conversation_id,
                "model_history": model_history,
                "current_model_message": current_model_message,
                "context_system_prompt": context_system_prompt,
                "system_prompt": system_prompt,
                "use_tools": use_tools,
            }
        )
        if self.missing:
            raise ConversationNotFoundError(conversation_id)
        return f"answer:{message}", "fake-model", conversation_id, 1


def enqueue_turn(
    service,
    session_id,
    message_id,
    message,
    system_prompt=None,
    *,
    author_id="author-1",
    author_display_name="Author One",
    reply_to_discord_message_id=None,
):
    return service.enqueue(
        session_id,
        message_id,
        message,
        system_prompt,
        author_id=author_id,
        author_display_name=author_display_name,
        reply_to_discord_message_id=reply_to_discord_message_id,
    )


@pytest.fixture
def turn_resources():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    prefix = f"sprint1b-{uuid4().hex}"
    resolver = DiscordSessionService(factory)
    chat = FakeChatService()
    service = DiscordTurnService(factory, resolver, chat, lease_seconds=30)
    yield factory, prefix, resolver, chat, service
    with factory.begin() as database:
        conversation_ids = [
            str(value)
            for value in database.scalars(
                select(DiscordConversationSession.backend_conversation_id).where(
                    DiscordConversationSession.guild_id.like(f"{prefix}%")
                )
            )
        ]
        database.execute(
            delete(DiscordConversationSession).where(
                DiscordConversationSession.guild_id.like(f"{prefix}%")
            )
        )
        if conversation_ids:
            database.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))


def test_enqueue_is_idempotent_and_sequence_is_per_session(turn_resources):
    factory, prefix, resolver, _, service = turn_resources
    first_session = resolver.resolve(prefix, "first")
    second_session = resolver.resolve(prefix, "second")

    first = enqueue_turn(
        service,
        first_session.session_id,
        "message-1",
        "one",
        reply_to_discord_message_id="original-reply",
    )
    duplicate = enqueue_turn(
        service,
        first_session.session_id,
        "message-1",
        "ignored",
        reply_to_discord_message_id="conflicting-reply",
    )
    second = enqueue_turn(service, first_session.session_id, "message-2", "two")
    other = enqueue_turn(service, second_session.session_id, "message-3", "other")

    assert first.created is True
    assert duplicate.created is False
    assert duplicate.turn_id == first.turn_id
    assert (first.sequence_number, second.sequence_number, other.sequence_number) == (1, 2, 1)
    with factory() as database:
        row = database.get(DiscordSessionTurn, first.turn_id)
        assert row.reply_to_discord_message_id == "original-reply"


def test_concurrent_enqueue_has_unique_monotonic_sequences(turn_resources):
    _, prefix, resolver, _, service = turn_resources
    session = resolver.resolve(prefix, "shared")
    workers = 10
    barrier = threading.Barrier(workers)

    def enqueue(index: int):
        barrier.wait(timeout=10)
        return enqueue_turn(service, session.session_id, f"message-{index}", f"text-{index}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        turns = list(pool.map(enqueue, range(workers)))

    assert sorted(turn.sequence_number for turn in turns) == list(range(1, workers + 1))
    assert len({turn.turn_id for turn in turns}) == workers


def test_atomic_claim_has_one_winner_and_enforces_head_of_line(turn_resources):
    _, prefix, resolver, _, service = turn_resources
    session = resolver.resolve(prefix, "claim")
    first = enqueue_turn(service, session.session_id, "message-1", "one")
    second = enqueue_turn(service, session.session_id, "message-2", "two")
    workers = 8
    barrier = threading.Barrier(workers)

    def claim():
        barrier.wait(timeout=10)
        return service.claim(first.turn_id)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _: claim(), range(workers)))

    assert sum(result.execution_token is not None for result in results) == 1
    assert service.claim(second.turn_id).execution_token is None
    winner = next(result for result in results if result.execution_token)
    service.complete(
        first.turn_id,
        winner.execution_token or "",
        [f"bot-{first.turn_id}"],
    )
    assert service.claim(second.turn_id).execution_token is not None


def test_different_sessions_can_be_running_together(turn_resources):
    factory, prefix, resolver, _, service = turn_resources
    first_session = resolver.resolve(prefix, "first-parallel")
    second_session = resolver.resolve(prefix, "second-parallel")
    first = enqueue_turn(service, first_session.session_id, "m1", "one")
    second = enqueue_turn(service, second_session.session_id, "m2", "two")

    barrier = threading.Barrier(2)

    def claim(turn_id):
        barrier.wait(timeout=10)
        return service.claim(turn_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed_first, claimed_second = list(pool.map(claim, [first.turn_id, second.turn_id]))

    assert claimed_first.execution_token
    assert claimed_second.execution_token
    with factory() as database:
        assert database.get(DiscordSessionTurn, first.turn_id).status == "running"
        assert database.get(DiscordSessionTurn, second.turn_id).status == "running"


def test_heartbeat_requires_current_owner_and_cancel_is_queued_only(turn_resources):
    _, prefix, resolver, _, service = turn_resources
    session = resolver.resolve(prefix, "ownership")
    running = enqueue_turn(service, session.session_id, "m1", "one")
    queued = enqueue_turn(service, session.session_id, "m2", "two")
    claim = service.claim(running.turn_id)

    service.heartbeat(running.turn_id, claim.execution_token or "")
    with pytest.raises(DiscordTurnOwnershipError):
        service.heartbeat(running.turn_id, "not-the-owner")
    cancelled = service.cancel(queued.turn_id, "Discord message deleted before execution.")
    assert cancelled.status == "cancelled"
    with pytest.raises(DiscordTurnOwnershipError):
        service.cancel(running.turn_id)


def test_execute_persists_response_until_delivery_ack_and_then_unlocks(turn_resources):
    factory, prefix, resolver, chat, service = turn_resources
    session = resolver.resolve(prefix, "execute")
    first = enqueue_turn(service, session.session_id, "m1", "one", "Discord prompt")
    second = enqueue_turn(service, session.session_id, "m2", "two")

    execution = service.execute(first.turn_id)
    assert execution.status == "running"
    assert execution.answer == "answer:one"
    assert execution.execution_token
    assert len(chat.calls) == 1
    assert chat.calls[0]["message"] == "one"
    assert chat.calls[0]["conversation_id"] == str(session.backend_conversation_id)
    assert chat.calls[0]["system_prompt"] == "Discord prompt"
    assert "author_id=author-1" in chat.calls[0]["current_model_message"]["content"]
    assert service.claim(second.turn_id).execution_token is None

    completed = service.complete(
        first.turn_id,
        execution.execution_token or "",
        [f"bot-{first.turn_id}"],
    )
    assert completed.status == "completed"
    assert service.claim(second.turn_id).execution_token is not None
    with factory() as database:
        row = database.get(DiscordSessionTurn, first.turn_id)
        assert row.response_text == "answer:one"
        assert row.model_used == "fake-model"


def test_operator_stop_terminally_cancels_running_and_queued_turns(turn_resources):
    factory, prefix, resolver, _, service = turn_resources
    session = resolver.resolve(prefix, "operator-stop")
    running = enqueue_turn(service, session.session_id, "m1", "one")
    queued = enqueue_turn(service, session.session_id, "m2", "two")
    claim = service.claim(running.turn_id)

    cancelled = service.cancel_open_for_operator_stop()

    assert [result.turn_id for result in cancelled] == [
        running.turn_id,
        queued.turn_id,
    ]
    assert all(result.status == "cancelled" for result in cancelled)
    with pytest.raises(DiscordTurnOwnershipError):
        service.complete(
            running.turn_id,
            claim.execution_token or "",
            [f"bot-{running.turn_id}"],
        )
    with factory() as database:
        rows = [
            database.get(DiscordSessionTurn, running.turn_id),
            database.get(DiscordSessionTurn, queued.turn_id),
        ]
        assert all(row is not None for row in rows)
        assert all(row.status == "cancelled" for row in rows)
        assert all(row.completed_at is not None for row in rows)
        assert all(row.worker_id is None for row in rows)
        assert all(row.lease_expires_at is None for row in rows)
        assert all(row.heartbeat_at is None for row in rows)
        assert all("stopped by the operator" in row.error for row in rows)


def test_cancelled_undelivered_response_is_not_used_as_discord_history(
    turn_resources,
):
    factory, prefix, resolver, chat, service = turn_resources
    session = resolver.resolve(prefix, "cancelled-context")
    first = enqueue_turn(service, session.session_id, "m1", "hidden answer")
    execution = service.execute(first.turn_id)
    assert execution.answer

    service.cancel_open_for_operator_stop()
    second = enqueue_turn(service, session.session_id, "m2", "visible question")
    next_execution = service.execute(second.turn_id)

    assert next_execution.answer
    assert chat.calls[-1]["model_history"] == []
    with factory() as database:
        first_row = database.get(DiscordSessionTurn, first.turn_id)
        assert first_row.status == "cancelled"
        assert first_row.response_text == "answer:hidden answer"


def test_stale_recovery_revokes_old_owner_and_retries_same_sequence(turn_resources):
    factory, prefix, resolver, _, service = turn_resources
    session = resolver.resolve(prefix, "stale")
    turn = enqueue_turn(service, session.session_id, "m1", "one")
    claimed = service.claim(turn.turn_id)
    assert claimed.execution_token
    with factory.begin() as database:
        row = database.get(DiscordSessionTurn, turn.turn_id)
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    recovered = service.recover_stale()
    assert [result.turn_id for result in recovered] == [turn.turn_id]
    assert recovered[0].status == "queued"
    with pytest.raises(DiscordTurnOwnershipError):
        service.heartbeat(turn.turn_id, claimed.execution_token or "")
    retried = service.claim(turn.turn_id)
    assert retried.execution_token
    assert retried.sequence_number == turn.sequence_number
    with factory() as database:
        assert database.get(DiscordSessionTurn, turn.turn_id).attempt_count == 2


def test_max_attempts_fails_head_and_allows_next_turn(turn_resources):
    factory, prefix, resolver, chat, _ = turn_resources
    service = DiscordTurnService(factory, resolver, chat, lease_seconds=30, max_attempts=1)
    session = resolver.resolve(prefix, "exhausted")
    first = enqueue_turn(service, session.session_id, "m1", "one")
    second = enqueue_turn(service, session.session_id, "m2", "two")
    claimed = service.claim(first.turn_id)
    with factory.begin() as database:
        database.get(DiscordSessionTurn, first.turn_id).lease_expires_at = (
            datetime.now(UTC) - timedelta(seconds=1)
        )

    recovered = service.recover_stale()
    assert recovered[0].status == "failed"
    assert service.claim(second.turn_id).execution_token is not None
    with pytest.raises(DiscordTurnOwnershipError):
        service.complete(
            first.turn_id,
            claimed.execution_token or "",
            [f"bot-{first.turn_id}"],
        )


def test_retryable_failure_preserves_sequence_and_permanent_failure_unblocks(turn_resources):
    _, prefix, resolver, _, service = turn_resources
    session = resolver.resolve(prefix, "failures")
    first = enqueue_turn(service, session.session_id, "m1", "one")
    second = enqueue_turn(service, session.session_id, "m2", "two")
    claimed = service.claim(first.turn_id)

    retry = service.fail(first.turn_id, claimed.execution_token or "", "temporary", retryable=True)
    assert retry.status == "queued"
    assert retry.sequence_number == first.sequence_number
    assert service.claim(second.turn_id).execution_token is None

    retried = service.claim(first.turn_id)
    failed = service.fail(first.turn_id, retried.execution_token or "", "permanent", retryable=False)
    assert failed.status == "failed"
    assert service.claim(second.turn_id).execution_token is not None


def test_orphan_execution_requeues_on_one_replacement_session(turn_resources):
    factory, prefix, resolver, _, _ = turn_resources
    missing_chat = FakeChatService(missing=True)
    service = DiscordTurnService(factory, resolver, missing_chat, lease_seconds=30)
    original_session = resolver.resolve(prefix, "orphan")
    turn = enqueue_turn(service, original_session.session_id, "m1", "one")
    later_turn = enqueue_turn(
        service,
        original_session.session_id,
        "m2",
        "two",
        reply_to_discord_message_id="m1",
    )
    with factory.begin() as database:
        database.execute(
            delete(Conversation).where(
                Conversation.id == str(original_session.backend_conversation_id)
            )
        )

    result = service.execute(turn.turn_id)
    later_result = service.execute(later_turn.turn_id)

    assert result.status == "requeued"
    assert result.replacement_turn_id is not None
    assert later_result.status == "requeued"
    assert later_result.replacement_turn_id is not None
    with factory() as database:
        old_session = database.get(DiscordConversationSession, original_session.session_id)
        old_turn = database.get(DiscordSessionTurn, turn.turn_id)
        replacement = database.get(DiscordSessionTurn, result.replacement_turn_id)
        later_replacement = database.get(
            DiscordSessionTurn,
            later_result.replacement_turn_id,
        )
        assert old_session.status == "orphaned"
        assert old_turn.status == "failed"
        assert replacement.status == "queued"
        assert replacement.sequence_number == 1
        assert later_replacement.sequence_number == 2
        assert later_replacement.reply_to_discord_message_id == "m1"
        resolved_target = DiscordSessionRepository(database).find_reply_target_turn(
            later_replacement.session_id,
            later_replacement.reply_to_discord_message_id,
            before_sequence=later_replacement.sequence_number,
        )
        assert resolved_target is not None
        assert resolved_target.id == replacement.id
        active = list(
            database.scalars(
                select(DiscordConversationSession).where(
                    DiscordConversationSession.guild_id == prefix,
                    DiscordConversationSession.channel_id == "orphan",
                    DiscordConversationSession.status == "active",
                )
            )
        )
        assert len(active) == 1


def test_agent_tools_gated_by_guild_allowlist(turn_resources):
    # Buoc 2 (28/08): the document corpus is backend-wide, so tools only run
    # for allowlisted guilds; everyone else degrades to plain chat.
    factory, prefix, resolver, chat, _ = turn_resources
    home_guild = f"{prefix}-home"
    service = DiscordTurnService(
        factory,
        resolver,
        chat,
        lease_seconds=30,
        agent_tools_enabled=True,
        agent_tools_guild_allowlist=frozenset({home_guild}),
    )
    home = resolver.resolve(home_guild, "tools")
    foreign = resolver.resolve(f"{prefix}-foreign", "tools")

    first = enqueue_turn(service, home.session_id, "m-tools-1", "tim tai lieu")
    service.execute(first.turn_id)
    second = enqueue_turn(service, foreign.session_id, "m-tools-2", "tim tai lieu")
    service.execute(second.turn_id)

    assert chat.calls[-2]["use_tools"] is True
    assert chat.calls[-1]["use_tools"] is False


def test_agent_tools_empty_allowlist_fails_closed_and_none_allows_all(turn_resources):
    # Review finding 28/08: an EMPTY allowlist must deny every guild — a
    # misconfiguration cannot reopen the cross-guild document leak. None
    # (explicit "*" in settings) keeps the historical allow-everywhere shape.
    factory, prefix, resolver, chat, _ = turn_resources
    closed = DiscordTurnService(
        factory,
        resolver,
        chat,
        lease_seconds=30,
        agent_tools_enabled=True,
        agent_tools_guild_allowlist=frozenset(),
    )
    session = resolver.resolve(f"{prefix}-anyguild", "tools")
    turn = enqueue_turn(closed, session.session_id, "m-tools-3", "xin chao")
    closed.execute(turn.turn_id)
    assert chat.calls[-1]["use_tools"] is False

    open_service = DiscordTurnService(
        factory,
        resolver,
        chat,
        lease_seconds=30,
        agent_tools_enabled=True,
        agent_tools_guild_allowlist=None,
    )
    # A fresh session: the still-running turn above would otherwise block
    # this one behind the per-session FIFO.
    other_session = resolver.resolve(f"{prefix}-anyguild", "tools-open")
    turn = enqueue_turn(open_service, other_session.session_id, "m-tools-4", "xin chao")
    open_service.execute(turn.turn_id)
    assert chat.calls[-1]["use_tools"] is True
