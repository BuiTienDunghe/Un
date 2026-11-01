"""Reminders (ticket 48): a member asks, the bot says it back at the hour. Nothing else is ever sent.

Rules the service keeps, whatever store sits under it:
- Off unless DISCORD_REMINDERS_ENABLED; every call then fails with REMINDERS_DISABLED.
- A reminder is created only in a guild on DISCORD_AGENT_TOOLS_GUILD_ALLOWLIST, and is sent only
  while its guild still is: one removed in between is marked failed, not sent.
- Only the member who created a reminder can cancel it.
- A reminder goes to the channel (or thread) it was asked in and mentions only its creator.
- Late: the bot polls, so a reminder claimed a little after its hour is sent as it is. Claimed
  LATE_NOTE_SECONDS or more after the hour (the machine was off) it is sent with a note saying
  how late. Claimed MISSED_AFTER or more after, it is marked `missed` and NOT sent: a "take your
  medicine at 8" arriving the next day is noise. `/reminders list` still shows it for a day.
- A send that fails is retried (RETRY_DELAY apart, MAX_ATTEMPTS in all) when Discord or the
  network was at fault, and gives up at once when the channel is gone or forbidden. A bot that
  died after claiming leaves the row `sending`; after LEASE it is claimed again, so a reminder
  is delivered at least once, and in that one crash window possibly twice.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import sessionmaker

from app.postgres.models import DiscordReminder

TEXT_MAX_CHARS = 500
MAX_PENDING_PER_MEMBER = 20
MAX_HORIZON = timedelta(days=90)
MIN_LEAD = timedelta(seconds=30)
LATE_NOTE_SECONDS = 300
MISSED_AFTER = timedelta(hours=24)
MISSED_LISTED_FOR = timedelta(hours=24)
MAX_ATTEMPTS = 3
RETRY_DELAY = timedelta(minutes=1)
LEASE = timedelta(minutes=10)
CLAIM_LIMIT = 10
REF_MIN_CHARS = 6


class ReminderError(Exception):
    """A refusal with a code the router and the tool show as they are."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Reminder:
    id: str
    guild_id: str
    channel_id: str
    thread_id: str | None
    creator_id: str
    creator_display_name: str | None
    text: str
    due_at: datetime
    status: str
    attempts: int = 0
    source_turn_id: str | None = None

    @property
    def short_id(self) -> str:
        return self.id[:8]

    @property
    def target_channel_id(self) -> str:
        return self.thread_id or self.channel_id


class ReminderStore(Protocol):
    def add(self, reminder: Reminder) -> None: ...

    def get(self, reminder_id: str) -> Reminder | None: ...

    def by_turn(self, turn_id: str) -> list[Reminder]: ...

    def pending_for(self, guild_id: str, creator_id: str) -> list[Reminder]: ...

    def recent_missed_for(self, guild_id: str, creator_id: str, since: datetime) -> list[Reminder]: ...

    def find(self, guild_id: str, ref: str) -> list[Reminder]: ...

    def cancel_if_pending(self, reminder_id: str) -> bool: ...

    def claim_due(self, now: datetime, lease_cutoff: datetime, limit: int) -> list[Reminder]: ...

    def finish(self, reminder_id: str, status: str, now: datetime, *, error: str | None = None, discord_message_id: str | None = None, retry_at: datetime | None = None) -> None: ...


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _row(row: DiscordReminder) -> Reminder:
    return Reminder(
        id=str(row.id), guild_id=row.guild_id, channel_id=row.channel_id, thread_id=row.thread_id,
        creator_id=row.creator_id, creator_display_name=row.creator_display_name, text=row.text,
        due_at=_utc(row.due_at), status=row.status, attempts=row.attempts,
        source_turn_id=str(row.source_turn_id) if row.source_turn_id else None,
    )


