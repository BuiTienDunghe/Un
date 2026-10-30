"""Ticket 30: /docs reads the owner's whole document store, so it obeys the same guild
allowlist as the @mention tools; a guild outside it, or a DM, reaches nothing."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from discord_bot.api_client import BackendDocument, BackendRagAnswer
from discord_bot.main import (
    DiscordSettings,
    create_bot,
    docs_allowed,
    parse_docs_guild_allowlist,
)

HOME = "111"
OTHER = "222"


class FakeBackend:
    def __init__(self) -> None:
        self.rag_questions: list[str] = []
        self.document_lists = 0

    async def rag_ask(self, question, document_ids=None, conversation_id=None) -> BackendRagAnswer:
        self.rag_questions.append(question)
        return BackendRagAnswer(answer="Tiền thuê là 7 triệu.", conversation_id="conv", sources=())

    async def list_documents(self) -> list[BackendDocument]:
        self.document_lists += 1
        return [BackendDocument(document_id="doc_1", filename="hop-dong.pdf", status="indexed")]


class FakeResponse:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bool]] = []
        self.deferred = False

    async def send_message(self, text: str, ephemeral: bool = False) -> None:
        self.sent.append((text, ephemeral))

    async def defer(self, thinking: bool = False, ephemeral: bool = False) -> None:
        self.deferred = True


class FakeFollowup:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content: str, **_kwargs):
        self.sent.append(content)
        return SimpleNamespace(id=len(self.sent))


def interaction_in(guild_id: str | None) -> SimpleNamespace:
    guild = None if guild_id is None else SimpleNamespace(id=int(guild_id), name="server")
    return SimpleNamespace(
        id=1,
        guild=guild,
        guild_id=None if guild_id is None else int(guild_id),
        channel=SimpleNamespace(id=5),
        user=SimpleNamespace(id=9, display_name="Minh", name="minh"),
        response=FakeResponse(),
        followup=FakeFollowup(),
    )


def run_docs(allowlist, guild_id) -> tuple[SimpleNamespace, FakeBackend]:
    backend = FakeBackend()
    bot = create_bot(backend, "system", 0, docs_guild_allowlist=allowlist)
    interaction = interaction_in(guild_id)
    asyncio.run(bot.tree.get_command("docs").callback(interaction, "Tiền thuê bao nhiêu?"))
    return interaction, backend


def run_autocomplete(allowlist, guild_id) -> tuple[list, FakeBackend]:
    backend = FakeBackend()
    bot = create_bot(backend, "system", 0, docs_guild_allowlist=allowlist)
    autocomplete = bot.tree.get_command("docs")._params["document"].autocomplete
    return asyncio.run(autocomplete(interaction_in(guild_id), "")), backend


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", frozenset()),
        ("   ", frozenset()),
        (",,", frozenset()),
        ("111", frozenset({"111"})),
        (" 111 , 222 ", frozenset({"111", "222"})),
        ("*", None),
        (" * ", None),
    ],
)
def test_the_list_reads_like_the_backend_reads_it(raw, expected) -> None:
    assert parse_docs_guild_allowlist(raw) == expected


@pytest.mark.parametrize(
    ("guild_id", "allowlist", "expected"),
    [
        (HOME, frozenset({HOME}), True),
        (int(HOME), frozenset({HOME}), True),
        (OTHER, frozenset({HOME}), False),
        (HOME, frozenset(), False),
        (HOME, None, True),
        (None, frozenset({HOME}), False),
        # "*" means every guild; a DM has no guild to check.
        (None, None, False),
    ],
)
def test_who_may_use_docs(guild_id, allowlist, expected) -> None:
    assert docs_allowed(guild_id, allowlist) is expected


def test_settings_read_the_same_variable_as_the_mention_tools(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DISCORD_AGENT_TOOLS_GUILD_ALLOWLIST", f"{HOME}, {OTHER}")
    assert DiscordSettings.from_env().docs_guild_allowlist == frozenset({HOME, OTHER})


def test_settings_fail_closed_when_the_variable_is_missing(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.delenv("DISCORD_AGENT_TOOLS_GUILD_ALLOWLIST", raising=False)
    assert DiscordSettings.from_env().docs_guild_allowlist == frozenset()


def test_create_bot_fails_closed_when_no_list_is_given() -> None:
    backend = FakeBackend()
    bot = create_bot(backend, "system", 0)
    interaction = interaction_in(HOME)
    asyncio.run(bot.tree.get_command("docs").callback(interaction, "Hỏi?"))
    assert backend.rag_questions == []


def test_docs_answers_publicly_in_an_allowed_guild() -> None:
    interaction, backend = run_docs(frozenset({HOME}), HOME)
    assert backend.rag_questions == ["Tiền thuê bao nhiêu?"]
    assert interaction.response.deferred
    assert interaction.followup.sent == ["Tiền thuê là 7 triệu."]


def test_docs_refuses_another_guild_before_reaching_the_documents() -> None:
    interaction, backend = run_docs(frozenset({HOME}), OTHER)
    assert backend.rag_questions == []
    # Discord fixes a reply's visibility at defer, so a private refusal cannot follow one.
    assert not interaction.response.deferred
    assert interaction.response.sent == [("Lệnh này chưa bật ở server này.", True)]
    assert interaction.followup.sent == []


def test_docs_refuses_a_direct_message_even_when_every_guild_is_allowed() -> None:
    interaction, backend = run_docs(None, None)
    assert backend.rag_questions == []
    assert not interaction.response.deferred
    assert interaction.response.sent == [("Lệnh này chỉ dùng trong server.", True)]


def test_a_refused_question_too_long_for_the_limit_still_gets_the_refusal() -> None:
    backend = FakeBackend()
    bot = create_bot(backend, "system", 0, docs_guild_allowlist=frozenset({HOME}))
    interaction = interaction_in(OTHER)
    asyncio.run(bot.tree.get_command("docs").callback(interaction, "x" * 10_001))
    assert interaction.response.sent == [("Lệnh này chưa bật ở server này.", True)]


def test_autocomplete_lists_filenames_in_an_allowed_guild() -> None:
    choices, _ = run_autocomplete(frozenset({HOME}), HOME)
    assert [choice.name for choice in choices] == ["hop-dong.pdf"]


@pytest.mark.parametrize(
    ("allowlist", "guild_id"),
    [(frozenset({HOME}), OTHER), (frozenset(), HOME), (None, None)],
)
def test_autocomplete_shows_no_filename_where_docs_is_refused(allowlist, guild_id) -> None:
    choices, backend = run_autocomplete(allowlist, guild_id)
    assert choices == []
    assert backend.document_lists == 0


@pytest.mark.parametrize(
    ("allowlist", "expected"),
    [
        (frozenset(), "/docs is off in every server"),
        (frozenset({HOME, OTHER}), "/docs is on in 2 server(s)"),
        (None, "/docs is on in every server"),
    ],
)
def test_startup_log_says_how_many_guilds_may_use_docs(allowlist, expected, caplog) -> None:
    bot = create_bot(FakeBackend(), "system", 0, docs_guild_allowlist=allowlist)
    with caplog.at_level(logging.INFO, logger="discord_bot.main"):
        asyncio.run(bot.on_ready())
    assert expected in caplog.text


def test_the_compose_bot_receives_the_list() -> None:
    # run-discord-bot.bat runs this service: without the key, /docs is off in every server.
    compose = yaml.safe_load((Path(__file__).parents[1] / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "DISCORD_AGENT_TOOLS_GUILD_ALLOWLIST" in compose["services"]["discord-bot"]["environment"]
