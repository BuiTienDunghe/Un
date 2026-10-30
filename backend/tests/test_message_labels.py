"""Ticket 36: decided suggests, a person decides; nothing reaches a memory on the model's word."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, update

from app.discord.message_labels import MessageLabelService
from app.discord import agent_tools
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import DiscordChannelMessage, DiscordMemory, DiscordMessageLabel
from app.services.agent_service import AgentService, core_tools
from datetime import UTC, datetime
from scripts.decided_worker import run_once

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


@pytest.fixture
def guild(factory):
    name = f"lbl-{uuid4().hex[:10]}"
    yield name
    with factory.begin() as session:
        session.execute(delete(DiscordMessageLabel).where(DiscordMessageLabel.guild_id == name))
        session.execute(delete(DiscordChannelMessage).where(DiscordChannelMessage.guild_id == name))


def heard(factory, guild: str, text: str | None, *, is_bot: bool = False) -> str:
    message_id = uuid4().hex
    with factory.begin() as session:
        session.add(DiscordChannelMessage(
            guild_id=guild, channel_id="c", discord_message_id=message_id, author_id="dung", author_display_name="Dũng",
            is_bot=is_bot, content=text, sent_at=datetime.now(UTC),
        ))
    return message_id


def result(label: str, confidence: float = 0.7) -> dict:
    return {"label": label, "confidence": confidence, "stable": True, "probs": {label: confidence}, "model": "test"}


def ours(service, guild) -> list[tuple]:
    return [row for row in service.unlabelled(limit=1000) if row[1] == guild]


def test_only_peoples_live_messages_wait_for_a_label(factory, guild) -> None:
    service = MessageLabelService(factory)
    person = heard(factory, guild, "Tôi thích trà")
    heard(factory, guild, "Tôi là bot", is_bot=True)
    heard(factory, guild, None)
    assert [row[0] for row in ours(service, guild)] == [person]
    service.record(person, guild, result("fact"))
    assert ours(service, guild) == []


def test_a_suggestion_writes_no_memory_and_waits_for_a_person(factory, guild) -> None:
    service = MessageLabelService(factory)
    service.record(heard(factory, guild, "Tôi dị ứng tôm"), guild, result("fact", 0.99))
    rows = [row for row in service.pending(limit=200) if row["guild_id"] == guild]
    assert len(rows) == 1 and rows[0]["text"] == "Tôi dị ứng tôm"
    assert service.memory_lines(guild) == []
    with factory() as session:
        assert session.scalar(select(DiscordMemory).where(DiscordMemory.guild_id == guild)) is None


def test_only_a_sure_ignore_skips_the_queue(factory, guild) -> None:
    service = MessageLabelService(factory)
    service.record(heard(factory, guild, "Chào"), guild, result("ignore", 0.95))
    service.record(heard(factory, guild, "Chắc tôi nghỉ việc"), guild, result("ignore", 0.6))
    assert [row["text"] for row in service.pending(limit=200) if row["guild_id"] == guild] == ["Chắc tôi nghỉ việc"]


def test_approved_facts_reach_the_turn_and_jokes_never_do(factory, guild) -> None:
    service = MessageLabelService(factory)
    for text, label in (("Tôi dị ứng tôm", "fact"), ("Chốt dùng PostgreSQL", "decision"), ("Tôi là tổng thống", "joke")):
        service.record(heard(factory, guild, text), guild, result(label))
    for row in [r for r in service.pending(limit=200) if r["guild_id"] == guild]:
        service.review(__import__("uuid").UUID(row["id"]), status="approved")
    lines = "\n".join(service.memory_lines(guild))
    assert "dị ứng tôm" in lines and "PostgreSQL" in lines and "tổng thống" not in lines
    assert service.memory_lines("another-guild") == []


def test_a_person_can_correct_reject_and_the_counts_say_so(factory, guild) -> None:
    from uuid import UUID

    service = MessageLabelService(factory)
    first, second = heard(factory, guild, "Đi làm vui lắm =))"), heard(factory, guild, "Mình sắp giàu rồi")
    service.record(first, guild, result("fact"))
    service.record(second, guild, result("joke"))
    rows = {row["text"]: row for row in service.pending(limit=200) if row["guild_id"] == guild}
    service.review(UUID(rows["Đi làm vui lắm =))"]["id"]), status="approved", final_label="joke")
    service.review(UUID(rows["Mình sắp giàu rồi"]["id"]), status="rejected")
    assert [row["text"] for row in service.approved(guild, ("joke",))] == ["Đi làm vui lắm =))"]
    with pytest.raises(ValueError):
        service.review(UUID(rows["Mình sắp giàu rồi"]["id"]), status="approved", final_label="nope")


def test_a_deleted_message_is_gone_from_every_list(factory, guild) -> None:
    from uuid import UUID

    service = MessageLabelService(factory)
    message_id = heard(factory, guild, "Tôi dị ứng tôm")
    service.record(message_id, guild, result("fact"))
    service.review(UUID(service.pending(limit=200)[0]["id"]) if False else UUID([r for r in service.pending(limit=200) if r["guild_id"] == guild][0]["id"]), status="approved")
    assert service.memory_lines(guild)
    with factory.begin() as session:
        session.execute(update(DiscordChannelMessage).where(DiscordChannelMessage.discord_message_id == message_id).values(content=None, deleted_at=datetime.now(UTC)))
    assert service.memory_lines(guild) == []


def test_the_review_api_works_and_needs_the_key(client, mock_ollama, factory, guild, monkeypatch) -> None:
    from app.config.settings import get_settings

    service = MessageLabelService(factory)
    service.record(heard(factory, guild, "Tôi là tổng thống 😂"), guild, result("joke"))
    row = [r for r in client.get("/api/message-labels?limit=200").json() if r["guild_id"] == guild][0]
    assert client.post(f"/api/message-labels/{row['id']}/approve", json={}).json()["final_label"] == "joke"
    assert client.get("/api/message-labels/stats").json()["agreement"]["joke"]["agreed"] >= 1
    assert client.post(f"/api/message-labels/{uuid4()}/reject").status_code == 404
    monkeypatch.setattr(get_settings(), "local_ai_api_key", "secret-key-for-this-test")
    assert client.post(f"/api/message-labels/{row['id']}/reopen").status_code == 401


def test_jokes_come_only_from_this_guild_and_marked_as_jokes(factory, guild) -> None:
    from uuid import UUID

    service = MessageLabelService(factory)
    service.record(heard(factory, guild, "Con mèo là CEO"), guild, result("joke"))
    service.review(UUID([r for r in service.pending(limit=200) if r["guild_id"] == guild][0]["id"]), status="approved")
    registry = core_tools()
    agent_tools.register_jokes(registry, service)
    agent = AgentService(SimpleNamespace(models={"general": {"name": "m"}}), SimpleNamespace(), SimpleNamespace(), registry=registry)
    assert "Con mèo là CEO" in agent._execute_tool("search_jokes", {}, {"guild_id": guild})
    assert "Con mèo" not in agent._execute_tool("search_jokes", {}, {"guild_id": "another"})
    assert "chỉ đọc" in agent._execute_tool("search_jokes", {}, {})
    assert "chưa có" in agent._execute_tool("search_jokes", {"query": "không khớp"}, {"guild_id": guild})


def test_the_worker_labels_what_is_waiting_and_a_down_service_loses_nothing(factory, guild) -> None:
    service = MessageLabelService(factory)
    heard(factory, guild, "Tôi thích trà")
    heard(factory, guild, "k")

    class OnlyOurs(MessageLabelService):
        def unlabelled(self, limit=20):
            return ours(service, guild)

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=result("fact")))
    with httpx.Client(transport=transport) as client:
        assert run_once(OnlyOurs(factory), "http://decided", client) == 1
    assert ours(service, guild) == []

    heard(factory, guild, "Tin khác")
    def down(request):
        raise httpx.ConnectError("down")
    with httpx.Client(transport=httpx.MockTransport(down)) as client, pytest.raises(httpx.HTTPError):
        run_once(OnlyOurs(factory), "http://decided", client)
    assert len(ours(service, guild)) == 1


def test_the_launcher_starts_the_trial_only_when_it_is_set() -> None:
    launcher = (REPO / "run-local-ai-core.bat").read_text(encoding="utf-8")
    assert '"^DECIDED_URL=."' in launcher and "scripts.decided_worker" in launcher
    assert launcher.index("^DECIDED_URL=.") < launcher.index("uvicorn app.main:app")
