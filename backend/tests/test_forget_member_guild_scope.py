"""forget_member forgets only in the guild where the member asked (ticket 19).

Member A spoke in two guilds, X and Y: a turn and a channel message in each. Forgetting
A in X leaves Y exactly as it was, and the dry-run names what it leaves there; running
again with --all-guilds takes Y too. Real PostgreSQL; no Qdrant (A has no memories).
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import (
    DiscordChannelMessage,
    DiscordConversationSession,
    DiscordSessionTurn,
)
from scripts.forget_member import forget, main

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


@pytest.fixture
def world(factory):
    tag = uuid4().hex[:8]
    x, y, a_id = f"guild-x-{tag}", f"guild-y-{tag}", f"a-{tag}"
    sessions = {x: uuid4(), y: uuid4()}
    now = datetime.now(UTC)
    with factory.begin() as database:
        for guild, session_id in sessions.items():
            # No Conversation row behind it: _copies then finds nothing to rewrite.
            database.add(DiscordConversationSession(id=session_id, guild_id=guild, channel_id="c1", backend_conversation_id=uuid4()))
            database.flush()
            database.add(DiscordSessionTurn(id=uuid4(), session_id=session_id, discord_message_id=f"t{tag}{guild}", sequence_number=1,
                                            request_text=f"Ún ơi nhắc mình lịch họp ở {guild}", response_text="Đã ghi.",
                                            author_id=a_id, author_display_name="Lan", status="completed"))
            database.add(DiscordChannelMessage(guild_id=guild, channel_id="c1", discord_message_id=f"m{tag}{guild}", author_id=a_id,
                                               author_display_name="Lan", content=f"Mình đi công tác từ thứ hai, nhắn ở {guild}", sent_at=now))
    yield {"x": x, "y": y, "a": a_id, "sessions": sessions}
    with factory.begin() as database:
        database.execute(delete(DiscordChannelMessage).where(DiscordChannelMessage.guild_id.in_([x, y])))
        database.execute(delete(DiscordConversationSession).where(DiscordConversationSession.id.in_(list(sessions.values()))))


def left(factory, world, guild: str) -> tuple[int, int]:
    """(A's turns, A's channel messages) still in `guild`."""
    with factory() as database:
        turns = database.scalar(select(func.count()).select_from(DiscordSessionTurn).where(
            DiscordSessionTurn.session_id == world["sessions"][guild], DiscordSessionTurn.author_id == world["a"]))
        messages = database.scalar(select(func.count()).select_from(DiscordChannelMessage).where(
            DiscordChannelMessage.guild_id == guild, DiscordChannelMessage.author_id == world["a"]))
    return turns, messages


def test_the_dry_run_names_the_guild_it_covers_and_what_it_leaves(factory, world):
    report = forget(world["x"], world["a"], apply=False)

    assert report["scope"]["all_guilds"] is False and report["scope"]["guilds"] == [world["x"]]
    assert report["planned"]["session_turns"] == 1 and report["planned"]["channel_messages"] == 1
    kept = report["scope"]["left_alone"]
    assert list(kept) == [world["y"]] and kept[world["y"]]["session_turns"] == 1 and kept[world["y"]]["channel_messages"] == 1
    assert left(factory, world, world["x"]) == (1, 1) and left(factory, world, world["y"]) == (1, 1)


def test_forgetting_in_x_keeps_y_and_all_guilds_then_takes_y(factory, world):
    report = forget(world["x"], world["a"], apply=True)
    assert not any(report["remaining"].values()), report["remaining"]
    assert left(factory, world, world["x"]) == (0, 0)
    assert left(factory, world, world["y"]) == (1, 1), "A asked in X; Y is not theirs to lose"

    widened = forget(world["x"], world["a"], apply=False, all_guilds=True)
    assert widened["scope"]["guilds"] == [world["y"]] and widened["scope"]["left_alone"] == {}
    assert widened["planned"]["session_turns"] == 1

    report = forget(world["x"], world["a"], apply=True, all_guilds=True)
    assert not any(report["remaining"].values()), report["remaining"]
    assert left(factory, world, world["y"]) == (0, 0)


def test_all_guilds_from_the_start_covers_both(factory, world):
    report = forget(world["x"], world["a"], apply=False, all_guilds=True)
    assert report["scope"]["guilds"] == sorted([world["x"], world["y"]])
    assert report["planned"]["session_turns"] == 2 and report["planned"]["channel_messages"] == 2

    forget(world["x"], world["a"], apply=True, all_guilds=True)
    assert left(factory, world, world["x"]) == (0, 0) and left(factory, world, world["y"]) == (0, 0)


def test_the_command_line_widens_only_when_told(factory, world, capsys):
    assert main(["--guild-id", world["x"], "--author-id", world["a"]]) == 0
    assert json.loads(capsys.readouterr().out)["scope"]["guilds"] == [world["x"]]

    assert main(["--guild-id", world["x"], "--author-id", world["a"], "--all-guilds"]) == 0
    assert json.loads(capsys.readouterr().out)["scope"]["guilds"] == sorted([world["x"], world["y"]])
    assert left(factory, world, world["x"]) == (1, 1), "a dry run, both times"
