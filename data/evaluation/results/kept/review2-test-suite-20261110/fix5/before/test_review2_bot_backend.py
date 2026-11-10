"""Review2 code A at level T: the real bot (gateway + backend client + answer_mention) on the
real app over httpx.ASGITransport, with a fake Discord.

A turn the bot abandons (Discord refused the answer, the backend failed once, the bot ran out
of patience, the bot died) must not block the channel: the next ordinary message in it is
answered within the bot's waiting time. Any valid fix flips these cases, whether it lives in
the bot or in the backend; that is why the lease is short (3 s), the bot waits at least four
leases, and the abandoned turn is aged one hour (after the backend's own recovery ran) before
message 2 is sent (opus-signoff.md, A-5..A-8).
"""
from __future__ import annotations

import asyncio

import pytest

from review2_support import (BotOnApp, KnownBug, age_open_turns, known_bug, r2, turn_by_message,  # noqa: F401
                             v2client)

LEASE_SECONDS = 3
BUDGET_SECONDS = 15.0  # at least four leases


@pytest.fixture
def bot(r2, monkeypatch):  # noqa: F811
    monkeypatch.setattr(r2.turns, "lease_seconds", LEASE_SECONDS)
    return BotOnApp(r2.client, r2.guild, budget=BUDGET_SECONDS)


def test_a4_a_plain_message_goes_through_the_bot_and_is_answered(r2, bot):  # noqa: F811
    # Step 0 of the plan: proves the bridge. One ordinary message, no fault anywhere.
    r2.model.answers.append("Đáp án sentinel-a4-ok.")
    source = bot.message("Xin chào Ún.")

    async def scenario():
        api = bot.api()
        try:
            return await bot.ask(api, source)
        finally:
            await bot.close(api)

    escaped = asyncio.run(scenario())
    assert escaped is None, repr(escaped)
    assert bot.server_errors == []
    assert "Đáp án sentinel-a4-ok." in bot.shown(source)
    assert turn_by_message(r2.client, source.id).status == "completed"


ANSWER_TWO = "Đáp án cho tin hai sentinel-a-two."
ORPHAN = "review2 A: a turn the bot abandoned blocks the channel; the next message waits until the bot gives up"


async def second_message_answered(r2, bot, api) -> bool:  # noqa: F811
    """Message 2, an ordinary question in the same channel, with the bot's full waiting time.
    Nothing may escape the handler (BotOnApp.ask re-raises it): today message 2 runs out of
    waiting time, and answer_mention reports that and returns normally."""
    r2.model.rules.append(("tin thứ hai", ANSWER_TWO))
    second = bot.message("Đây là tin thứ hai, bình thường.")
    await bot.ask(api, second)
    assert turn_by_message(r2.client, second.id) is not None, "message 2 never reached the backend"
    return ANSWER_TWO in bot.shown(second)


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=ORPHAN + " (Discord refused the answer to message 1)")
def test_a5_after_discord_refuses_an_answer_the_next_message_is_answered(r2, bot):  # noqa: F811
    import discord
    r2.model.rules.append(("tin thứ nhất", "Đáp án cho tin một."))
    first = bot.message("Đây là tin thứ nhất.")
    first.reply_errors.append(bot.fakes.http_error(discord.HTTPException, 500))

    async def scenario():
        api = bot.api()
        try:
            # Discord's refusal may escape the handler (today it is reported, then re-raised);
            # any other escape fails the case.
            await bot.ask(api, first, allowed=(discord.HTTPException,))
            assert first.reply_errors == [], "Discord was never asked to deliver the answer to message 1"
            assert turn_by_message(r2.client, first.id) is not None
            age_open_turns(r2.client, r2.guild)
            return await second_message_answered(r2, bot, api)
        finally:
            await bot.close(api)

    answered = asyncio.run(scenario())
    assert bot.server_errors == []
    known_bug(answered, "message 2 was not answered after Discord refused the answer to message 1")


