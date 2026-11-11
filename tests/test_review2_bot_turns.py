"""Review2 A-9 at level B: what the bot does with the three final outcomes of a turn.

A turn already answered is not sent again; a failed turn tells the asker; a turn whose
message was deleted before delivery is closed for good instead of being put back in the
queue. The backend is test_discord_progress_message.FakeBackend.

A-10: a turn the bot gives up on while holding no lease (its wait ran out, the backend failed,
the turn was taken from it) is cancelled once; a timed-out turn is left to its lease.
"""
from __future__ import annotations

import asyncio

import discord
import pytest

from discord_bot.api_client import BackendResponseError, BackendTimeoutError, BackendUnavailableError
from discord_bot.main import DiscordConversationGateway, answer_mention
from test_discord_progress_message import Discord, FakeBackend, FakeSource, http_error, quick, run, running, state


@pytest.mark.parametrize("outcome", ["completed", "failed", "source_deleted"])
def test_a9_the_bot_ends_a_turn_once_whatever_its_final_outcome(outcome):
    discord_side = Discord()
    source = FakeSource(discord_side)
    if outcome == "completed":
        backend = FakeBackend([state("completed")])
    elif outcome == "failed":
        backend = FakeBackend([state("failed")])
    else:
        backend = FakeBackend([running("câu trả lời")])
        source.reply_errors.append(http_error(discord.NotFound, 404))

    run(backend, source, quick(source, first_post_seconds=60.0))

    assert [call[0] for call in backend.calls if call[0] == "execute"] == ["execute"]
    assert backend.completions() == []
    if outcome == "completed":
        assert discord_side.writes == []  # an earlier delivery already answered it
    elif outcome == "failed":
        assert [kind for kind, _, content, _ in discord_side.writes if content] == ["reply"]  # the asker is told
    else:
        assert source.reply_errors == [], "delivery was never tried"
        assert [(call[0], call[4]) for call in backend.calls if call[0] == "fail"] == [("fail", False)]


class GivingUpBackend(FakeBackend):
    async def cancel_discord_turn(self, turn_id, error):
        self.calls.append(("cancel", turn_id))
        return "cancelled"


@pytest.mark.parametrize("exit_path", ["wait_ran_out", "backend_5xx", "turn_taken_409", "timeout"])
def test_a10_a_turn_the_bot_gives_up_on_without_a_lease_is_cancelled_once(exit_path):
    # Review2 A: the bot holds no lease token on these exits, so /fail cannot end the turn;
    # it asks the backend to cancel it (once, never retrying the turn). A timeout leaves the
    # turn running under the backend's lease: reported, never retried and never cancelled.
    discord_side = Discord()
    source = FakeSource(discord_side)
    outcome = {
        "wait_ran_out": state("queued"),
        "backend_5xx": BackendUnavailableError("Backend is unavailable. Please try again later."),
        "turn_taken_409": BackendResponseError("Turn lease is no longer owned by this execution."),
        "timeout": BackendTimeoutError("Discord turn execution timed out. Please try again later."),
    }[exit_path]
    backend = GivingUpBackend([outcome])
    gateway = DiscordConversationGateway(backend, "prompt", 0, True, poll_budget_seconds=0)

    asyncio.run(answer_mention(gateway, source, "câu hỏi", quick(source, first_post_seconds=60.0)))

    assert [call[0] for call in backend.calls if call[0] == "execute"] == ["execute"]
    cancels = [call for call in backend.calls if call[0] == "cancel"]
    assert cancels == ([] if exit_path == "timeout" else [("cancel", "turn")])
    assert backend.completions() == [] and [call for call in backend.calls if call[0] == "fail"] == []
    assert [kind for kind, _, content, _ in discord_side.writes if content] == ["reply"]  # the asker is told


def test_a10_a_failed_cancel_is_only_logged():
    # Best effort: a backend that cannot cancel (or a client without the call) changes nothing
    # the asker sees.
    discord_side = Discord()
    source = FakeSource(discord_side)
    backend = FakeBackend([BackendUnavailableError("Backend is unavailable. Please try again later.")])
    gateway = DiscordConversationGateway(backend, "prompt", 0, True, poll_budget_seconds=0)

    asyncio.run(answer_mention(gateway, source, "câu hỏi", quick(source, first_post_seconds=60.0)))

    assert [kind for kind, _, content, _ in discord_side.writes if content] == ["reply"]
