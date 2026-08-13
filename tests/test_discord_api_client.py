from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from discord_bot.api_client import BackendAuthenticationError, BackendConversationNotFoundError, BackendDiscordDeliveryConflictError, BackendResponseError, BackendTimeoutError, LocalAgentClient, LocalAgentSettings
from discord_bot.client import DISCORD_MESSAGE_LIMIT, split_for_discord
from discord_bot.main import conversation_key, guild_context


def test_ask_posts_current_backend_chat_schema_without_auth() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["payload"], seen["authorization"] = request.url.path, json.loads(request.content), request.headers.get("Authorization")
        return httpx.Response(200, json={"answer": "Hello from backend", "model_used": "test", "conversation_id": "conv_1", "latency_ms": 1})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            assert await client.ask("Hello") == "Hello from backend"

    asyncio.run(scenario())
    assert seen == {"path": "/chat", "payload": {"message": "Hello", "stream": False}, "authorization": None}


def test_401_refreshes_jwt_once_and_retries() -> None:
    calls: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, request.headers.get("Authorization")))
        if request.url.path == "/chat" and request.headers.get("Authorization") is None:
            return httpx.Response(401, json={"message": "expired"})
        if request.url.path == "/api/login":
            assert json.loads(request.content) == {"username": "user", "password": "password"}
            return httpx.Response(200, json={"access_token": "new-jwt"})
        return httpx.Response(200, json={"answer": "Recovered", "model_used": "test", "conversation_id": "conv_1", "latency_ms": 1})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend", "user", "password"), http)
            assert await client.ask("Hello") == "Recovered"

    asyncio.run(scenario())
    assert calls == [("/chat", None), ("/api/login", None), ("/chat", "Bearer new-jwt")]


def test_timeout_is_reported_without_real_network() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow backend")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            with pytest.raises(BackendTimeoutError):
                await client.ask("Hello")

    asyncio.run(scenario())


def test_401_without_credentials_is_safe_error() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(401)), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            with pytest.raises(BackendAuthenticationError):
                await client.ask("Hello")

    asyncio.run(scenario())


def test_discord_output_is_split_below_platform_limit() -> None:
    parts = split_for_discord("word " * 1_000)
    assert len(parts) > 1
    assert all(len(part) <= DISCORD_MESSAGE_LIMIT for part in parts)


def test_discord_client_sends_separate_system_prompt_and_conversation_key() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"answer": "ok", "model_used": "test", "conversation_id": "conv_1", "latency_ms": 1})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            await client.ask("Hello", conversation_id="discord_abc", system_prompt="Discord persona")

    asyncio.run(scenario())
    assert seen["payload"] == {"message": "Hello", "stream": False, "conversation_id": "discord_abc", "system_prompt": "Discord persona"}


def test_guild_context_is_bounded_and_conversation_key_is_stable() -> None:
    class Member:
        def __init__(self, name: str, bot: bool = False): self.display_name, self.bot = name, bot
    class Guild:
        name, member_count = "Test Server", 3
        members = [Member("An"), Member("Bot", True), Member("Bình")]

    context = guild_context(Guild(), 1)
    assert "Test Server" in context and "An" in context and "Bình" not in context
    assert conversation_key(1, 2, 3) == conversation_key(1, 2, 3)


def test_missing_backend_conversation_is_detectable_for_safe_retry() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(404, json={"error_code": "CONVERSATION_NOT_FOUND"})), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            with pytest.raises(BackendConversationNotFoundError):
                await client.ask_with_conversation("Hello", conversation_id="old-conversation")

    asyncio.run(scenario())


def test_discord_client_resolves_backend_owned_session() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "session_id": "11111111-1111-1111-1111-111111111111",
                "backend_conversation_id": "22222222-2222-2222-2222-222222222222",
                "created": True,
                "status": "active",
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            result = await client.resolve_discord_session("guild", "parent", "thread")
            assert result.created is True
            assert result.backend_conversation_id == "22222222-2222-2222-2222-222222222222"

    asyncio.run(scenario())
    assert seen == {
        "path": "/api/discord/sessions/resolve",
        "payload": {"guild_id": "guild", "channel_id": "parent", "thread_id": "thread"},
    }


def test_discord_client_rejects_empty_session_identifiers() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            with pytest.raises(BackendResponseError):
                await client.resolve_discord_session("guild", " ")

    asyncio.run(scenario())


def test_discord_client_turn_workflow_uses_server_owned_fifo_contract() -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append((request.url.path, payload))
        if request.url.path.endswith("/turns"):
            return httpx.Response(
                200,
                json={
                    "turn_id": "turn-1",
                    "session_id": "session-1",
                    "sequence_number": 1,
                    "status": "queued",
                    "created": True,
                },
            )
        if request.url.path.endswith("/execute"):
            return httpx.Response(
                200,
                json={
                    "turn_id": "turn-1",
                    "session_id": "session-1",
                    "sequence_number": 1,
                    "status": "running",
                    "answer": "answer",
                    "model_used": "model",
                    "execution_token": "server-token",
                    "replacement_turn_id": None,
                },
            )
        return httpx.Response(200, json={"turn_id": "turn-1", "status": "completed"})

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://backend",
        ) as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            turn = await client.enqueue_discord_turn(
                "session-1",
                "message-1",
                "question",
                author_id="author-1",
                author_display_name="Dũng",
                reply_to_discord_message_id="parent-message",
                system_prompt="prompt",
            )
            execution = await client.execute_discord_turn(turn.turn_id)
            assert execution.answer == "answer"
            assert execution.execution_token == "server-token"
            assert await client.complete_discord_turn(
                turn.turn_id,
                execution.execution_token,
                ["discord-response-1"],
            ) == "completed"

    asyncio.run(scenario())
    assert seen == [
        (
            "/api/discord/sessions/session-1/turns",
            {
                "discord_message_id": "message-1",
                "message": "question",
                "author_id": "author-1",
                "author_display_name": "Dũng",
                "reply_to_discord_message_id": "parent-message",
                "system_prompt": "prompt",
            },
        ),
        ("/api/discord/sessions/turns/turn-1/execute", {}),
        (
            "/api/discord/sessions/turns/turn-1/complete",
            {
                "execution_token": "server-token",
                "discord_response_message_ids": ["discord-response-1"],
            },
        ),
    ]


def test_discord_turn_execute_uses_long_model_timeout() -> None:
    observed_timeout: dict[str, float] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed_timeout.update(request.extensions["timeout"])
        return httpx.Response(
            200,
            json={
                "turn_id": "turn-1",
                "session_id": "session-1",
                "sequence_number": 1,
                "status": "running",
                "answer": "answer",
                "model_used": "model",
                "execution_token": "server-token",
                "replacement_turn_id": None,
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://backend",
            timeout=45,
        ) as http:
            client = LocalAgentClient(
                LocalAgentSettings(
                    "http://backend",
                    turn_execute_timeout_seconds=180,
                ),
                http,
            )
            await client.execute_discord_turn("turn-1")

    asyncio.run(scenario())
    assert observed_timeout["read"] == 180
    assert observed_timeout["write"] == 180


def test_discord_completion_surfaces_delivery_conflict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "error": True,
                "error_code": "DISCORD_TURN_DELIVERY_CONFLICT",
                "message": "Turn completion conflicts with persisted delivery IDs.",
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://backend",
        ) as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            with pytest.raises(BackendDiscordDeliveryConflictError):
                await client.complete_discord_turn(
                    "turn-1",
                    "token",
                    ["response-2"],
                )

    asyncio.run(scenario())
