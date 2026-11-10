"""Review2 A-9 at level B: what the bot does with the three final outcomes of a turn.

A turn already answered is not sent again; a failed turn tells the asker; a turn whose
message was deleted before delivery is closed for good instead of being put back in the
queue. The backend is test_discord_progress_message.FakeBackend.
"""
from __future__ import annotations

import discord
import pytest

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
