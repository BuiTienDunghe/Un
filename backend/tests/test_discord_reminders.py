"""Ticket 48: reminders, checked without a database.

The store is replaced by an in-memory one that follows the same contract, so these tests cover the
rules (off by default, creator-only cancel, guild allowlist, late and failed sends, the agent's
gate); the SQL store itself, the migration and a real claim race need PostgreSQL.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import discord
from app.config.settings import PROJECT_ROOT, Settings
from app.discord import reminders as policy
from app.discord.remind_tool import Remind, TurnFacts, asked_for_reminder, names_a_time
from app.discord.reminders import Reminder, ReminderError, ReminderService
from app.discord.routers import reminders as reminder_routes
from app.postgres.database import create_postgres_engine, create_session_factory
from app.services.agent_service import AgentService, core_tools

NOW = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
GUILD, OTHER_GUILD = "111", "222"
ME, YOU = "900", "901"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class MemoryStore:
    """What SqlReminderStore promises, in a dict."""

    def __init__(self) -> None:
        self.rows: dict[str, Reminder] = {}
        self.retry_at: dict[str, datetime] = {}
        self.claimed_at: dict[str, datetime] = {}
        self.errors: dict[str, str | None] = {}

    def add(self, reminder: Reminder) -> None:
        self.rows[reminder.id] = reminder

    def get(self, reminder_id: str) -> Reminder | None:
        return self.rows.get(reminder_id)

    def by_turn(self, turn_id: str) -> list[Reminder]:
        return [row for row in self.rows.values() if row.source_turn_id == turn_id]

    def pending_for(self, guild_id: str, creator_id: str) -> list[Reminder]:
        return [r for r in self.rows.values() if (r.guild_id, r.creator_id) == (guild_id, creator_id) and r.status in ("pending", "sending")]

    def recent_missed_for(self, guild_id: str, creator_id: str, since: datetime) -> list[Reminder]:
        return [r for r in self.rows.values() if (r.guild_id, r.creator_id, r.status) == (guild_id, creator_id, "missed") and self.claimed_at[r.id] >= since]

    def find(self, guild_id: str, ref: str) -> list[Reminder]:
        return [r for r in self.rows.values() if r.guild_id == guild_id and r.id.startswith(ref) and r.status in ("pending", "sending")]

    def cancel_if_pending(self, reminder_id: str) -> bool:
        row = self.rows[reminder_id]
        if row.status != "pending":
            return False
        self.rows[reminder_id] = replace(row, status="cancelled")
        return True

    def claim_due(self, now: datetime, lease_cutoff: datetime, limit: int) -> list[Reminder]:
        due = [
            r for r in sorted(self.rows.values(), key=lambda r: r.due_at)
            if (r.status == "pending" and r.due_at <= now and self.retry_at.get(r.id, now) <= now)
            or (r.status == "sending" and self.claimed_at[r.id] < lease_cutoff)
        ][:limit]
        claimed = []
        for row in due:
            self.rows[row.id] = row = replace(row, status="sending", attempts=row.attempts + 1)
            self.claimed_at[row.id] = now
            claimed.append(row)
        return claimed

    def finish(self, reminder_id: str, status: str, now: datetime, *, error: str | None = None, discord_message_id: str | None = None, retry_at: datetime | None = None) -> None:
        if self.rows[reminder_id].status != "sending":
            return
        self.rows[reminder_id] = replace(self.rows[reminder_id], status=status)
        self.errors[reminder_id] = error
        if retry_at:
            self.retry_at[reminder_id] = retry_at


def build(enabled: bool = True, allowed: frozenset[str] | None = frozenset({GUILD})):
    clock, store = Clock(), MemoryStore()
    service = ReminderService(store, enabled=enabled, guild_allowed=lambda guild: allowed is None or guild in allowed, clock=clock)
    return service, store, clock


def make(service: ReminderService, *, creator: str = ME, text: str = "Họp nhóm", minutes: int = 60, guild: str = GUILD, turn: str | None = None) -> Reminder:
    return service.create(
        guild_id=guild, channel_id="chan", thread_id=None, creator_id=creator, creator_display_name="Dũng", text=text,
        due_at=NOW + timedelta(minutes=minutes), source_turn_id=turn,
    )


def refusal(call) -> str:
    with pytest.raises(ReminderError) as caught:
        call()
    return caught.value.code


# ---- off by default ----

def test_reminders_are_off_unless_switched_on() -> None:
    assert Settings(_env_file=None, database_url="postgresql+psycopg://x:x@127.0.0.1:1/x").discord_reminders_enabled is False
    service, store, _ = build(enabled=False)
    assert refusal(lambda: make(service)) == "REMINDERS_DISABLED"
    assert refusal(lambda: service.list_for(GUILD, ME)) == "REMINDERS_DISABLED"
    assert refusal(lambda: service.cancel("abcdef", guild_id=GUILD, requester_id=ME)) == "REMINDERS_DISABLED"
    assert refusal(service.claim_due) == "REMINDERS_DISABLED"
    assert refusal(lambda: service.mark_sent("x", None)) == "REMINDERS_DISABLED"
    assert store.rows == {}


def test_the_default_wiring_offers_no_remind_tool_and_the_switch_adds_it() -> None:
    def wire(**flags):
        settings = Settings(_env_file=None, database_url="postgresql+psycopg://test:test@127.0.0.1:1/none", **flags)
        sessions = create_session_factory(create_postgres_engine(str(settings.database_url)))  # never connects here
        agent = SimpleNamespace(registry=core_tools())
        app = SimpleNamespace(state=SimpleNamespace(memory_service=object(), chat_service=object(), agent_service=agent))
        discord.register_services(app, settings, sessions, project_root=PROJECT_ROOT)
        return app, agent

    app, agent = wire()
    assert "remind" not in agent.registry.names() and app.state.reminder_service.enabled is False
    app, agent = wire(discord_reminders_enabled=True)
    assert "remind" in agent.registry.names() and app.state.reminder_service.enabled is True


# ---- the server allowlist ----

def test_a_server_outside_the_allowlist_is_refused_everywhere() -> None:
    service, store, _ = build()
    assert refusal(lambda: make(service, guild=OTHER_GUILD)) == "GUILD_NOT_ALLOWED"
    assert refusal(lambda: service.list_for(OTHER_GUILD, ME)) == "GUILD_NOT_ALLOWED"
    assert refusal(lambda: service.cancel("abcdef", guild_id=OTHER_GUILD, requester_id=ME)) == "GUILD_NOT_ALLOWED"
    assert store.rows == {}


def test_a_server_that_leaves_the_allowlist_gets_nothing_sent() -> None:
    allowed = {GUILD}
    clock, store = Clock(), MemoryStore()
    service = ReminderService(store, enabled=True, guild_allowed=lambda guild: guild in allowed, clock=clock)
    reminder = make(service)
    allowed.clear()
    clock.now = NOW + timedelta(minutes=61)
    assert service.claim_due() == []
    assert store.rows[reminder.id].status == "failed" and store.errors[reminder.id] == "guild_not_allowed"


# ---- who may cancel ----

def test_only_the_creator_cancels() -> None:
    service, store, _ = build()
    reminder = make(service)
    assert refusal(lambda: service.cancel(reminder.id, guild_id=GUILD, requester_id=YOU)) == "REMINDER_NOT_YOURS"
    assert store.rows[reminder.id].status == "pending"
    service.cancel(reminder.short_id, guild_id=GUILD, requester_id=ME)
    assert store.rows[reminder.id].status == "cancelled"


def test_a_cancelled_reminder_is_never_handed_to_the_bot() -> None:
    service, _, clock = build()
    reminder = make(service)
    service.cancel(reminder.short_id, guild_id=GUILD, requester_id=ME)
    clock.now = NOW + timedelta(hours=2)
    assert service.claim_due() == []


@pytest.mark.parametrize("ref", ["", "abc", "zzzzzz", "%", "ab%def", "abcdef' OR 1=1"])
def test_a_reference_that_is_not_an_id_prefix_finds_nothing(ref) -> None:
    service, _, _ = build()
    make(service)
    assert refusal(lambda: service.cancel(ref, guild_id=GUILD, requester_id=ME)) == "REMINDER_NOT_FOUND"


def test_a_reminder_being_sent_cannot_be_cancelled_and_one_in_another_server_is_not_found() -> None:
    service, _, clock = build()
    reminder = make(service)
    clock.now = NOW + timedelta(minutes=61)
    service.claim_due()
    assert refusal(lambda: service.cancel(reminder.short_id, guild_id=GUILD, requester_id=ME)) == "REMINDER_NOT_CANCELLABLE"
    other, _, _ = build(allowed=frozenset({GUILD, OTHER_GUILD}))
    assert refusal(lambda: other.cancel(make(other).short_id, guild_id=OTHER_GUILD, requester_id=ME)) == "REMINDER_NOT_FOUND"


# ---- making one ----

def test_a_reminder_is_kept_in_the_channel_it_was_asked_in() -> None:
    service, _, _ = build()
    reminder = service.create(
        guild_id=GUILD, channel_id="chan", thread_id="thread", creator_id=ME, creator_display_name="Dũng", text="  Gọi   mẹ ", due_at=NOW + timedelta(hours=1),
    )
    assert reminder.target_channel_id == "thread" and reminder.text == "Gọi mẹ" and reminder.creator_id == ME


@pytest.mark.parametrize("kwargs,code", [
    ({"minutes": -5}, "TIME_IN_PAST"),
    ({"minutes": 0}, "TIME_IN_PAST"),
    ({"minutes": 60 * 24 * 91}, "TIME_TOO_FAR"),
    ({"text": "   "}, "BAD_TEXT"),
    ({"text": "x" * (policy.TEXT_MAX_CHARS + 1)}, "BAD_TEXT"),
])
def test_a_bad_hour_or_text_is_refused(kwargs, code) -> None:
    service, store, _ = build()
    assert refusal(lambda: make(service, **kwargs)) == code
    assert store.rows == {}


def test_one_member_cannot_pile_up_reminders() -> None:
    service, _, _ = build()
    for number in range(policy.MAX_PENDING_PER_MEMBER):
        make(service, text=f"Việc {number}")
    assert refusal(lambda: make(service, text="Một việc nữa")) == "TOO_MANY"
    make(service, creator=YOU)  # the cap is per member


def test_one_message_makes_at_most_three_and_a_repeated_call_makes_none_more() -> None:
    service, store, _ = build()
    turn = "t-1"
    first = make(service, text="Một", turn=turn)
    assert make(service, text="Một", turn=turn).id == first.id
    make(service, text="Hai", turn=turn)
    make(service, text="Ba", turn=turn)
    assert refusal(lambda: make(service, text="Bốn", turn=turn)) == "TOO_MANY_IN_TURN"
    assert len(store.rows) == 3


# ---- the hour, late hours, failed sends ----

def test_a_reminder_is_handed_over_once_at_its_hour_and_not_before() -> None:
    service, _, clock = build()
    reminder = make(service)
    clock.now = NOW + timedelta(minutes=59)
    assert service.claim_due() == []
    clock.now = NOW + timedelta(minutes=60, seconds=20)
    due = service.claim_due()
    assert [(item.reminder.id, item.late_seconds) for item in due] == [(reminder.id, 20)]
    assert service.claim_due() == []  # being sent: not handed out twice
    service.mark_sent(reminder.id, "m-1")


def test_a_reminder_missed_while_the_machine_was_off_is_sent_late_and_flagged() -> None:
    service, _, clock = build()
    make(service)
    clock.now = NOW + timedelta(minutes=60, hours=5)
    (item,) = service.claim_due()
    assert item.late_seconds == 5 * 3600


def test_a_reminder_more_than_a_day_late_is_not_sent_but_still_listed_for_its_creator() -> None:
    service, store, clock = build()
    reminder = make(service)
    clock.now = NOW + timedelta(minutes=60) + policy.MISSED_AFTER
    assert service.claim_due() == []
    assert store.rows[reminder.id].status == "missed"
    assert [r.id for r in service.list_for(GUILD, ME)] == [reminder.id]
    clock.now += timedelta(hours=25)
    assert service.list_for(GUILD, ME) == []


def test_a_claim_the_bot_never_finished_is_handed_out_again_after_the_lease() -> None:
    service, _, clock = build()
    reminder = make(service)
    clock.now = NOW + timedelta(minutes=61)
    assert len(service.claim_due()) == 1
    clock.now += policy.LEASE - timedelta(minutes=1)
    assert service.claim_due() == []
    clock.now += timedelta(minutes=2)
    assert [item.reminder.id for item in service.claim_due()] == [reminder.id]


def test_a_failed_send_is_retried_after_a_pause_and_gives_up_after_the_limit() -> None:
    service, store, clock = build()
    reminder = make(service)
    clock.now = NOW + timedelta(minutes=61)
    for attempt in range(1, policy.MAX_ATTEMPTS + 1):
        assert [item.reminder.id for item in service.claim_due()] == [reminder.id]
        outcome = service.mark_failed(reminder.id, "timeout", retryable=True)
        assert outcome == ("pending" if attempt < policy.MAX_ATTEMPTS else "failed")
        if outcome == "pending":
            assert service.claim_due() == []  # waits out the pause
            clock.now += policy.RETRY_DELAY
    assert store.rows[reminder.id].status == "failed"
    clock.now += timedelta(hours=1)
    assert service.claim_due() == []


def test_a_send_that_can_never_work_is_not_retried() -> None:
    service, store, clock = build()
    reminder = make(service)
    clock.now = NOW + timedelta(minutes=61)
    service.claim_due()
    assert service.mark_failed(reminder.id, "channel deleted", retryable=False) == "failed"
    assert store.rows[reminder.id].status == "failed"
    assert refusal(lambda: service.mark_failed(reminder.id, "again", retryable=True)) == "REMINDER_NOT_FOUND"


# ---- the HTTP surface ----

def api(service: ReminderService) -> TestClient:
    app = FastAPI()
    app.include_router(reminder_routes.router)
    app.state.reminder_service = service
    return TestClient(app)


def test_the_routes_carry_the_refusals_with_their_codes() -> None:
    service, _, clock = build()
    reminder = make(service)
    client = api(service)
    response = client.post(f"/api/discord/reminders/{reminder.short_id}/cancel", json={"guild_id": GUILD, "requester_id": YOU})
    assert response.status_code == 403 and response.json()["detail"]["error_code"] == "REMINDER_NOT_YOURS"
    response = client.post(f"/api/discord/reminders/{reminder.short_id}/cancel", json={"guild_id": OTHER_GUILD, "requester_id": ME})
    assert response.status_code == 403 and response.json()["detail"]["error_code"] == "GUILD_NOT_ALLOWED"
    assert client.get("/api/discord/reminders", params={"guild_id": GUILD, "author_id": ME}).json()[0]["short_id"] == reminder.short_id
    clock.now = NOW + timedelta(minutes=61)
    claimed = client.post("/api/discord/reminders/claim").json()
    assert claimed[0]["id"] == reminder.id and claimed[0]["channel_id"] == "chan" and claimed[0]["creator_id"] == ME
    assert client.post(f"/api/discord/reminders/{reminder.id}/sent", json={"discord_message_id": "m"}).json() == {"status": "sent"}
    assert client.post("/api/discord/reminders/not-a-uuid/failed", json={"error": "x", "retryable": True}).status_code == 404
    response = client.post(f"/api/discord/reminders/{reminder.short_id}/cancel", json={"guild_id": GUILD, "requester_id": ME})
    assert response.status_code == 404


def test_the_routes_say_plainly_when_reminders_are_off() -> None:
    client = api(build(enabled=False)[0])
    assert client.post("/api/discord/reminders/claim").json()["detail"]["error_code"] == "REMINDERS_DISABLED"
    assert client.post("/api/discord/reminders/claim").status_code == 409


# ---- the agent's tool ----

def agent() -> AgentService:
    return AgentService(SimpleNamespace(models={"general": {"name": "m"}}), SimpleNamespace(), SimpleNamespace())


def tool_for(own_text: str, *, service: ReminderService | None = None, facts: bool = True):
    service = service or build()[0]
    turn = TurnFacts(GUILD, "chan", None, ME, "Dũng", own_text) if facts else None
    return Remind(service, lambda turn_id: turn), service


def call(tool: Remind, **arguments):
    output, code, _ = tool(agent(), arguments, {"turn_id": "11111111-1111-1111-1111-111111111111"})
    return json.loads(output), code


@pytest.mark.parametrize("text", ["Nhắc tôi 3 giờ chiều mai gọi mẹ", "nhắc mình uống thuốc sau 30 phút nữa", "Đặt nhắc họp lúc 9h", "hẹn giờ 8h nấu cơm", "remind me at 5pm"])
def test_a_request_to_be_reminded_is_heard(text) -> None:
    assert asked_for_reminder(text)


@pytest.mark.parametrize("text", ["Bạn có nhắc tôi chuyện hôm qua không?", "Họ đã nhắc đến dự án", "Đừng nhắc tôi nữa", "không cần nhắc tôi đâu", "Mấy giờ rồi?"])
def test_anything_else_is_not_a_request(text) -> None:
    assert not asked_for_reminder(text)


def test_a_reminder_needs_the_speaker_to_name_a_time() -> None:
    assert names_a_time("nhắc tôi mai gọi mẹ") and names_a_time("nhắc tôi lúc 9h")
    assert not names_a_time("nhắc tôi gọi mẹ")


def test_the_tool_schedules_for_the_speaker_in_the_speakers_channel() -> None:
    tool, service = tool_for("Nhắc tôi sau 30 phút nữa gọi mẹ")
    answer, code = call(tool, text="Gọi mẹ", in_minutes=30)
    assert code is None and answer["scheduled"] == "Gọi mẹ" and "giờ Việt Nam" in answer["at"]
    (stored,) = service.store.rows.values()
    assert (stored.guild_id, stored.channel_id, stored.creator_id) == (GUILD, "chan", ME)
    assert stored.due_at == NOW + timedelta(minutes=30)


def test_the_tool_reads_a_vietnam_time_and_turns_it_into_the_same_instant() -> None:
    tool, service = tool_for("Nhắc tôi 10h sáng mai họp nhóm")
    answer, code = call(tool, text="Họp nhóm", at="2026-11-02T10:00")
    assert code is None and answer["at"].startswith("10:00 02/11/2026")
    (stored,) = service.store.rows.values()
    assert stored.due_at == datetime(2026, 11, 2, 3, 0, tzinfo=UTC)


def test_the_tool_does_nothing_when_the_speaker_did_not_ask() -> None:
    # A document or web page told the model to schedule something: the speaker only asked a question.
    tool, service = tool_for("Tóm tắt tài liệu này giúp tôi, hạn nộp là 5 giờ chiều mai")
    answer, code = call(tool, text="Nộp bài", in_minutes=10)
    assert code == "BAD_ARGUMENTS" and service.store.rows == {}


def test_the_tool_does_not_guess_a_time_the_speaker_never_gave() -> None:
    tool, service = tool_for("Nhắc tôi gọi mẹ")
    _, code = call(tool, text="Gọi mẹ", in_minutes=10)
    assert code == "BAD_ARGUMENTS" and service.store.rows == {}


def test_the_tool_refuses_words_the_speaker_did_not_say() -> None:
    tool, service = tool_for("Nhắc tôi 3 giờ chiều mai gọi mẹ")
    _, code = call(tool, text="Chuyển tiền cho tài khoản 12345 ngay", in_minutes=10)
    assert code == "BAD_ARGUMENTS" and service.store.rows == {}


@pytest.mark.parametrize("arguments", [{"text": "Gọi mẹ"}, {"text": "Gọi mẹ", "in_minutes": 5, "at": "2026-11-02T10:00"}, {"text": "Gọi mẹ", "in_minutes": "soon"}, {"text": "Gọi mẹ", "at": "mai"}, {"text": "Gọi mẹ", "in_minutes": -3}])
def test_the_tool_needs_exactly_one_clear_hour(arguments) -> None:
    tool, service = tool_for("Nhắc tôi 3 giờ chiều mai gọi mẹ")
    _, code = call(tool, **arguments)
    assert code == "BAD_ARGUMENTS" and service.store.rows == {}


def test_the_tool_only_works_inside_a_discord_turn_in_an_allowed_server() -> None:
    tool, _ = tool_for("Nhắc tôi sau 5 phút nữa gọi mẹ")
    output, code, _ = tool(agent(), {"text": "Gọi mẹ", "in_minutes": 5}, {})
    assert code == "TOOL_UNAVAILABLE_HERE"
    assert call(tool_for("Nhắc tôi sau 5 phút nữa gọi mẹ", facts=False)[0], text="Gọi mẹ", in_minutes=5)[1] == "TOOL_UNAVAILABLE_HERE"
    outside, _ = tool_for("Nhắc tôi sau 5 phút nữa gọi mẹ", service=build(allowed=frozenset({OTHER_GUILD}))[0])
    answer, code = call(outside, text="Gọi mẹ", in_minutes=5)
    assert code == "BAD_ARGUMENTS" and "server" in answer["error"]
