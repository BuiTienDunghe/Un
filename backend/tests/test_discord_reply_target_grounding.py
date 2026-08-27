from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.discord_repositories import DiscordSessionRepository
from app.postgres.models import (
    Conversation,
    DiscordConversationSession,
    DiscordSessionTurn,
)
from app.services.discord_session_service import DiscordSessionService
from app.services.discord_speaker_context import (
    ReplyTargetContext,
    build_discord_speaker_context,
)
from app.services.discord_turn_service import DiscordTurnService


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
            }
        )
        return f"answer:{message}", "reply-grounding-model", conversation_id, 1


@pytest.fixture
def reply_resources():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    prefix = f"sprint2a2-{uuid4().hex}"
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
    author_id: str,
    display_name: str,
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


def _execute_and_complete(service: DiscordTurnService, turn):
    execution = service.execute(turn.turn_id)
    assert execution.answer
    assert execution.execution_token
    service.complete(
        turn.turn_id,
        execution.execution_token,
        [f"bot-{turn.turn_id}"],
    )
    return execution


def _reply_block(chat: CapturingChatService) -> str:
    model_history = chat.calls[-1]["model_history"]
    assert isinstance(model_history, list)
    assert model_history[-1]["role"] == "user"
    return model_history[-1]["content"]


def test_sequence_22_regression_resolves_exact_same_author_target(
    reply_resources,
):
    _, prefix, resolver, chat, service = reply_resources
    session = resolver.resolve(prefix, "production-regression")
    target = _enqueue(
        service,
        session.session_id,
        "1531028782075609268",
        "tôi là người đã nói về trà sữa chân trâu đường đen",
        author_id="1264408020322881646",
        display_name="Dũnggg",
    )
    _execute_and_complete(service, target)
    distractor = _enqueue(
        service,
        session.session_id,
        "message-dat",
        "tôi có hồng trà kem cheese",
        author_id="1531015317831155876",
        display_name="Đạt",
    )
    _execute_and_complete(service, distractor)
    current = _enqueue(
        service,
        session.session_id,
        "message-current",
        "Tôi có phải cùng người với message tôi đang reply không?",
        author_id="1264408020322881646",
        display_name="Dũnggg",
        reply_to="1531028782075609268",
    )

    _execute_and_complete(service, current)

    block = _reply_block(chat)
    current_content = chat.calls[-1]["current_model_message"]["content"]
    assert "resolution_status=resolved_user_message" in block
    assert "discord_message_id=1531028782075609268" in block
    assert "author_id=1264408020322881646" in block
    assert "same_author_as_current=true" in block
    assert "trà sữa chân trâu đường đen" in block
    assert "hồng trà kem cheese" not in block
    assert "author_id=1264408020322881646" in current_content
    assert "reply_to_discord_message_id=1531028782075609268" in current_content


def test_cross_author_reply_is_explicitly_false(reply_resources):
    _, prefix, resolver, chat, service = reply_resources
    session = resolver.resolve(prefix, "cross-author")
    target = _enqueue(
        service,
        session.session_id,
        "target-a",
        "account A statement",
        author_id="author-a",
        display_name="Alpha",
    )
    _execute_and_complete(service, target)
    current = _enqueue(
        service,
        session.session_id,
        "current-b",
        "account B reply",
        author_id="author-b",
        display_name="Beta",
        reply_to="target-a",
    )

    _execute_and_complete(service, current)

    block = _reply_block(chat)
    assert "author_id=author-a" in block
    assert "same_author_as_current=false" in block
    assert "author_id=author-b" in chat.calls[-1]["current_model_message"]["content"]


