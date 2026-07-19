from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from discord_bot.api_client import BackendAuthenticationError, BackendConversationNotFoundError, BackendTimeoutError, LocalAgentClient, LocalAgentSettings
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
