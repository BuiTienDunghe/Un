from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord
import pytest

from discord_bot.api_client import (
    BackendAnswer,
    BackendDiscordSession,
    BackendDiscordTurn,
    BackendDiscordTurnExecution,
    BackendTimeoutError,
)
from discord_bot.main import (
    DiscordConversationGateway,
    DiscordSettings,
    PreparedDiscordAnswer,
    discord_author_metadata,
    discord_reply_message_id,
    send_discord_answer,
)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.completion_failures = 0

    async def ask_with_conversation(self, question, *, conversation_id=None, system_prompt=None):
        self.calls.append(("legacy", question, conversation_id, system_prompt))
        return BackendAnswer("legacy answer", "legacy-conversation")

    async def resolve_discord_session(self, guild_id, channel_id, thread_id=None):
        self.calls.append(("resolve", guild_id, channel_id, thread_id))
        return BackendDiscordSession("session", "conversation", False, "active")

    async def enqueue_discord_turn(
        self,
        session_id,
        message_id,
        message,
        *,
        author_id,
        author_display_name,
        reply_to_discord_message_id=None,
        system_prompt=None,
    ):
        self.calls.append(
            (
                "enqueue",
                session_id,
                message_id,
                message,
                author_id,
                author_display_name,
                reply_to_discord_message_id,
                system_prompt,
            )
        )
        return BackendDiscordTurn("turn", session_id, 1, "queued", True)

    async def execute_discord_turn(self, turn_id):
        self.calls.append(("execute", turn_id))
        return BackendDiscordTurnExecution(
            turn_id,
            "session",
            1,
            "running",
            "persistent answer",
            "model",
            "token",
            None,
        )

    async def complete_discord_turn(self, turn_id, token, response_message_ids):
        self.calls.append(
            ("complete", turn_id, token, tuple(response_message_ids))
        )
        if self.completion_failures:
            self.completion_failures -= 1
            raise BackendTimeoutError("completion response was lost")
        return "completed"

    async def fail_discord_turn(self, turn_id, token, error, *, retryable):
        self.calls.append(("fail", turn_id, token, error, retryable))
        return "queued" if retryable else "failed"


def guild():
    return SimpleNamespace(id=10, name="Guild", member_count=0, members=[])


def channel():
    return SimpleNamespace(id=20, type=discord.ChannelType.text)


def test_feature_flag_false_uses_only_legacy_ram_path():
    async def scenario():
        client = FakeClient()
        gateway = DiscordConversationGateway(client, "prompt", 0, False)
        prepared = await gateway.prepare(
            "question",
            guild(),
            channel(),
            30,
            "Legacy User",
            "message",
        )
        assert prepared and prepared.answer == "legacy answer"
        assert [call[0] for call in client.calls] == ["legacy"]
        assert gateway.conversations

    asyncio.run(scenario())


def test_feature_flag_true_uses_canonical_resolver_fifo_and_delivery_ack():
    async def scenario():
        client = FakeClient()
        gateway = DiscordConversationGateway(client, "prompt", 0, True)
        prepared = await gateway.prepare(
            "question",
            guild(),
            channel(),
            999,
            "Persistent User",
            "message",
            "parent-message",
        )
        assert prepared and prepared.answer == "persistent answer"
        await gateway.delivered(prepared, ["bot-response-1"])
        assert [call[0] for call in client.calls] == [
            "resolve",
            "enqueue",
            "execute",
            "complete",
        ]
        assert client.calls[0] == ("resolve", "10", "20", None)
        assert client.calls[1][4:7] == (
            "999",
            "Persistent User",
            "parent-message",
        )
        assert client.calls[-1] == (
            "complete",
            "turn",
            "token",
            ("bot-response-1",),
        )

    asyncio.run(scenario())


def test_runtime_default_feature_flag_is_false(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "test-only")
    monkeypatch.delenv("DISCORD_PERSISTENT_SESSIONS_ENABLED", raising=False)
    monkeypatch.delenv("DISCORD_TURN_EXECUTE_TIMEOUT_SECONDS", raising=False)
    settings = DiscordSettings.from_env()
    assert settings.persistent_sessions_enabled is False
    assert settings.local_agent.turn_execute_timeout_seconds == 180


def test_runtime_can_override_turn_execute_timeout(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "test-only")
    monkeypatch.setenv("DISCORD_TURN_EXECUTE_TIMEOUT_SECONDS", "240")

    settings = DiscordSettings.from_env()

    assert settings.local_agent.turn_execute_timeout_seconds == 240


def test_bot_reads_author_and_reply_metadata_from_discord_objects():
    author = SimpleNamespace(id=123, display_name="Dũng")
    message = SimpleNamespace(
        reference=SimpleNamespace(message_id=456),
    )

    assert discord_author_metadata(author) == ("123", "Dũng")
    assert discord_reply_message_id(message) == "456"
    assert discord_reply_message_id(SimpleNamespace(reference=None)) is None


def test_deleted_discord_message_marks_turn_permanently_failed():
    async def scenario():
        client = FakeClient()
        gateway = DiscordConversationGateway(client, "prompt", 0, True)
        prepared = await gateway.prepare(
            "question",
            guild(),
            channel(),
            30,
            "Deleted User",
            "message",
        )
        assert prepared is not None
        await gateway.delivery_failed(
            prepared,
            "Discord source message was deleted.",
            retryable=False,
        )
        assert client.calls[-1] == (
            "fail",
            "turn",
            "token",
            "Discord source message was deleted.",
            False,
        )

    asyncio.run(scenario())


def test_send_success_then_completion_retry_never_resends_discord_content():
    class FakeChannel:
        def __init__(self):
            self.sent: list[str] = []

        async def send(self, content):
            self.sent.append(content)
            return SimpleNamespace(id=200 + len(self.sent))

    class FakeSource:
        def __init__(self):
            self.replies: list[str] = []

        async def reply(self, content, *, mention_author):
            assert mention_author is False
            self.replies.append(content)
            return SimpleNamespace(id=100)

    async def scenario():
        client = FakeClient()
        client.completion_failures = 2
        gateway = DiscordConversationGateway(client, "prompt", 0, True)
        prepared = PreparedDiscordAnswer("x" * 4_500, "turn", "token")
        channel = FakeChannel()
        source = FakeSource()

        messages = await send_discord_answer(
            channel,
            prepared.answer,
            reply_to=source,
        )
        await gateway.delivered(
            prepared,
            [str(message.id) for message in messages],
        )

        assert len(source.replies) == 1
        assert len(channel.sent) == len(messages) - 1
        assert len([call for call in client.calls if call[0] == "complete"]) == 3
        assert all(
            call[-1] == tuple(str(message.id) for message in messages)
            for call in client.calls
            if call[0] == "complete"
        )

    asyncio.run(scenario())


def test_discord_send_failure_never_acknowledges_completion():
    class FailingSource:
        async def reply(self, content, *, mention_author):
            raise RuntimeError("Discord send failed")

    async def scenario():
        client = FakeClient()
        gateway = DiscordConversationGateway(client, "prompt", 0, True)
        prepared = PreparedDiscordAnswer("answer", "turn", "token")

        with pytest.raises(RuntimeError, match="Discord send failed"):
            await send_discord_answer(
                SimpleNamespace(send=None),
                prepared.answer,
                reply_to=FailingSource(),
            )

        assert not any(call[0] == "complete" for call in client.calls)
        # The handler calls delivery_failed after this exception; no completion
        # payload or Discord response ID was produced.
        assert gateway.persistent_sessions_enabled is True

    asyncio.run(scenario())
