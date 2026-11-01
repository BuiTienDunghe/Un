"""Ticket 49: a voice message replying to the bot is heard and enters the turn as the question — off by
default, only in listed guilds, and a recording that cannot be heard gets a polite reply instead of a
turn. No Discord, no backend, no speech model."""
from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

import discord_bot.main as bot_module
from discord_bot.api_client import BackendUnavailableError, LocalAgentClient, LocalAgentSettings
from discord_bot.main import (
    MAX_TRANSCRIPT_CHARS,
    MAX_VOICE_BYTES,
    MAX_VOICE_SECONDS,
    VOICE_EMPTY,
    VOICE_FAILED,
    VOICE_NOT_ENABLED,
    VOICE_TOO_LONG,
    DiscordSettings,
    create_bot,
    hear_voice,
)

HOME, OTHER = 111, 222
ALLOWED = frozenset({str(HOME)})
RECORDING = b"OggS-not-really-audio"


class FakeApi:
    def __init__(self, heard: str | Exception = "mai trời mưa không") -> None:
        self.heard = heard
        self.sent: list[str] = []

    async def transcribe_voice(self, audio_base64: str) -> str:
        self.sent.append(audio_base64)
        if isinstance(self.heard, BaseException):
            raise self.heard
        return self.heard


def voice(size: int = len(RECORDING), seconds: float | None = 4.0, read_error: Exception | None = None, is_voice: bool = True):
    async def read() -> bytes:
        if read_error:
            raise read_error
        return RECORDING

    return SimpleNamespace(is_voice_message=lambda: is_voice, size=size, duration=seconds, read=read, content_type="audio/ogg")


def message(attachments, guild: int | None = HOME, content: str = ""):
    replies: list[str] = []

    class Typing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    async def reply(text, **_kwargs):
        replies.append(text)

    channel = SimpleNamespace(id=5, typing=Typing)
    return SimpleNamespace(
        id=1, content=content, attachments=attachments, reply=reply, replies=replies, channel=channel,
        guild=None if guild is None else SimpleNamespace(id=guild), author=SimpleNamespace(id=9, bot=False),
    )


def hear(api, attachments, guild=HOME, allowlist=ALLOWED):
    return asyncio.run(hear_voice(api, message(attachments, guild), allowlist))


# ---- hear_voice ----

def test_the_words_come_back_and_the_recording_went_out_as_base64() -> None:
    api = FakeApi()
    assert hear(api, [voice()]) == ("mai trời mưa không", None)
    assert base64.b64decode(api.sent[0]) == RECORDING


def test_a_message_without_a_voice_recording_is_not_touched() -> None:
    api = FakeApi()
    assert hear(api, []) == (None, None)
    assert hear(api, [voice(is_voice=False)]) == (None, None)  # An uploaded audio file, not a voice message.
    assert api.sent == []


@pytest.mark.parametrize(
    ("guild", "allowlist"),
    [(HOME, frozenset()), (OTHER, ALLOWED), (None, ALLOWED), (None, None)],
    ids=["off by default", "another guild", "a DM", "a DM with every guild allowed"],
)
def test_outside_the_list_nothing_leaves(guild, allowlist) -> None:
    api = FakeApi()
    assert hear(api, [voice()], guild, allowlist) == (None, VOICE_NOT_ENABLED)
    assert api.sent == []


def test_every_guild_when_the_list_says_so() -> None:
    assert hear(FakeApi(), [voice()], OTHER, None)[0] == "mai trời mưa không"


@pytest.mark.parametrize("recording", [voice(size=MAX_VOICE_BYTES + 1), voice(seconds=MAX_VOICE_SECONDS + 1)], ids=["bytes", "seconds"])
def test_too_large_or_too_long_is_refused_before_reading(recording) -> None:
    api = FakeApi()
    assert hear(api, [recording]) == (None, VOICE_TOO_LONG)
    assert api.sent == []


def test_the_limits_themselves_are_allowed() -> None:
    assert hear(FakeApi(), [voice(size=MAX_VOICE_BYTES, seconds=MAX_VOICE_SECONDS)])[1] is None


@pytest.mark.parametrize(
    "failure",
    [BackendUnavailableError("down"), TimeoutError(), RuntimeError("boom"), ValueError("x")],
    ids=lambda failure: type(failure).__name__,
)
def test_a_service_that_fails_gets_a_polite_reply_and_no_error(failure) -> None:
    assert hear(FakeApi(failure), [voice()]) == (None, VOICE_FAILED)


def test_a_recording_that_cannot_be_fetched_gets_a_polite_reply() -> None:
    api = FakeApi()
    assert hear(api, [voice(read_error=OSError("gone"))]) == (None, VOICE_FAILED)
    assert api.sent == []


@pytest.mark.parametrize("heard", ["", "   \n"])
def test_silence_gets_its_own_reply(heard) -> None:
    assert hear(FakeApi(heard), [voice()]) == (None, VOICE_EMPTY)


