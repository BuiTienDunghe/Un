"""Ticket 48: the bot's half of reminders — off by default, delivered to the right channel,
mentioning only the member who asked, and honest about what failed. No Discord, no backend."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import discord
import httpx
import pytest
import yaml

from discord_bot import reminders as sender_module
from discord_bot.api_client import BackendReminder, BackendResponseError, BackendUnavailableError, LocalAgentClient, LocalAgentSettings
from discord_bot.main import DiscordSettings, create_bot
from discord_bot.reminders import ReminderSender, format_reminder, format_reminder_list

HOME, OTHER = "111", "222"
ME, YOU = "900", "901"


def reminder(text: str = "Gọi mẹ", *, guild: str = HOME, channel: str = "55", late: int = 0, creator: str = ME) -> BackendReminder:
    return BackendReminder("00000000-0000-0000-0000-000000000001", "00000000", guild, channel, creator, text, "2026-11-01T03:00:00+00:00", "sending", late)


class FakeApi:
    def __init__(self, due: list[BackendReminder] | None = None) -> None:
        self.due = due or []
        self.claims = 0
        self.sent: list[tuple[str, str | None]] = []
        self.failed: list[tuple[str, str, bool]] = []
        self.ack_fails = 0
        self.cancel_error: Exception | None = None
        self.cancelled: list[tuple[str, str, str]] = []
        self.listed: list[tuple[str, str]] = []

    async def claim_reminders(self):
        self.claims += 1
        return list(self.due)

    async def reminder_sent(self, reminder_id, discord_message_id):
        if self.ack_fails:
            self.ack_fails -= 1
            raise BackendUnavailableError("down")
        self.sent.append((reminder_id, discord_message_id))

    async def reminder_failed(self, reminder_id, error, *, retryable):
        self.failed.append((reminder_id, error, retryable))

    async def cancel_reminder(self, reference, guild_id, requester_id):
        self.cancelled.append((reference, guild_id, requester_id))
        if self.cancel_error:
            raise self.cancel_error
        return reminder()

    async def list_reminders(self, guild_id, author_id):
        self.listed.append((guild_id, author_id))
        return [reminder()]


class FakeChannel:
    def __init__(self, guild_id: str = HOME, fail: Exception | None = None) -> None:
        self.guild = SimpleNamespace(id=int(guild_id))
        self.fail = fail
        self.sent: list[tuple[str, discord.AllowedMentions]] = []

    async def send(self, content, *, allowed_mentions):
        if self.fail:
            raise self.fail
        self.sent.append((content, allowed_mentions))
        return SimpleNamespace(id=777)


class FakeBot:
    def __init__(self, channel: FakeChannel | None = None) -> None:
        self.channel = channel
        self.fetched = 0

    def get_channel(self, channel_id):
        return self.channel

    async def fetch_channel(self, channel_id):
        self.fetched += 1
        raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "unknown channel")


def make_sender(channel: FakeChannel | None, api: FakeApi, allowed=frozenset({HOME})) -> ReminderSender:
    return ReminderSender(FakeBot(channel), api, lambda guild: allowed is None or guild in allowed)


def run(coroutine):
    return asyncio.run(coroutine)


# ---- what the message says and who it can ping ----

def test_the_message_mentions_its_creator_and_nobody_else() -> None:
    message = format_reminder(reminder("Báo @everyone và @here, <@&5> <@123> đi họp"))
    assert message.startswith(f"<@{ME}> ")
    assert "@everyone" not in message and "@here" not in message and "<@&5>" not in message and "<@123>" not in message
    mentions = sender_module.mention_only(ME)
    assert mentions.everyone is False and mentions.roles is False
    assert [user.id for user in mentions.users] == [int(ME)]


def test_a_late_reminder_says_how_late_and_an_on_time_one_does_not() -> None:
    assert "Trễ" not in format_reminder(reminder(late=20))
    late = format_reminder(reminder(late=5 * 3600))
    assert "Trễ 5 giờ" in late and "10:00 01/11" in late


def test_the_list_shows_the_code_to_cancel_with() -> None:
    assert "`00000000`" in format_reminder_list([reminder()])
    assert "chưa có lời nhắc" in format_reminder_list([])


# ---- delivery ----

def test_a_due_reminder_goes_to_its_channel_and_is_marked_sent() -> None:
    channel, api = FakeChannel(), FakeApi([reminder()])
    assert run(make_sender(channel, api).tick()) == 1
    (content, allowed) = channel.sent[0]
    assert content.startswith(f"<@{ME}>") and "Gọi mẹ" in content
    assert allowed.everyone is False and allowed.roles is False and [u.id for u in allowed.users] == [int(ME)]
    assert api.sent == [("00000000-0000-0000-0000-000000000001", "777")] and api.failed == []


def test_a_server_outside_the_allowlist_is_not_sent_to() -> None:
    channel, api = FakeChannel(OTHER), FakeApi([reminder(guild=OTHER)])
    assert run(make_sender(channel, api).tick()) == 0
    assert channel.sent == [] and api.sent == []
    assert api.failed == [("00000000-0000-0000-0000-000000000001", "guild_not_allowed", False)]


def test_a_channel_that_belongs_to_another_server_is_not_sent_to() -> None:
    channel, api = FakeChannel(OTHER), FakeApi([reminder()])
    run(make_sender(channel, api).tick())
    assert channel.sent == [] and api.failed[0][2] is False


def test_a_deleted_channel_is_final_and_a_network_error_is_worth_another_try() -> None:
    api = FakeApi([reminder()])
    run(make_sender(None, api).tick())  # not cached, fetch says NotFound
    assert api.failed[-1][1] == "discord_NotFound" and api.failed[-1][2] is False

    forbidden = FakeChannel(fail=discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "missing access"))
    run(make_sender(forbidden, api).tick())
    assert api.failed[-1][1] == "discord_Forbidden" and api.failed[-1][2] is False

    broken = FakeChannel(fail=ConnectionError("reset"))
    run(make_sender(broken, api).tick())
    assert api.failed[-1][1] == "send_failed_ConnectionError" and api.failed[-1][2] is True
    assert api.sent == []


def test_a_receipt_the_backend_would_not_take_is_offered_on_later_ticks_without_sending_again() -> None:
    channel, api = FakeChannel(), FakeApi([reminder()])
    sender = make_sender(channel, api)
    api.ack_fails = 4  # the three tries of the first tick, then the first offer on the second
    run(sender.tick())
    api.due = []
    assert len(channel.sent) == 1 and api.sent == []
    run(sender.tick())
    assert api.sent == []
    run(sender.tick())
    assert api.sent == [("00000000-0000-0000-0000-000000000001", "777")] and len(channel.sent) == 1
    run(sender.tick())
    assert len(api.sent) == 1  # taken: nothing more is offered


def test_a_reminder_the_backend_hands_out_again_after_its_lease_is_not_sent_twice() -> None:
    channel, api = FakeChannel(), FakeApi([reminder()])
    sender = make_sender(channel, api)
    api.ack_fails = 4  # the whole first tick, and the offer at the start of the second
    run(sender.tick())
    assert len(channel.sent) == 1 and api.sent == []
    run(sender.tick())  # the same reminder comes back from claim
    assert len(channel.sent) == 1 and len(api.sent) == 1


def test_a_receipt_nobody_takes_is_dropped_after_an_hour(monkeypatch) -> None:
    channel, api = FakeChannel(), FakeApi()
    sender = make_sender(channel, api)
    api.due, api.ack_fails = [reminder()], 10_000
    run(sender.tick())
    api.due = []
    clock = [sender_module.monotonic() + sender_module.RECEIPT_KEPT_SECONDS + 1]
    monkeypatch.setattr(sender_module, "monotonic", lambda: clock[0])
    run(sender.tick())
    assert sender._unacknowledged == {}


def test_the_loop_survives_a_backend_that_is_down(monkeypatch) -> None:
    class Down(FakeApi):
        async def claim_reminders(self):
            self.claims += 1
            raise BackendUnavailableError("down")

    api, sleeps = Down(), []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(sender_module.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        run(make_sender(FakeChannel(), api).run_forever())
    assert api.claims == 3


# ---- off by default ----

def test_nothing_runs_and_no_command_exists_unless_switched_on(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "t")
    monkeypatch.delenv("DISCORD_REMINDERS_ENABLED", raising=False)
    assert DiscordSettings.from_env().reminders_enabled is False
    api = FakeApi([reminder()])
    bot = create_bot(api, "system", 0, docs_guild_allowlist=frozenset({HOME}))
    run(bot.on_ready())
    assert bot.reminder_task is None and api.claims == 0
    assert bot.tree.get_command("reminders") is None
    monkeypatch.setenv("DISCORD_REMINDERS_ENABLED", "true")
    assert DiscordSettings.from_env().reminders_enabled is True


def test_switched_on_it_starts_one_sender_however_often_the_bot_reconnects() -> None:
    async def scenario():
        bot = create_bot(FakeApi(), "system", 0, docs_guild_allowlist=frozenset({HOME}), reminders_enabled=True)
        await bot.on_ready()
        first = bot.reminder_task
        await bot.on_ready()
        same = bot.reminder_task is first
        first.cancel()
        return same, bot.tree.get_command("reminders") is not None

    assert run(scenario()) == (True, True)


# ---- the slash commands ----

class Response:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bool]] = []
        self.deferred = False

    async def send_message(self, text, ephemeral=False):
        self.sent.append((text, ephemeral))

    async def defer(self, thinking=False, ephemeral=False):
        self.deferred = True


class Followup:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bool]] = []

    async def send(self, content, ephemeral=False, **_):
        self.sent.append((content, ephemeral))


def interaction(guild_id: str | None, user_id: str = ME) -> SimpleNamespace:
    return SimpleNamespace(
        guild_id=None if guild_id is None else int(guild_id), user=SimpleNamespace(id=int(user_id)), response=Response(), followup=Followup(),
    )


def command(api: FakeApi, name: str, *args, guild: str | None = HOME, user: str = ME, allowlist=frozenset({HOME})):
    bot = create_bot(api, "system", 0, docs_guild_allowlist=allowlist, reminders_enabled=True)
    call = interaction(guild, user)
    run(bot.tree.get_command("reminders").get_command(name).callback(call, *args))
    return call


def test_cancel_sends_who_is_asking_and_shows_the_backends_refusal_privately() -> None:
    api = FakeApi()
    api.cancel_error = BackendResponseError("Chỉ người đặt lời nhắc mới huỷ được.")
    call = command(api, "cancel", " 00000000 ", user=YOU)
    assert api.cancelled == [("00000000", HOME, YOU)]
    assert call.followup.sent == [("Chỉ người đặt lời nhắc mới huỷ được.", True)]
    api.cancel_error = None
    assert "Đã huỷ" in command(api, "cancel", "00000000").followup.sent[0][0]


def test_the_commands_refuse_a_server_outside_the_list_and_a_direct_message_without_calling_the_backend() -> None:
    api = FakeApi()
    for name, args in (("list", ()), ("cancel", ("00000000",))):
        outside = command(api, name, *args, guild=OTHER)
        assert outside.response.sent == [("Lệnh này chưa bật ở server này.", True)]
        direct = command(api, name, *args, guild=None, allowlist=None)
        assert direct.response.sent == [("Lệnh này chỉ dùng trong server.", True)]
    assert api.cancelled == [] and api.listed == []


def test_list_is_private_to_the_asker() -> None:
    api = FakeApi()
    call = command(api, "list")
    assert api.listed == [(HOME, ME)] and call.followup.sent[0][1] is True


# ---- the HTTP client ----

def client_for(handler) -> LocalAgentClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend")
    return LocalAgentClient(LocalAgentSettings("http://backend", api_key="k"), http)


ROW = {"id": "i", "short_id": "s", "guild_id": HOME, "channel_id": "55", "creator_id": ME, "text": "Gọi mẹ", "due_at": "2026-11-01T03:00:00+00:00", "status": "sending"}


def test_claim_parses_rows_and_drops_a_malformed_one() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["key"] = request.url.path, request.headers.get("X-API-Key")
        return httpx.Response(200, json=[{**ROW, "late_seconds": 42}, {"id": "broken"}, "junk"])

    (claimed,) = run(client_for(handler).claim_reminders())
    assert seen == {"path": "/api/discord/reminders/claim", "key": "k"}
    assert claimed.late_seconds == 42 and claimed.channel_id == "55"


def test_cancel_and_failure_reports_carry_the_right_fields() -> None:
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append((request.url.path, request.content.decode()))
        return httpx.Response(200, json=ROW if request.url.path.endswith("/cancel") else {"status": "ok"})

    client = client_for(handler)
    run(client.cancel_reminder("abcdef", HOME, YOU))
    run(client.reminder_failed("i", "boom", retryable=True))
    assert '"requester_id":"901"' in bodies[0][1].replace(" ", "") and bodies[0][0] == "/api/discord/reminders/abcdef/cancel"
    assert '"retryable":true' in bodies[1][1].replace(" ", "")


def test_a_refusal_from_the_backend_reaches_the_user_as_its_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error_code": "REMINDER_NOT_YOURS", "message": "Chỉ người đặt lời nhắc mới huỷ được."})

    with pytest.raises(BackendResponseError, match="Chỉ người đặt"):
        run(client_for(handler).cancel_reminder("abcdef", HOME, YOU))


def test_the_compose_bot_receives_the_switch() -> None:
    compose = yaml.safe_load((Path(__file__).parents[1] / "docker-compose.yml").read_text(encoding="utf-8"))
    environment = compose["services"]["discord-bot"]["environment"]
    assert "DISCORD_REMINDERS_ENABLED" in environment
    example = (Path(__file__).parents[1] / ".env.example").read_text(encoding="utf-8")
    assert "DISCORD_REMINDERS_ENABLED=false" in example