class SqlReminderStore:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def add(self, reminder: Reminder) -> None:
        with self.sessions.begin() as database:
            database.add(DiscordReminder(
                id=UUID(reminder.id), guild_id=reminder.guild_id, channel_id=reminder.channel_id, thread_id=reminder.thread_id,
                creator_id=reminder.creator_id, creator_display_name=reminder.creator_display_name, text=reminder.text,
                due_at=reminder.due_at, status="pending",
                source_turn_id=UUID(reminder.source_turn_id) if reminder.source_turn_id else None,
            ))

    def _select(self, *conditions: Any, order: Any = DiscordReminder.due_at) -> list[Reminder]:
        with self.sessions() as database:
            return [_row(row) for row in database.scalars(select(DiscordReminder).where(*conditions).order_by(order))]

    def get(self, reminder_id: str) -> Reminder | None:
        found = self._select(DiscordReminder.id == UUID(reminder_id))
        return found[0] if found else None

    def by_turn(self, turn_id: str) -> list[Reminder]:
        return self._select(DiscordReminder.source_turn_id == UUID(turn_id))

    def pending_for(self, guild_id: str, creator_id: str) -> list[Reminder]:
        return self._select(
            DiscordReminder.guild_id == guild_id, DiscordReminder.creator_id == creator_id,
            DiscordReminder.status.in_(("pending", "sending")),
        )

    def recent_missed_for(self, guild_id: str, creator_id: str, since: datetime) -> list[Reminder]:
        return self._select(
            DiscordReminder.guild_id == guild_id, DiscordReminder.creator_id == creator_id,
            DiscordReminder.status == "missed", DiscordReminder.claimed_at >= since,
        )

    def find(self, guild_id: str, ref: str) -> list[Reminder]:
        from sqlalchemy import String, cast

        return self._select(
            DiscordReminder.guild_id == guild_id, cast(DiscordReminder.id, String).like(f"{ref}%"),
            DiscordReminder.status.in_(("pending", "sending")),
        )

    def cancel_if_pending(self, reminder_id: str) -> bool:
        with self.sessions.begin() as database:
            result = database.execute(
                update(DiscordReminder).where(DiscordReminder.id == UUID(reminder_id), DiscordReminder.status == "pending")
                .values(status="cancelled")
            )
            return result.rowcount == 1

    def claim_due(self, now: datetime, lease_cutoff: datetime, limit: int) -> list[Reminder]:
        """Rows are locked while claimed, so two pollers never hold the same reminder."""
        with self.sessions.begin() as database:
            rows = database.scalars(
                select(DiscordReminder).where(or_(
                    (DiscordReminder.status == "pending") & (DiscordReminder.due_at <= now)
                    & or_(DiscordReminder.retry_at.is_(None), DiscordReminder.retry_at <= now),
                    (DiscordReminder.status == "sending") & (DiscordReminder.claimed_at < lease_cutoff),
                )).order_by(DiscordReminder.due_at).limit(limit).with_for_update(skip_locked=True)
            ).all()
            for row in rows:
                row.status, row.claimed_at, row.attempts = "sending", now, row.attempts + 1
            database.flush()
            return [_row(row) for row in rows]

    def finish(self, reminder_id: str, status: str, now: datetime, *, error: str | None = None, discord_message_id: str | None = None, retry_at: datetime | None = None) -> None:
        values: dict[str, Any] = {"status": status, "error": error, "retry_at": retry_at}
        if status == "sent":
            values.update(sent_at=now, discord_message_id=discord_message_id)
        with self.sessions.begin() as database:
            database.execute(
                update(DiscordReminder).where(DiscordReminder.id == UUID(reminder_id), DiscordReminder.status == "sending").values(**values)
            )


@dataclass(frozen=True)
class DueReminder:
    reminder: Reminder
    late_seconds: int


