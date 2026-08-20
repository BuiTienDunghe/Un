from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import (
    Conversation,
    DiscordConversationSession,
    DiscordSessionTurn,
    DiscordTurnDelivery,
)
from app.services.discord_session_service import DiscordSessionService
from app.services.discord_turn_service import (
    DiscordTurnDeliveryConflictError,
    DiscordTurnService,
)


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


class CapturingChatService:
    history_limit = 12

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
    ):
        self.calls.append(
            {
                "message": message,
                "conversation_id": conversation_id,
                "model_history": model_history,
                "current_model_message": current_model_message,
                "context_system_prompt": context_system_prompt,
                "system_prompt": system_prompt,
            }
        )
        return f"answer:{message}", "delivery-model", conversation_id, 1


@pytest.fixture
def correlation_resources():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    prefix = f"sprint2a3-{uuid4().hex}"
    resolver = DiscordSessionService(factory)
    chat = CapturingChatService()
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
            database.execute(
                delete(Conversation).where(Conversation.id.in_(conversation_ids))
            )


def _enqueue(
    service: DiscordTurnService,
    session_id,
    message_id: str,
    message: str,
    *,
    author_id: str = "author-a",
    display_name: str = "Author A",
    reply_to: str | None = None,
):
    return service.enqueue(
        session_id,
        message_id,
        message,
        author_id=author_id,
        author_display_name=display_name,
        reply_to_discord_message_id=reply_to,
    )


def _execute_and_deliver(
    service: DiscordTurnService,
    turn,
    response_ids: list[str],
):
    execution = service.execute(turn.turn_id)
    assert execution.answer
    assert execution.execution_token
    completed = service.complete(
        turn.turn_id,
        execution.execution_token,
        response_ids,
    )
    assert completed.status == "completed"
    return execution


def _target_block(chat: CapturingChatService) -> str:
    model_history = chat.calls[-1]["model_history"]
    assert isinstance(model_history, list)
    return model_history[-1]["content"]


def test_completion_persists_all_chunks_and_same_ids_are_idempotent(
    correlation_resources,
):
    factory, prefix, resolver, _, service = correlation_resources
    session = resolver.resolve(prefix, "delivery")
    turn = _enqueue(service, session.session_id, "source-1", "question")
    execution = service.execute(turn.turn_id)
    response_ids = ["bot-response-1", "bot-response-2"]

    first = service.complete(
        turn.turn_id,
        execution.execution_token or "",
        response_ids,
    )
    retry = service.complete(
        turn.turn_id,
        execution.execution_token or "",
        response_ids,
    )

    assert first.status == retry.status == "completed"
    with factory() as database:
        deliveries = list(
            database.scalars(
                select(DiscordTurnDelivery)
                .where(DiscordTurnDelivery.turn_id == turn.turn_id)
                .order_by(DiscordTurnDelivery.chunk_index)
            )
        )
        assert [row.discord_message_id for row in deliveries] == response_ids
        assert [row.chunk_index for row in deliveries] == [0, 1]


def test_completion_with_different_ids_is_an_explicit_conflict(
    correlation_resources,
):
    _, prefix, resolver, _, service = correlation_resources
    session = resolver.resolve(prefix, "conflict")
    turn = _enqueue(service, session.session_id, "source-conflict", "question")
    execution = service.execute(turn.turn_id)
    service.complete(
        turn.turn_id,
        execution.execution_token or "",
        ["bot-original"],
    )

    with pytest.raises(DiscordTurnDeliveryConflictError):
        service.complete(
            turn.turn_id,
            execution.execution_token or "",
            ["bot-different"],
        )


def test_one_discord_response_id_cannot_link_two_turns(correlation_resources):
    _, prefix, resolver, _, service = correlation_resources
    session = resolver.resolve(prefix, "global-unique")
    first = _enqueue(service, session.session_id, "source-first", "first")
    second = _enqueue(service, session.session_id, "source-second", "second")
    _execute_and_deliver(service, first, ["shared-bot-response"])
    second_execution = service.execute(second.turn_id)

    with pytest.raises(DiscordTurnDeliveryConflictError):
        service.complete(
            second.turn_id,
            second_execution.execution_token or "",
            ["shared-bot-response"],
        )


