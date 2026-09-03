"""Tier 3 (memory_design.md §7): batching, the trusted-identity binding, the
failure lanes, and the read path — all against a FAKE condenser, so the suite
never calls a cloud provider.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import (
    DiscordChannelMessage,
    DiscordChannelPolicy,
    DiscordCondensationBatch,
    DiscordCondensationProposition,
)
from app.services.discord_condensation_service import DiscordCondensationService
from app.services.discord_history_service import DiscordHistoryService

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")

_DISCORD_EPOCH_MS = 1_420_070_400_000
BASE = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)


def _snowflake(at: datetime, sequence: int) -> str:
    return str(((int(at.timestamp() * 1000) - _DISCORD_EPOCH_MS) << 22) + sequence)


class FakeCondenser:
    """Scripted stand-in for GeminiClient.chat."""

    def __init__(self, answer: str = "[]", error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[dict] = []

    def chat(self, model, messages, temperature=None, max_tokens=None, top_p=None):
        self.calls.append({"model": model, "messages": messages})
        if self.error is not None:
            raise self.error
        return self.answer


@pytest.fixture
def world():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    prefix = f"cond-{uuid4().hex}"
    history = DiscordHistoryService(factory)
    yield factory, prefix, history
    with factory.begin() as database:
        batch_ids = list(
            database.scalars(
                select(DiscordCondensationBatch.id).where(
                    DiscordCondensationBatch.guild_id.like(f"{prefix}%")
                )
            )
        )
        if batch_ids:
            database.execute(
                delete(DiscordCondensationProposition).where(
                    DiscordCondensationProposition.batch_id.in_(batch_ids)
                )
            )
            database.execute(
                delete(DiscordCondensationBatch).where(
                    DiscordCondensationBatch.id.in_(batch_ids)
                )
            )
        database.execute(
            delete(DiscordChannelMessage).where(
                DiscordChannelMessage.guild_id.like(f"{prefix}%")
            )
        )
        database.execute(
            delete(DiscordChannelPolicy).where(
                DiscordChannelPolicy.guild_id.like(f"{prefix}%")
            )
        )


def _seed(history, prefix, count, *, guild="g1", channel="chan-1", start=0,
          gap_minutes=1, author="u1", content="tin so"):
    ids = []
    for index in range(count):
        sequence = start + index
        at = BASE + timedelta(minutes=gap_minutes * sequence)
        message_id = _snowflake(at, sequence)
        assert history.record_message(
            guild_id=f"{prefix}-{guild}",
            channel_id=channel,
            thread_id=None,
            discord_message_id=message_id,
            author_id=author,
            author_display_name=f"User {author}",
            is_bot=False,
            content=f"{content} {sequence}",
        )
        ids.append(message_id)
    return ids


def _service(factory, condenser=None, **kwargs):
    return DiscordCondensationService(
        factory,
        condenser,
        model="fake-condenser",
        worker_id="test-worker",
        **kwargs,
    )


def test_below_the_floor_nothing_is_planned(world):
    factory, prefix, history = world
    _seed(history, prefix, 5)
    service = _service(factory, FakeCondenser())
    assert service.ready_channels() == []
    assert service.plan_batch(f"{prefix}-g1", "chan-1").status == "skipped"


def test_batch_prefers_cutting_at_a_silence_gap(world):
    factory, prefix, history = world
    # 24 messages one minute apart, then a 30-minute silence, then 6 more.
    _seed(history, prefix, 24, start=0, gap_minutes=1)
    for index in range(6):
        at = BASE + timedelta(minutes=24 + 30 + index)
        history.record_message(
            guild_id=f"{prefix}-g1", channel_id="chan-1", thread_id=None,
            discord_message_id=_snowflake(at, 100 + index),
            author_id="u2", author_display_name="User u2",
            is_bot=False, content=f"sau khoang lang {index}",
        )
    service = _service(factory, FakeCondenser())
    outcome = service.plan_batch(f"{prefix}-g1", "chan-1")
    assert outcome.status == "planned"
    with factory() as database:
        batch = database.get(DiscordCondensationBatch, outcome.batch_id)
        # The span stops at the gap, not at an arbitrary count.
        assert batch.message_count == 24
        remaining = database.scalar(
            select(DiscordChannelMessage)
            .where(
                DiscordChannelMessage.guild_id == f"{prefix}-g1",
                DiscordChannelMessage.condensation_batch_id.is_(None),
            )
            .limit(1)
        )
        assert remaining is not None


def test_identity_comes_from_our_rows_not_from_the_model(world):
    factory, prefix, history = world
    _seed(history, prefix, 20, author="real-author")
    condenser = FakeCondenser(
        answer=(
            '```json\n[{"content": "Người dùng chốt dùng Postgres", '
            '"source": [1, 2], "speaker_id": "ATTACKER", '
            '"source_message_ids": ["999"]},'
            '{"content": "bịa từ dòng không tồn tại", "source": [999]}]\n```'
        )
    )
    service = _service(factory, condenser)
    planned = service.plan_batch(f"{prefix}-g1", "chan-1")
    outcome = service.run_batch(planned.batch_id)

    assert outcome.status == "completed"
    # The out-of-range entry is dropped; the valid one keeps OUR identity.
    assert outcome.proposition_count == 1
    with factory() as database:
        rows = list(
            database.scalars(
                select(DiscordCondensationProposition).where(
                    DiscordCondensationProposition.batch_id == planned.batch_id
                )
            )
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.speaker_id == "real-author"
        assert row.speaker_display_name == "User real-author"
        assert len(row.source_message_ids) == 2
        assert all(value != "999" for value in row.source_message_ids)
        batch = database.get(DiscordCondensationBatch, planned.batch_id)
        assert batch.status == "completed"
        assert batch.model_used == "fake-condenser"


def test_transcript_carries_time_and_name(world):
    factory, prefix, history = world
    _seed(history, prefix, 20, author="u7")
    condenser = FakeCondenser()
    service = _service(factory, condenser)
    planned = service.plan_batch(f"{prefix}-g1", "chan-1")
    service.run_batch(planned.batch_id)

    transcript = condenser.calls[0]["messages"][1]["content"]
    assert transcript.startswith("#1 [26/08 09:00] User u7: tin so 0")
    assert "#20 " in transcript


def test_model_failure_retries_then_releases_the_messages(world):
    factory, prefix, history = world
    _seed(history, prefix, 20)
    condenser = FakeCondenser(error=RuntimeError("network down"))
    service = _service(factory, condenser, max_attempts=2)
    planned = service.plan_batch(f"{prefix}-g1", "chan-1")

    first = service.run_batch(planned.batch_id)
    assert first.status == "retrying"
    with factory() as database:
        batch = database.get(DiscordCondensationBatch, planned.batch_id)
        assert batch.status == "pending"
        held = database.scalar(
            select(DiscordChannelMessage)
            .where(DiscordChannelMessage.condensation_batch_id == planned.batch_id)
            .limit(1)
        )
        assert held is not None  # still claimed while retries remain

    second = service.run_batch(planned.batch_id)
    assert second.status == "failed"
    with factory() as database:
        batch = database.get(DiscordCondensationBatch, planned.batch_id)
        assert batch.status == "failed"
        assert batch.error_code == "condenser_error"
        # §7.7: a dead network must never silently swallow a span.
        released = database.scalar(
            select(DiscordChannelMessage)
            .where(DiscordChannelMessage.condensation_batch_id == planned.batch_id)
            .limit(1)
        )
        assert released is None


def test_service_without_a_condenser_is_inert(world):
    factory, prefix, history = world
    _seed(history, prefix, 20)
    service = _service(factory, None)
    assert service.enabled is False
    planned = service.plan_batch(f"{prefix}-g1", "chan-1")
    outcome = service.run_batch(planned.batch_id)
    assert outcome.reason == "condenser_not_configured"


def test_read_path_is_guild_scoped_and_chronological(world):
    factory, prefix, history = world
    _seed(history, prefix, 20, guild="g1")
    _seed(history, prefix, 20, guild="g2", start=200, author="u9")
    condenser = FakeCondenser(
        answer='[{"content": "menh de mot", "source": [1]},'
        '{"content": "menh de hai", "source": [5]}]'
    )
    service = _service(factory, condenser)
    for guild in ("g1", "g2"):
        planned = service.plan_batch(f"{prefix}-{guild}", "chan-1")
        service.run_batch(planned.batch_id)

    rows = service.recent_propositions(guild_id=f"{prefix}-g1", limit=8)
    assert [row.content for row in rows] == ["menh de mot", "menh de hai"]
    assert all(row.guild_id == f"{prefix}-g1" for row in rows)
    assert service.recent_propositions(guild_id=f"{prefix}-khac") == []


def test_forget_member_removes_only_that_speaker(world):
    factory, prefix, history = world
    _seed(history, prefix, 10, author="alice", start=0)
    _seed(history, prefix, 10, author="bob", start=10)
    condenser = FakeCondenser(
        answer='[{"content": "cua alice", "source": [1]},'
        '{"content": "cua bob", "source": [11]}]'
    )
    service = _service(factory, condenser)
    planned = service.plan_batch(f"{prefix}-g1", "chan-1")
    service.run_batch(planned.batch_id)

    removed = service.forget_member(guild_id=f"{prefix}-g1", speaker_id="alice")
    assert removed == 1
    rows = service.recent_propositions(guild_id=f"{prefix}-g1")
    assert [row.speaker_id for row in rows] == ["bob"]


def test_edit_marks_the_covering_batch_stale(world):
    factory, prefix, history = world
    ids = _seed(history, prefix, 20)
    condenser = FakeCondenser(answer='[{"content": "x", "source": [1]}]')
    service = _service(factory, condenser)
    planned = service.plan_batch(f"{prefix}-g1", "chan-1")
    service.run_batch(planned.batch_id)

    assert history.record_edit(discord_message_id=ids[3], content="noi dung da sua")
    assert service.mark_stale(discord_message_id=ids[3]) == planned.batch_id
    with factory() as database:
        assert database.get(
            DiscordCondensationBatch, planned.batch_id
        ).status == "stale"


def test_delete_batch_revokes_and_frees_the_span(world):
    factory, prefix, history = world
    _seed(history, prefix, 20)
    condenser = FakeCondenser(answer='[{"content": "x", "source": [1]}]')
    service = _service(factory, condenser)
    planned = service.plan_batch(f"{prefix}-g1", "chan-1")
    service.run_batch(planned.batch_id)

    assert service.delete_batch(planned.batch_id) is True
    with factory() as database:
        assert database.get(DiscordCondensationBatch, planned.batch_id) is None
        assert (
            database.scalar(
                select(DiscordCondensationProposition).where(
                    DiscordCondensationProposition.batch_id == planned.batch_id
                )
            )
            is None
        )
    # Freed messages are condensable again — a regenerate can replace it.
    assert service.ready_channels()


def test_bot_attributed_propositions_are_dropped(world):
    """MEASURED 28/08: on real data 9/10 propositions were attributed to the
    assistant, two of them crystallising its own hallucinations. §9.3 keeps
    bot lines for coherence; they must never become remembered content."""
    factory, prefix, history = world
    _seed(history, prefix, 10, author="nguoi-that", start=0)
    for index in range(10):
        at = BASE + timedelta(minutes=10 + index)
        history.record_message(
            guild_id=f"{prefix}-g1", channel_id="chan-1", thread_id=None,
            discord_message_id=_snowflake(at, 300 + index),
            author_id="bot-un", author_display_name="Ún",
            is_bot=True, content=f"Ún noi dieu co the sai {index}",
        )
    condenser = FakeCondenser(
        answer='[{"content": "tu loi thanh vien", "source": [1]},'
        '{"content": "tu loi bot - phai bi loai", "source": [11, 1]}]'
    )
    service = _service(factory, condenser)
    planned = service.plan_batch(f"{prefix}-g1", "chan-1")
    outcome = service.run_batch(planned.batch_id)

    assert outcome.proposition_count == 1
    rows = service.recent_propositions(guild_id=f"{prefix}-g1")
    assert [row.content for row in rows] == ["tu loi thanh vien"]
    assert rows[0].speaker_id == "nguoi-that"


def test_transcript_marks_bot_lines(world):
    factory, prefix, history = world
    _seed(history, prefix, 19, author="u1")
    at = BASE + timedelta(minutes=100)
    history.record_message(
        guild_id=f"{prefix}-g1", channel_id="chan-1", thread_id=None,
        discord_message_id=_snowflake(at, 400),
        author_id="bot-un", author_display_name="Ún",
        is_bot=True, content="loi cua bot",
    )
    condenser = FakeCondenser()
    service = _service(factory, condenser)
    planned = service.plan_batch(f"{prefix}-g1", "chan-1")
    service.run_batch(planned.batch_id)

    transcript = condenser.calls[0]["messages"][1]["content"]
    assert "[BOT] Ún: loi cua bot" in transcript
    assert "[BOT] User u1" not in transcript