def test_same_display_name_different_ids_are_not_merged(reply_resources):
    _, prefix, resolver, chat, service = reply_resources
    session = resolver.resolve(prefix, "same-display")
    target = _enqueue(
        service,
        session.session_id,
        "same-name-a",
        "first account",
        author_id="author-a",
        display_name="Dũnggg",
    )
    _execute_and_complete(service, target)
    current = _enqueue(
        service,
        session.session_id,
        "same-name-b",
        "second account",
        author_id="author-b",
        display_name="Dũnggg",
        reply_to="same-name-a",
    )

    _execute_and_complete(service, current)

    block = _reply_block(chat)
    assert "display_name=Dũnggg" in block
    assert "author_id=author-a" in block
    assert "same_author_as_current=false" in block
    current_content = chat.calls[-1]["current_model_message"]["content"]
    assert "Dũnggg" in current_content
    assert "author_id=author-b" in current_content


def test_renamed_display_same_id_is_same_author(reply_resources):
    _, prefix, resolver, chat, service = reply_resources
    session = resolver.resolve(prefix, "renamed-display")
    target = _enqueue(
        service,
        session.session_id,
        "before-rename",
        "before",
        author_id="stable-b",
        display_name="Đạt",
    )
    _execute_and_complete(service, target)
    current = _enqueue(
        service,
        session.session_id,
        "after-rename",
        "after",
        author_id="stable-b",
        display_name="Phương Anh",
        reply_to="before-rename",
    )

    _execute_and_complete(service, current)

    block = _reply_block(chat)
    assert "display_name=Đạt" in block
    assert "author_id=stable-b" in block
    assert "same_author_as_current=true" in block
    current_content = chat.calls[-1]["current_model_message"]["content"]
    assert "Phương Anh" in current_content
    assert "author_id=stable-b" in current_content


def test_target_outside_history_window_is_still_resolved_exactly(reply_resources):
    _, prefix, resolver, chat, service = reply_resources
    session = resolver.resolve(prefix, "outside-window")
    for index in range(1, 8):
        turn = _enqueue(
            service,
            session.session_id,
            f"old-{index}",
            f"old content {index}",
            author_id=f"author-{index}",
            display_name=f"Author {index}",
        )
        _execute_and_complete(service, turn)
    current = _enqueue(
        service,
        session.session_id,
        "current-outside-window",
        "reply to the oldest turn",
        author_id="current-author",
        display_name="Current",
        reply_to="old-1",
    )

    _execute_and_complete(service, current)

    model_history = chat.calls[-1]["model_history"]
    ordinary_history = model_history[:-1]
    assert all("old content 1" not in item["content"] for item in ordinary_history)
    block = _reply_block(chat)
    assert "discord_message_id=old-1" in block
    assert "sequence=1" in block
    assert "old content 1" in block


def test_missing_target_is_unresolved_and_nearest_message_is_not_selected(
    reply_resources,
):
    _, prefix, resolver, chat, service = reply_resources
    session = resolver.resolve(prefix, "missing")
    nearest = _enqueue(
        service,
        session.session_id,
        "nearest",
        "do not use this nearby hồng trà message as target",
        author_id="other",
        display_name="Other",
    )
    _execute_and_complete(service, nearest)
    current = _enqueue(
        service,
        session.session_id,
        "missing-current",
        "reply with an unknown reference",
        author_id="current",
        display_name="Current",
        reply_to="does-not-exist",
    )

    _execute_and_complete(service, current)

    block = _reply_block(chat)
    assert "resolution_status=not_found" in block
    assert "discord_message_id=does-not-exist" in block
    assert "hồng trà" not in block
    assert "không chọn hoặc suy đoán" in block


def test_legacy_target_has_unknown_author_and_unknown_relationship(reply_resources):
    factory, prefix, resolver, chat, service = reply_resources
    session = resolver.resolve(prefix, "legacy")
    target = _enqueue(
        service,
        session.session_id,
        "legacy-target",
        "legacy content",
        author_id="temporary",
        display_name="Temporary",
    )
    _execute_and_complete(service, target)
    with factory.begin() as database:
        row = database.get(DiscordSessionTurn, target.turn_id)
        assert row is not None
        row.author_id = None
        row.author_display_name = None
    current = _enqueue(
        service,
        session.session_id,
        "legacy-current",
        "who wrote the target?",
        author_id="current",
        display_name="Current",
        reply_to="legacy-target",
    )

    _execute_and_complete(service, current)

    block = _reply_block(chat)
    assert "resolution_status=legacy_unavailable" in block
    assert "author_id=unknown" in block
    assert "same_author_as_current=unknown" in block
    assert "legacy content" in block