@pytest.mark.parametrize("fault", ["once", "forever"])
@pytest.mark.xfail(strict=True, raises=KnownBug, reason=ORPHAN + " (the backend failed with 5xx on message 1)")
def test_a6_after_the_backend_fails_on_a_message_the_next_message_is_answered(r2, bot, monkeypatch, fault):  # noqa: F811
    # The fault is tied to message 1's turn only: message 2 must stay answerable by any fix.
    import app.discord.turn_service as turn_service
    original = turn_service.build_discord_speaker_context
    fired = []

    def faulty(previous_turns, current_turn, **kwargs):
        if "tin thứ nhất" in current_turn.request_text and (fault == "forever" or not fired):
            fired.append(current_turn.request_text)
            raise RuntimeError("review2: injected fault while preparing the turn")
        return original(previous_turns, current_turn, **kwargs)

    monkeypatch.setattr(turn_service, "build_discord_speaker_context", faulty)
    r2.model.rules.append(("tin thứ nhất", "Đáp án cho tin một."))
    first = bot.message("Đây là tin thứ nhất.")

    async def scenario():
        api = bot.api()
        try:
            await bot.ask(api, first)
            assert fired, "the injected fault never fired"
            assert turn_by_message(r2.client, first.id) is not None
            age_open_turns(r2.client, r2.guild)
            return await second_message_answered(r2, bot, api)
        finally:
            await bot.close(api)

    answered = asyncio.run(scenario())
    assert all("review2: injected fault" in str(error) for error in bot.server_errors), bot.server_errors
    known_bug(answered, f"message 2 was not answered after the backend failed ({fault}) on message 1")


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=ORPHAN + " (the bot stopped waiting while message 1 was queued)")
def test_a7_after_the_bot_stops_waiting_on_a_queued_turn_the_next_message_is_answered(r2, bot):  # noqa: F811
    r2.model.failures = 1  # message 1's first model call fails; the turn goes back to the queue
    r2.model.rules.append(("tin thứ nhất", "Đáp án cho tin một."))
    first = bot.message("Đây là tin thứ nhất.")

    async def scenario():
        api = bot.api()
        try:
            await bot.ask(api, first, budget=0.0)  # the bot's waiting time runs out after one call
            assert r2.model.failures == 0, "message 1 never reached the model"
            row = turn_by_message(r2.client, first.id)
            assert row is not None and row.status == "queued", row
            age_open_turns(r2.client, r2.guild)
            return await second_message_answered(r2, bot, api)
        finally:
            await bot.close(api)

    answered = asyncio.run(scenario())
    assert bot.server_errors == []
    known_bug(answered, "message 2 was not answered after the bot stopped waiting on message 1")


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=ORPHAN + " (the bot died mid-turn and was started again)")
def test_a8_after_the_bot_dies_mid_turn_and_restarts_the_next_message_is_answered(r2, bot):  # noqa: F811
    # "Restart" is create_bot + setup_hook + on_ready, the startup a real process runs (the
    # Discord command sync is the only step stubbed). Message 2 then goes through
    # answer_mention with a gateway built exactly as create_bot builds one; on_message itself
    # needs a logged-in Discord user, which this harness does not have.
    from discord_bot.main import create_bot
    r2.model.rules.append(("tin thứ nhất", "Đáp án cho tin một."))
    first = bot.message("Đây là tin thứ nhất.")

    async def scenario():
        dying = bot.api()
        prepared = await bot.gateway(dying).prepare(
            first.question, first.guild, first.channel, int(first.author.id), first.author.display_name, str(first.id))
        await bot.close(dying)  # the process dies: the answer is never delivered or reported
        assert prepared is not None and prepared.answer == "Đáp án cho tin một.", prepared
        assert turn_by_message(r2.client, first.id).status == "running"
        age_open_turns(r2.client, r2.guild)

        api = bot.api()
        restarted = create_bot(api, "Bạn là Ún.", 0, True)

        async def no_command_sync(*args, **kwargs):
            return []

        restarted.tree.sync = no_command_sync
        try:
            await restarted.setup_hook()
            await restarted.on_ready()
            return await second_message_answered(r2, bot, api)
        finally:
            await restarted.close()
            await bot.close(api)

    answered = asyncio.run(scenario())
    assert bot.server_errors == []
    known_bug(answered, "message 2 was not answered after the bot died mid-turn and started again")
