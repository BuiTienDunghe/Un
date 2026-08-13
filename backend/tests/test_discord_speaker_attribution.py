from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import (
    Conversation,
    DiscordConversationSession,
    DiscordSessionTurn,
    Message,
)
from app.services.chat_service import ChatService
from app.services.discord_session_service import DiscordSessionService
from app.services.discord_speaker_context import build_discord_speaker_context
from app.services.discord_turn_service import DiscordTurnService
from app.stores.postgres_auxiliary_store import PostgresAuxiliaryStore


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


class CapturingRouter:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, mode, messages):
        assert mode == "general"
        self.calls.append(messages)
        return "Dũng đã nói câu đầu; Tuấn đang hỏi lại.", "speaker-test-model"


class SilentLogging:
    def log_request(self, *args, **kwargs):
        return None


@pytest.fixture
def speaker_resources():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    prefix = f"sprint2a-{uuid4().hex}"
    resolver = DiscordSessionService(factory)
    router = CapturingRouter()
    chat = ChatService(
        PostgresAuxiliaryStore(factory),
        router,
        SilentLogging(),
        history_limit=12,
    )
    service = DiscordTurnService(factory, resolver, chat, lease_seconds=30)
    yield factory, prefix, resolver, router, service
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


def test_shared_session_model_input_keeps_each_discord_speaker(
    speaker_resources,
):
    factory, prefix, resolver, router, service = speaker_resources
    session = resolver.resolve(prefix, "shared-channel")
    first = service.enqueue(
        session.session_id,
        "message-1",
        "Dự án dùng PostgreSQL.",
        "Discord prompt",
        author_id="author-dung",
        author_display_name="Dũng",
    )
    first_execution = service.execute(first.turn_id)
    service.complete(
        first.turn_id,
        first_execution.execution_token or "",
        [f"bot-{first.turn_id}"],
    )

    second = service.enqueue(
        session.session_id,
        "message-2",
        "Chúng ta vừa nói gì?",
        "Discord prompt",
        author_id="author-tuan",
        author_display_name="Tuấn",
        reply_to_discord_message_id="message-1",
    )
    second_execution = service.execute(second.turn_id)

    assert second_execution.answer == "Dũng đã nói câu đầu; Tuấn đang hỏi lại."
    model_input = router.calls[-1]
    assert model_input[0] == {"role": "system", "content": "Discord prompt"}
    instruction = model_input[1]["content"]
    assert "Các author_id khác nhau là những người khác nhau." in instruction
    assert "Không gán phát ngôn của người khác cho người đang hỏi." in instruction
    assert "Nếu message cũ thiếu author metadata" in instruction

    attributed_history = model_input[2]["content"]
    current_speaker = model_input[-1]["content"]
    assert "[Dũng | author_id=author-dung]" in attributed_history
    assert "Dự án dùng PostgreSQL." in attributed_history
    assert "Người đang hỏi: Tuấn | author_id=author-tuan" in current_speaker
    assert "reply_to_discord_message_id=message-1" in current_speaker
    assert "author-tuan" not in attributed_history
    assert "author-dung" not in current_speaker
    reply_target = model_input[-2]["content"]
    assert "Discord reply target" in reply_target
    assert "discord_message_id=message-1" in reply_target
    assert "author_id=author-dung" in reply_target
    assert "same_author_as_current=false" in reply_target
    assert "Dự án dùng PostgreSQL." in reply_target

    with factory() as database:
        rows = list(
            database.scalars(
                select(DiscordSessionTurn)
                .where(DiscordSessionTurn.session_id == session.session_id)
                .order_by(DiscordSessionTurn.sequence_number)
            )
        )
        assert [row.author_id for row in rows] == [
            "author-dung",
            "author-tuan",
        ]
        assert rows[1].reply_to_discord_message_id == "message-1"
        assert len({row.session_id for row in rows}) == 1
        assert str(session.backend_conversation_id) == str(
            database.get(
                DiscordConversationSession,
                session.session_id,
            ).backend_conversation_id
        )
        persisted_user_content = list(
            database.scalars(
                select(Message.content)
                .where(
                    Message.conversation_id
                    == str(session.backend_conversation_id),
                    Message.role == "user",
                )
                .order_by(Message.id)
            )
        )
        assert persisted_user_content == [
            "Dự án dùng PostgreSQL.",
            "Chúng ta vừa nói gì?",
        ]


def _turn(
    message: str,
    author_id: str | None,
    display_name: str | None,
    *,
    response: str | None = "answer",
    reply_to: str | None = None,
):
    return SimpleNamespace(
        request_text=message,
        response_text=response,
        author_id=author_id,
        author_display_name=display_name,
        reply_to_discord_message_id=reply_to,
    )


def test_same_display_name_is_distinguished_by_stable_author_id():
    context = build_discord_speaker_context(
        [_turn("first", "author-a", "Alex")],
        _turn("second", "author-b", "Alex", response=None),
    )

    assert "[Alex | author_id=author-a]" in context.history[0]["content"]
    assert (
        "[Người đang hỏi: Alex | author_id=author-b]"
        in context.current_message["content"]
    )


def test_display_name_change_does_not_change_author_identity():
    context = build_discord_speaker_context(
        [
            _turn("before rename", "stable-author", "Old Name"),
            _turn("after rename", "stable-author", "New Name"),
        ],
        _turn("current", "other-author", "Other", response=None),
    )

    user_messages = [
        item["content"] for item in context.history if item["role"] == "user"
    ]
    assert "[Old Name | author_id=stable-author]" in user_messages[0]
    assert "[New Name | author_id=stable-author]" in user_messages[1]


def test_missing_legacy_author_is_explicitly_unknown_and_never_guessed():
    context = build_discord_speaker_context(
        [_turn("legacy statement", None, None)],
        _turn("who said that?", "current-author", "Current", response=None),
    )

    legacy = context.history[0]["content"]
    assert "Không xác định được người nói" in legacy
    assert "author_id=unknown" in legacy
    assert "current-author" not in legacy