def test_cross_session_target_does_not_leak_target_content(reply_resources):
    _, prefix, resolver, chat, service = reply_resources
    source_session = resolver.resolve(prefix, "source-session")
    current_session = resolver.resolve(prefix, "current-session")
    target = _enqueue(
        service,
        source_session.session_id,
        "cross-session-target",
        "private source-session content",
        author_id="source-author",
        display_name="Source",
    )
    _execute_and_complete(service, target)
    current = _enqueue(
        service,
        current_session.session_id,
        "cross-session-current",
        "try cross-session reference",
        author_id="current-author",
        display_name="Current",
        reply_to="cross-session-target",
    )

    _execute_and_complete(service, current)

    block = _reply_block(chat)
    assert "resolution_status=outside_session" in block
    assert "private source-session content" not in block
    assert "author_id=source-author" not in block


def test_retry_keeps_reply_id_and_exact_resolution(reply_resources):
    factory, prefix, resolver, chat, service = reply_resources
    session = resolver.resolve(prefix, "retry")
    target = _enqueue(
        service,
        session.session_id,
        "retry-target",
        "stable target",
        author_id="author-a",
        display_name="A",
    )
    _execute_and_complete(service, target)
    current = _enqueue(
        service,
        session.session_id,
        "retry-current",
        "retrying reply",
        author_id="author-a",
        display_name="A",
        reply_to="retry-target",
    )
    claim = service.claim(current.turn_id)
    retry = service.fail(
        current.turn_id,
        claim.execution_token or "",
        "temporary",
        retryable=True,
    )
    assert retry.status == "queued"

    _execute_and_complete(service, current)

    with factory() as database:
        row = database.get(DiscordSessionTurn, current.turn_id)
        assert row is not None
        assert row.reply_to_discord_message_id == "retry-target"
        assert row.attempt_count == 2
    assert "same_author_as_current=true" in _reply_block(chat)


def test_unknown_legacy_bot_response_is_not_found_and_never_fabricated():
    current = type(
        "CurrentTurn",
        (),
        {
            "request_text": "reply to a bot response",
            "response_text": None,
            "author_id": "current",
            "author_display_name": "Current",
            "reply_to_discord_message_id": "bot-response-id",
        },
    )()
    target = ReplyTargetContext(
        discord_message_id="bot-response-id",
        sequence=None,
        author_id=None,
        author_display_name=None,
        request_text=None,
        resolution_status="not_found",
        same_author_as_current=None,
    )

    context = build_discord_speaker_context([], current, reply_target=target)

    assert context.reply_target_message is not None
    block = context.reply_target_message["content"]
    assert "resolution_status=not_found" in block
    assert "same_author_as_current=unknown" in block
    assert "không chọn hoặc suy đoán" in block


def test_repository_exact_lookup_is_scoped_to_session(reply_resources):
    factory, prefix, resolver, _, service = reply_resources
    first_session = resolver.resolve(prefix, "lookup-a")
    second_session = resolver.resolve(prefix, "lookup-b")
    first = _enqueue(
        service,
        first_session.session_id,
        "shared-external-id",
        "first session",
        author_id="a",
        display_name="A",
    )
    _enqueue(
        service,
        second_session.session_id,
        "shared-external-id",
        "second session",
        author_id="b",
        display_name="B",
    )

    with factory() as database:
        repository = DiscordSessionRepository(database)
        target = repository.find_reply_target_turn(
            first_session.session_id,
            "shared-external-id",
            before_sequence=2,
        )
        assert target is not None
        assert target.id == first.turn_id
        assert target.request_text == "first session"
