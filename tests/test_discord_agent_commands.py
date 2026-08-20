"""P2-3: the /memory and /status commands — client methods and reply formats."""
from __future__ import annotations

import asyncio

import httpx

from discord_bot.api_client import (
    BackendAgentMemory,
    LocalAgentClient,
    LocalAgentSettings,
)
from discord_bot.client import format_agent_memories, format_health


def test_list_agent_memories_sends_filters_and_parses_rows() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=[
            {"canonical_fact": "Người dùng thích trả lời ngắn gọn.", "memory_type": "preference", "version": 2, "applied_by": "agent"},
            {"canonical_fact": 123},  # malformed row is dropped, not fatal
        ])

    async def scenario() -> list[BackendAgentMemory]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend", api_key="secret-key"), http)
            return await client.list_agent_memories("guild-1", "user-9")

    memories = asyncio.run(scenario())
    assert seen["path"] == "/api/memory-review/applied"
    assert seen["params"] == {"guild_id": "guild-1", "subject_id": "user-9"}
    assert len(memories) == 1
    assert memories[0].applied_by == "agent" and memories[0].version == 2


def test_backend_health_returns_the_raw_payload() -> None:
    async def scenario() -> dict:
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"status": "ok", "postgres": "ok"}))
        async with httpx.AsyncClient(transport=transport, base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            return await client.backend_health()

    payload = asyncio.run(scenario())
    assert payload["status"] == "ok" and payload["postgres"] == "ok"


def test_format_agent_memories_escapes_markdown_and_labels_reviewers() -> None:
    text = format_agent_memories([
        BackendAgentMemory("Thích file *quan_trong*.md", "preference", 1, "agent"),
        BackendAgentMemory("Dùng RAM DDR4", "configuration", 3, "dashboard"),
    ])
    assert "Agent đang nhớ 2 điều" in text
    assert "\\*quan\\_trong\\*" in text  # markdown renders literally
    assert "🤖 tự áp dụng" in text and "👤 người duyệt" in text
    assert "v3" in text


def test_format_agent_memories_empty_state() -> None:
    assert "chưa nhớ điều gì" in format_agent_memories([])


def test_format_health_marks_ok_disabled_and_broken_components() -> None:
    text = format_health({
        "status": "degraded",
        "postgres": "ok",
        "redis": "ok",
        "qdrant": "ok",
        "ollama": "error",
        "worker_memory": "ok",
        "outbox_dispatcher": "disabled",
        "backup": "ok",
        "backup_age_hours": "3.2",
    })
    assert text.startswith("⚠️ **Local AI Core: degraded**")
    assert "✅ PostgreSQL: ok" in text
    assert "⚠️ Ollama: error" in text
    assert "➖ Outbox: disabled" in text
    assert "Backup: ok · 3.2h tuổi" in text


def test_format_health_all_ok() -> None:
    payload = {key: "ok" for key, _ in (
        ("postgres", ""), ("redis", ""), ("qdrant", ""), ("ollama", ""),
        ("worker_memory", ""), ("outbox_dispatcher", ""), ("backup", ""),
    )}
    payload["status"] = "ok"
    text = format_health(payload)
    assert text.startswith("✅ **Local AI Core: ok**")
    assert "⚠️" not in text