class ReminderService:
    def __init__(
        self,
        store: ReminderStore,
        *,
        enabled: bool,
        guild_allowed: Callable[[str | None], bool],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.enabled = enabled
        self.guild_allowed = guild_allowed
        self.clock = clock

    def _check(self, guild_id: str | None) -> None:
        if not self.enabled:
            raise ReminderError("REMINDERS_DISABLED", "Nhắc việc đang tắt.")
        if not guild_id or not self.guild_allowed(guild_id):
            raise ReminderError("GUILD_NOT_ALLOWED", "Nhắc việc chưa bật ở server này.")

    def create(
        self,
        *,
        guild_id: str,
        channel_id: str,
        thread_id: str | None,
        creator_id: str,
        creator_display_name: str | None,
        text: str,
        due_at: datetime,
        source_turn_id: str | None = None,
        max_per_turn: int = 3,
    ) -> Reminder:
        self._check(guild_id)
        text = " ".join(text.split())
        if not text or len(text) > TEXT_MAX_CHARS:
            raise ReminderError("BAD_TEXT", f"Nội dung nhắc phải từ 1 đến {TEXT_MAX_CHARS} ký tự.")
        if not creator_id or not channel_id:
            raise ReminderError("NO_SPEAKER", "Không xác định được người hẹn hoặc kênh.")
        now, due_at = self.clock(), _utc(due_at)
        if due_at < now + MIN_LEAD:
            raise ReminderError("TIME_IN_PAST", "Giờ hẹn đã qua hoặc quá gần. Hãy hỏi lại người dùng giờ nào.")
        if due_at > now + MAX_HORIZON:
            raise ReminderError("TIME_TOO_FAR", f"Chỉ hẹn được trong {MAX_HORIZON.days} ngày tới.")
        if source_turn_id:
            same_turn = self.store.by_turn(source_turn_id)
            for earlier in same_turn:
                if earlier.text == text and earlier.due_at == due_at:
                    return earlier
            if len(same_turn) >= max_per_turn:
                raise ReminderError("TOO_MANY_IN_TURN", f"Mỗi tin nhắn hẹn được tối đa {max_per_turn} lời nhắc.")
        if len(self.store.pending_for(guild_id, creator_id)) >= MAX_PENDING_PER_MEMBER:
            raise ReminderError("TOO_MANY", f"Người này đang có {MAX_PENDING_PER_MEMBER} lời nhắc chưa tới giờ. Huỷ bớt trước khi hẹn thêm.")
        reminder = Reminder(
            id=str(uuid4()), guild_id=guild_id, channel_id=channel_id, thread_id=thread_id, creator_id=creator_id,
            creator_display_name=creator_display_name, text=text, due_at=due_at, status="pending", source_turn_id=source_turn_id,
        )
        self.store.add(reminder)
        return reminder

    def list_for(self, guild_id: str, member_id: str) -> list[Reminder]:
        self._check(guild_id)
        now = self.clock()
        return [
            *self.store.pending_for(guild_id, member_id),
            *self.store.recent_missed_for(guild_id, member_id, now - MISSED_LISTED_FOR),
        ]

    def cancel(self, ref: str, *, guild_id: str, requester_id: str) -> Reminder:
        """Only the creator cancels. The reference is a full id or the first characters the list shows."""
        self._check(guild_id)
        ref = ref.strip().lower()
        if len(ref) < REF_MIN_CHARS or any(ch not in "0123456789abcdef-" for ch in ref):
            raise ReminderError("REMINDER_NOT_FOUND", "Không có lời nhắc nào mang mã đó.")
        found = self.store.find(guild_id, ref)
        if not found:
            raise ReminderError("REMINDER_NOT_FOUND", "Không có lời nhắc nào chưa gửi mang mã đó.")
        if len(found) > 1:
            raise ReminderError("REMINDER_AMBIGUOUS", "Mã này khớp nhiều lời nhắc. Gõ thêm ký tự.")
        reminder = found[0]
        if reminder.creator_id != requester_id:
            raise ReminderError("REMINDER_NOT_YOURS", "Chỉ người đặt lời nhắc mới huỷ được.")
        if not self.store.cancel_if_pending(reminder.id):
            raise ReminderError("REMINDER_NOT_CANCELLABLE", "Lời nhắc này đang được gửi nên không huỷ được nữa.")
        return reminder

    def claim_due(self, limit: int = CLAIM_LIMIT) -> list[DueReminder]:
        """What the bot should send now. Rows the policy at the top of this file refuses are
        settled here and never reach the bot."""
        if not self.enabled:
            raise ReminderError("REMINDERS_DISABLED", "Nhắc việc đang tắt.")
        now = self.clock()
        due: list[DueReminder] = []
        for reminder in self.store.claim_due(now, now - LEASE, max(1, min(limit, CLAIM_LIMIT))):
            late = now - reminder.due_at
            if not self.guild_allowed(reminder.guild_id):
                self.store.finish(reminder.id, "failed", now, error="guild_not_allowed")
            elif late >= MISSED_AFTER:
                self.store.finish(reminder.id, "missed", now, error=f"late_{int(late.total_seconds())}s")
            elif reminder.attempts > MAX_ATTEMPTS:
                self.store.finish(reminder.id, "failed", now, error="bot_lost_the_claim_repeatedly")
            else:
                due.append(DueReminder(reminder, max(0, int(late.total_seconds()))))
        return due

    def mark_sent(self, reminder_id: str, discord_message_id: str | None) -> None:
        if not self.enabled:
            raise ReminderError("REMINDERS_DISABLED", "Nhắc việc đang tắt.")
        self.store.finish(reminder_id, "sent", self.clock(), discord_message_id=discord_message_id)

    def mark_failed(self, reminder_id: str, error: str, *, retryable: bool) -> str:
        """Back to pending after a failure worth another try, else failed for good. The claim
        already counted this try in `attempts`."""
        if not self.enabled:
            raise ReminderError("REMINDERS_DISABLED", "Nhắc việc đang tắt.")
        now = self.clock()
        reminder = self.store.get(reminder_id)
        if reminder is None or reminder.status != "sending":
            raise ReminderError("REMINDER_NOT_FOUND", "Không có lời nhắc nào đang gửi mang mã đó.")
        if retryable and reminder.attempts < MAX_ATTEMPTS:
            self.store.finish(reminder_id, "pending", now, error=error[:500], retry_at=now + RETRY_DELAY)
            return "pending"
        self.store.finish(reminder_id, "failed", now, error=error[:500])
        return "failed"


def reminder_payload(reminder: Reminder, *, late_seconds: int | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": reminder.id, "short_id": reminder.short_id, "guild_id": reminder.guild_id,
        "channel_id": reminder.target_channel_id, "creator_id": reminder.creator_id,
        "text": reminder.text, "due_at": reminder.due_at.isoformat(), "status": reminder.status, "attempts": reminder.attempts,
    }
    if late_seconds is not None:
        payload["late_seconds"] = late_seconds
    return payload