def test_reply_to_bot_response_resolves_originating_turn(correlation_resources):
    _, prefix, resolver, chat, service = correlation_resources
    session = resolver.resolve(prefix, "bot-reply")
    origin = _enqueue(
        service,
        session.session_id,
        "origin-user-message",
        "Account A owns milk tea",
        author_id="account-a",
        display_name="Alpha",
    )
    _execute_and_deliver(service, origin, ["origin-bot-response"])
    current = _enqueue(
        service,
        session.session_id,
        "current-user-message",
        "What did the bot answer?",
        author_id="account-b",
        display_name="Beta",
        reply_to="origin-bot-response",
    )

    service.execute(current.turn_id)

    block = _target_block(chat)
    assert "resolution_status=resolved_bot_response" in block
    assert "discord_message_id=origin-bot-response" in block
    assert "originating_sequence=1" in block
    assert "originating_author_id=account-a" in block
    assert "same_originating_author_as_current=false" in block
    assert "Originating user request:\nAccount A owns milk tea" in block
    assert "Assistant response:\nanswer:Account A owns milk tea" in block
    current_block = chat.calls[-1]["current_model_message"]["content"]
    assert "author_id=account-b" in current_block
    assert "reply_to_discord_message_id=origin-bot-response" in current_block


def test_bot_response_target_outside_history_window_still_resolves(
    correlation_resources,
):
    _, prefix, resolver, chat, service = correlation_resources
    session = resolver.resolve(prefix, "outside-window")
    for index in range(1, 8):
        turn = _enqueue(
            service,
            session.session_id,
            f"user-{index}",
            f"origin content {index}",
            author_id=f"author-{index}",
            display_name=f"Author {index}",
        )
        _execute_and_deliver(service, turn, [f"bot-{index}"])
    current = _enqueue(
        service,
        session.session_id,
        "outside-current",
        "reply to old bot response",
        author_id="current",
        display_name="Current",
        reply_to="bot-1",
    )

    service.execute(current.turn_id)

    ordinary_history = chat.calls[-1]["model_history"][:-1]
    assert all(
        "origin content 1" not in item["content"]
        for item in ordinary_history
    )
    block = _target_block(chat)
    assert "originating_sequence=1" in block
    assert "origin content 1" in block
    assert "answer:origin content 1" in block


def test_bot_response_never_cross_resolves_between_sessions(
    correlation_resources,
):
    _, prefix, resolver, chat, service = correlation_resources
    source_session = resolver.resolve(prefix, "source-session")
    current_session = resolver.resolve(prefix, "current-session")
    origin = _enqueue(
        service,
        source_session.session_id,
        "source-message",
        "private similar content",
    )
    _execute_and_deliver(service, origin, ["private-bot-response"])
    current = _enqueue(
        service,
        current_session.session_id,
        "current-message",
        "private similar content",
        author_id="other",
        display_name="Other",
        reply_to="private-bot-response",
    )

    service.execute(current.turn_id)

    block = _target_block(chat)
    assert "resolution_status=outside_session" in block
    assert "private similar content" not in block
    assert "originating_author_id" not in block


def test_legacy_turn_without_delivery_correlation_is_unresolved(
    correlation_resources,
):
    factory, prefix, resolver, chat, service = correlation_resources
    session = resolver.resolve(prefix, "legacy")
    origin = _enqueue(
        service,
        session.session_id,
        "legacy-source",
        "legacy request",
    )
    _execute_and_deliver(service, origin, ["temporary-correlation"])
    with factory.begin() as database:
        database.execute(
            delete(DiscordTurnDelivery).where(
                DiscordTurnDelivery.turn_id == origin.turn_id
            )
        )
    current = _enqueue(
        service,
        session.session_id,
        "legacy-current",
        "reply to old bot message",
        author_id="current",
        display_name="Current",
        reply_to="legacy-bot-message-with-no-row",
    )

    service.execute(current.turn_id)

    block = _target_block(chat)
    assert "resolution_status=not_found" in block
    assert "legacy request" not in block
    assert "Assistant response:" not in block


def test_failed_delivery_does_not_persist_response_ids(correlation_resources):
    factory, prefix, resolver, _, service = correlation_resources
    session = resolver.resolve(prefix, "failed-delivery")
    turn = _enqueue(service, session.session_id, "failed-source", "question")
    execution = service.execute(turn.turn_id)

    failed = service.fail(
        turn.turn_id,
        execution.execution_token or "",
        "Discord send failed",
        retryable=False,
    )

    assert failed.status == "failed"
    with factory() as database:
        assert (
            database.scalar(
                select(DiscordTurnDelivery).where(
                    DiscordTurnDelivery.turn_id == turn.turn_id
                )
            )
            is None
        )