def test_a_very_long_text_is_cut() -> None:
    heard, _ = hear(FakeApi("a" * (MAX_TRANSCRIPT_CHARS + 500)), [voice()])
    assert len(heard) == MAX_TRANSCRIPT_CHARS


def test_stopping_the_bot_is_not_swallowed() -> None:
    with pytest.raises(asyncio.CancelledError):
        hear(FakeApi(asyncio.CancelledError()), [voice()])


def test_the_failure_is_logged_by_type_only(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        hear(FakeApi(RuntimeError("what the person said")), [voice()])
    assert "RuntimeError" in caplog.text and "what the person said" not in caplog.text


# ---- through on_message ----

def run_on_message(api, incoming, *, allowlist=ALLOWED, mentioned=True, monkeypatch):
    """Drives the bot's own on_message and returns the questions that reached a turn."""
    asked: list[str] = []

    async def answer_mention(_gateway, _message, question, _progress) -> None:
        asked.append(question)

    monkeypatch.setattr(bot_module, "answer_mention", answer_mention)
    monkeypatch.setattr(bot_module, "ProgressMessage", lambda _message: None)
    bot = create_bot(api, "system", 0, voice_guild_allowlist=allowlist)
    bot._connection.user = SimpleNamespace(id=42, mentioned_in=lambda _message: mentioned)
    asyncio.run(bot.on_message(incoming))
    return asked


def test_the_words_enter_the_turn_like_a_typed_message(monkeypatch) -> None:
    api, incoming = FakeApi(), message([voice()])
    assert run_on_message(api, incoming, monkeypatch=monkeypatch) == ["mai trời mưa không"]
    assert incoming.replies == []


def test_off_by_default_the_voice_message_gets_a_reply_and_no_turn(monkeypatch) -> None:
    api, incoming = FakeApi(), message([voice()])
    assert run_on_message(api, incoming, allowlist=frozenset(), monkeypatch=monkeypatch) == []
    assert incoming.replies == [VOICE_NOT_ENABLED] and api.sent == []


@pytest.mark.parametrize(
    ("api", "recording", "reply"),
    [
        (FakeApi(RuntimeError("boom")), voice(), VOICE_FAILED),
        (FakeApi(), voice(size=MAX_VOICE_BYTES + 1), VOICE_TOO_LONG),
        (FakeApi(""), voice(), VOICE_EMPTY),
    ],
    ids=["failure", "too large", "silence"],
)
def test_a_recording_that_cannot_be_heard_costs_no_turn(api, recording, reply, monkeypatch) -> None:
    incoming = message([recording])
    assert run_on_message(api, incoming, monkeypatch=monkeypatch) == []
    assert incoming.replies == [reply]


def test_a_voice_message_not_addressed_to_the_bot_is_not_heard(monkeypatch) -> None:
    api, incoming = FakeApi(), message([voice()])
    assert run_on_message(api, incoming, mentioned=False, monkeypatch=monkeypatch) == []
    assert api.sent == [] and incoming.replies == []


def test_an_uploaded_audio_file_is_left_alone(monkeypatch) -> None:
    api, incoming = FakeApi(), message([voice(is_voice=False)])
    assert run_on_message(api, incoming, monkeypatch=monkeypatch) == []
    assert api.sent == [] and incoming.replies == ["Hãy gắn kèm câu hỏi sau @Ún."]


# ---- settings, client, wiring ----

def test_the_switch_is_off_unless_the_environment_lists_guilds(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "t")
    monkeypatch.delenv("DISCORD_VOICE_GUILD_ALLOWLIST", raising=False)
    assert DiscordSettings.from_env().voice_guild_allowlist == frozenset()
    monkeypatch.setenv("DISCORD_VOICE_GUILD_ALLOWLIST", "111, 222")
    assert DiscordSettings.from_env().voice_guild_allowlist == frozenset({"111", "222"})
    monkeypatch.setenv("DISCORD_VOICE_GUILD_ALLOWLIST", "*")
    assert DiscordSettings.from_env().voice_guild_allowlist is None


def test_the_client_posts_the_recording_and_returns_trimmed_words() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["body"], seen["key"] = request.url.path, request.read(), request.headers.get("X-API-Key")
        return httpx.Response(200, json={"text": "  xin chào  "})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend")
    client = LocalAgentClient(LocalAgentSettings("http://backend", api_key="k"), http)
    assert asyncio.run(client.transcribe_voice("QUJD")) == "xin chào"
    assert seen["path"] == "/voice/transcribe" and b"QUJD" in seen["body"] and seen["key"] == "k"


def test_the_compose_bot_receives_the_list_and_the_example_leaves_it_off() -> None:
    root = Path(__file__).parents[1]
    environment = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["discord-bot"]["environment"]
    assert "DISCORD_VOICE_GUILD_ALLOWLIST" in environment
    example = (root / ".env.example").read_text(encoding="utf-8")
    assert "\nDISCORD_VOICE_GUILD_ALLOWLIST=\n" in example.replace("\r\n", "\n")
    assert "\nVOICE_URL=\n" in example.replace("\r\n", "\n")
