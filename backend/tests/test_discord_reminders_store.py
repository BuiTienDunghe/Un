"""Ticket 48: the SQL store and the forgetting of reminders.

The first half runs the real SQL of SqlReminderStore on in-memory SQLite (the table alone, no
other); SQLite ignores FOR UPDATE and stores UUIDs without dashes, so the claim race and the
dashed-UUID prefix lookup stay for PostgreSQL. The second half needs POSTGRES_TEST_URL.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from app.discord import reminders as policy
from app.discord.reminders import ReminderError, ReminderService, SqlReminderStore
from app.postgres.models import DiscordReminder
from scripts.forget_member import _forget_reminders

NOW = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
GUILD, OTHER_GUILD = "111", "222"
ME, YOU = "900", "901"


class Clock:
    now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def world():
    engine = create_engine("sqlite://")
    DiscordReminder.__table__.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    clock = Clock()
    service = ReminderService(
        SqlReminderStore(sessions), enabled=True, guild_allowed=lambda guild: guild in {GUILD, OTHER_GUILD}, clock=clock,
    )
    return service, sessions, clock


def make(service, *, creator=ME, guild=GUILD, text="Họp nhóm", minutes=60, turn=None):
    return service.create(
        guild_id=guild, channel_id="chan", thread_id=None, creator_id=creator, text=text,
        due_at=NOW + timedelta(minutes=minutes), source_turn_id=turn,
    )


def status_of(sessions, reminder_id) -> str:
    with sessions() as database:
        return database.scalar(select(DiscordReminder.status).where(DiscordReminder.id == UUID(reminder_id)))


def test_the_life_of_a_reminder_through_real_sql(world) -> None:
    service, sessions, clock = world
    reminder = make(service)
    assert [r.id for r in service.list_for(GUILD, ME)] == [reminder.id]
    clock.now = NOW + timedelta(minutes=61)
    (due,) = service.claim_due()
    assert due.reminder.id == reminder.id and due.late_seconds == 60 and status_of(sessions, reminder.id) == "sending"
    assert service.claim_due() == []
    service.mark_sent(reminder.id, "m-1")
    assert status_of(sessions, reminder.id) == "sent"
    assert service.list_for(GUILD, ME) == []


def test_cancel_by_short_code_and_only_by_the_creator(world) -> None:
    service, sessions, clock = world
    reminder = make(service)
    with pytest.raises(ReminderError) as caught:
        service.cancel(reminder.short_id, guild_id=GUILD, requester_id=YOU)
    assert caught.value.code == "REMINDER_NOT_YOURS" and status_of(sessions, reminder.id) == "pending"
    service.cancel(reminder.short_id, guild_id=GUILD, requester_id=ME)
    assert status_of(sessions, reminder.id) == "cancelled"
    clock.now = NOW + timedelta(hours=2)
    assert service.claim_due() == []


def test_a_send_that_failed_waits_then_a_lost_claim_comes_back(world) -> None:
    service, sessions, clock = world
    reminder = make(service)
    clock.now = NOW + timedelta(minutes=61)
    service.claim_due()
    assert service.mark_failed(reminder.id, "timeout", retryable=True) == "pending"
    assert service.claim_due() == []
    clock.now += policy.RETRY_DELAY + timedelta(seconds=1)
    assert [d.reminder.attempts for d in service.claim_due()] == [2]
    clock.now += policy.LEASE + timedelta(seconds=1)
    assert [d.reminder.attempts for d in service.claim_due()] == [3]
    clock.now += policy.LEASE + timedelta(seconds=1)
    assert service.claim_due() == []  # a fourth claim is refused: the bot keeps losing it
    assert status_of(sessions, reminder.id) == "failed"


def test_forgetting_a_member_leaves_no_reminder_to_ping_them(world) -> None:
    service, sessions, clock = world
    mine = make(service, text="Gọi mẹ")
    mine_elsewhere = make(service, text="Họp ở server khác", guild=OTHER_GUILD)
    yours = make(service, creator=YOU, text="Của bạn")
    with sessions.begin() as database:
        assert _forget_reminders(database, ME, GUILD) == 1  # only the guild where they asked
    with sessions() as database:
        left = set(database.scalars(select(DiscordReminder.id)))
    assert {str(i) for i in left} == {mine_elsewhere.id, yours.id}
    clock.now = NOW + timedelta(hours=2)
    assert {d.reminder.id for d in service.claim_due()} == {mine_elsewhere.id, yours.id}
    with sessions.begin() as database:
        assert _forget_reminders(database, ME, None) == 1  # every guild
    assert service.list_for(OTHER_GUILD, ME) == []


def test_the_reminder_follows_its_turn_and_holds_no_name() -> None:
    column = DiscordReminder.__table__.c.source_turn_id
    (key,) = column.foreign_keys
    assert key.target_fullname == "discord_session_turns.id" and key.ondelete == "CASCADE"
    assert "creator_display_name" not in DiscordReminder.__table__.c
    migration = (Path(__file__).parents[1] / "alembic" / "versions" / "20261101_37_discord_reminders.py").read_text(encoding="utf-8")
    assert 'ForeignKey("discord_session_turns.id", ondelete="CASCADE")' in migration and "creator_display_name" not in migration


# ---- PostgreSQL: the real cascade and the real script ----

URL = os.getenv("POSTGRES_TEST_URL")
needs_postgres = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


@needs_postgres
def test_deleting_the_turn_or_the_conversation_deletes_the_reminder_and_forget_member_clears_the_rest(monkeypatch) -> None:
    from app.postgres.database import create_postgres_engine, create_session_factory
    from app.postgres.models import DiscordConversationSession, DiscordSessionTurn
    from scripts.forget_member import forget

    factory = create_session_factory(create_postgres_engine(str(URL)))
    tag = uuid4().hex[:8]
    guild, author = f"guild-{tag}", f"a-{tag}"
    session_id, turn_a, turn_b = uuid4(), uuid4(), uuid4()
    with factory.begin() as database:
        database.add(DiscordConversationSession(id=session_id, guild_id=guild, channel_id="c1", backend_conversation_id=uuid4()))
        database.flush()
        for turn_id, number in ((turn_a, 1), (turn_b, 2)):
            database.add(DiscordSessionTurn(
                id=turn_id, session_id=session_id, discord_message_id=f"t{number}{tag}", sequence_number=number,
                request_text="Nhắc tôi 9h mai họp", response_text="Rồi.", author_id=author, author_display_name="Lan", status="completed",
            ))
        database.flush()
        for turn_id, text in ((turn_a, "Họp"), (turn_b, "Họp nữa")):
            database.add(DiscordReminder(
                guild_id=guild, channel_id="c1", creator_id=author, text=text, due_at=NOW + timedelta(days=1), source_turn_id=turn_id,
            ))

    def count() -> int:
        with factory() as database:
            return int(database.scalar(select(func.count()).select_from(DiscordReminder).where(DiscordReminder.guild_id == guild)))

    try:
        with factory.begin() as database:
            database.execute(delete(DiscordSessionTurn).where(DiscordSessionTurn.id == turn_a))
        assert count() == 1  # the turn took its reminder with it
        monkeypatch.setenv("DATABASE_URL", str(URL))
        report = forget(guild, author, apply=True)
        assert report["remaining"]["reminders"] == 0 and count() == 0
        with factory.begin() as database:
            database.add(DiscordSessionTurn(
                id=uuid4(), session_id=session_id, discord_message_id=f"t3{tag}", sequence_number=3,
                request_text="Nhắc tôi 9h mai ăn", response_text="Rồi.", author_id=author, author_display_name="Lan", status="completed",
            ))
            database.flush()
            database.add(DiscordReminder(
                guild_id=guild, channel_id="c1", creator_id=author, text="Ăn", due_at=NOW + timedelta(days=1),
                source_turn_id=database.scalar(select(DiscordSessionTurn.id).where(DiscordSessionTurn.discord_message_id == f"t3{tag}")),
            ))
        with factory.begin() as database:
            database.execute(delete(DiscordConversationSession).where(DiscordConversationSession.id == session_id))
        assert count() == 0  # a deleted conversation takes its reminders
    finally:
        with factory.begin() as database:
            database.execute(delete(DiscordReminder).where(DiscordReminder.guild_id == guild))
            database.execute(delete(DiscordConversationSession).where(DiscordConversationSession.id == session_id))
