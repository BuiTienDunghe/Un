"""Approvals (ticket 46): a tool call that waits for the member it belongs to. Nothing runs before they say yes.

Rules the service keeps, whatever store sits under it:
- Off unless DISCORD_APPROVALS_ENABLED; every call then fails with APPROVALS_DISABLED and nothing runs.
- The member is read from the turn the model's call was made in (never from the model), and only
  that member, in that guild, can approve or deny: anyone else is refused and the row is not touched.
- The call is kept as the JSON the model wrote and shown whole (ARGUMENTS_MAX_CHARS: a longer one is
  refused, because a person must not approve what they were not shown). What runs is that same JSON.
- It waits TTL. Past it, approving fails and the row is `expired`; the tool never runs. The check is
  made by the database at the moment of approving, so nothing has to sweep for it to hold; expire_due
  only tidies the status, and runs whenever the service is used.
- Approving moves the row pending -> running in one conditional update, so two clicks run the tool at
  most once. A process that dies after that leaves `running`; after RUNNING_LEASE it is marked `failed`
  (`interrupted`) and is never run again: the tool may or may not have run, and a repeat could do it twice.
- Denying, expiring, or a guild that left the allowlist: the tool does not run.
- A row holds the member's words and id: the FK to its turn (CASCADE) and forget_member remove it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.postgres.models import DiscordApproval, DiscordConversationSession, DiscordSessionTurn
from app.services.agent_service import TOOL_FAILED, ToolOutput
from app.services.approvals import ApprovalError, ApprovalNotice

TTL = timedelta(minutes=10)
RUNNING_LEASE = timedelta(minutes=10)
MAX_PENDING_PER_MEMBER = 5
ARGUMENTS_MAX_CHARS = 1500
SHORT_ID_CHARS = 8


@dataclass(frozen=True)
class Approval:
    id: str
    guild_id: str
    channel_id: str
    thread_id: str | None
    requester_id: str
    tool_name: str
    arguments: str
    status: str
    expires_at: datetime
    source_turn_id: str | None = None

    @property
    def short_id(self) -> str:
        return self.id[:SHORT_ID_CHARS]


@dataclass(frozen=True)
class TurnIdentity:
    """Where a turn happened and who spoke, read from the turn and never from the model."""

    guild_id: str
    channel_id: str
    thread_id: str | None
    author_id: str


@dataclass(frozen=True)
class Decision:
    status: str  # done | failed | denied
    tool_name: str
    text: str | None = None  # what the tool returned, for the bot to word; None when it did not run
    code: str | None = None  # the tool's error code, if it failed


class ApprovalStore(Protocol):
    def add(self, approval: Approval) -> None: ...

    def get(self, approval_id: str) -> Approval | None: ...

    def by_turn(self, turn_id: str) -> list[Approval]: ...

    def pending_for(self, guild_id: str, requester_id: str, now: datetime) -> list[Approval]: ...

    def move(self, approval_id: str, from_status: str, to_status: str, now: datetime, *, before_expiry: bool = False, result_code: str | None = None, stamp: bool = True) -> bool:
        """Compare-and-set: True only for the caller whose update changed the row."""
        ...

    def expire_due(self, now: datetime, running_cutoff: datetime) -> int: ...


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _row(row: DiscordApproval) -> Approval:
    return Approval(
        id=str(row.id), guild_id=row.guild_id, channel_id=row.channel_id, thread_id=row.thread_id, requester_id=row.requester_id,
        tool_name=row.tool_name, arguments=row.arguments, status=row.status, expires_at=_utc(row.expires_at),
        source_turn_id=str(row.source_turn_id) if row.source_turn_id else None,
    )


class SqlApprovalStore:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def add(self, approval: Approval) -> None:
        with self.sessions.begin() as database:
            database.add(DiscordApproval(
                id=UUID(approval.id), guild_id=approval.guild_id, channel_id=approval.channel_id, thread_id=approval.thread_id,
                requester_id=approval.requester_id, tool_name=approval.tool_name, arguments=approval.arguments,
                status="pending", expires_at=approval.expires_at,
                source_turn_id=UUID(approval.source_turn_id) if approval.source_turn_id else None,
            ))

    def _select(self, *conditions: Any) -> list[Approval]:
        with self.sessions() as database:
            return [_row(row) for row in database.scalars(select(DiscordApproval).where(*conditions).order_by(DiscordApproval.created_at, DiscordApproval.id))]

    def get(self, approval_id: str) -> Approval | None:
        found = self._select(DiscordApproval.id == UUID(approval_id))
        return found[0] if found else None

    def by_turn(self, turn_id: str) -> list[Approval]:
        return self._select(DiscordApproval.source_turn_id == UUID(turn_id))

    def pending_for(self, guild_id: str, requester_id: str, now: datetime) -> list[Approval]:
        return self._select(
            DiscordApproval.guild_id == guild_id, DiscordApproval.requester_id == requester_id,
            DiscordApproval.status == "pending", DiscordApproval.expires_at > now,
        )

    def move(self, approval_id: str, from_status: str, to_status: str, now: datetime, *, before_expiry: bool = False, result_code: str | None = None, stamp: bool = True) -> bool:
        conditions = [DiscordApproval.id == UUID(approval_id), DiscordApproval.status == from_status]
        if before_expiry:
            conditions.append(DiscordApproval.expires_at > now)
        values: dict[str, Any] = {"status": to_status}
        if stamp:
            values["decided_at"] = now
        if result_code is not None:
            values["result_code"] = result_code
        with self.sessions.begin() as database:
            return database.execute(update(DiscordApproval).where(*conditions).values(**values)).rowcount == 1

    def expire_due(self, now: datetime, running_cutoff: datetime) -> int:
        with self.sessions.begin() as database:
            expired = database.execute(
                update(DiscordApproval).where(DiscordApproval.status == "pending", DiscordApproval.expires_at <= now)
                .values(status="expired", decided_at=now)
            ).rowcount
            interrupted = database.execute(
                update(DiscordApproval).where(DiscordApproval.status == "running", DiscordApproval.decided_at < running_cutoff)
                .values(status="failed", result_code="interrupted")
            ).rowcount
            return expired + interrupted


def load_turn_identity(sessions: sessionmaker) -> Callable[[str], TurnIdentity | None]:
    def load(turn_id: str) -> TurnIdentity | None:
        try:
            turn_uuid = UUID(turn_id)
        except ValueError:
            return None
        with sessions() as database:
            turn = database.get(DiscordSessionTurn, turn_uuid)
            session = database.get(DiscordConversationSession, turn.session_id) if turn is not None else None
            if turn is None or session is None or not turn.author_id:
                return None
            return TurnIdentity(guild_id=session.guild_id, channel_id=session.channel_id, thread_id=session.thread_id, author_id=turn.author_id)

    return load


def _canonical(arguments: object) -> str:
    """The call's arguments as the one JSON text that is shown, kept and run."""
    if not isinstance(arguments, dict):
        raise ApprovalError("BAD_ARGUMENTS", "Tham số của công cụ phải là một đối tượng JSON.")
    try:
        text = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ApprovalError("BAD_ARGUMENTS", "Tham số của công cụ không viết được thành JSON.") from error
    if len(text) > ARGUMENTS_MAX_CHARS:
        raise ApprovalError("ARGUMENTS_TOO_LONG", f"Tham số dài quá {ARGUMENTS_MAX_CHARS} ký tự nên không đưa cho người dùng duyệt được. Rút gọn rồi gọi lại, hoặc nói thật là chưa làm được.")
    return text


class ApprovalService:
    """Implements app.services.approvals.ApprovalGate for Discord turns, and decides what members answer."""

    def __init__(
        self,
        store: ApprovalStore,
        *,
        enabled: bool,
        guild_allowed: Callable[[str | None], bool],
        load_turn: Callable[[str], TurnIdentity | None],
        run_approved: Callable[[str, dict[str, Any], dict[str, Any] | None], ToolOutput],
        ttl: timedelta = TTL,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.enabled = enabled
        self.guild_allowed = guild_allowed
        self.load_turn = load_turn
        self.run_approved = run_approved
        self.ttl = ttl
        self.clock = clock

    def _check_enabled(self) -> None:
        if not self.enabled:
            raise ApprovalError("APPROVALS_DISABLED", "Xin duyệt đang tắt.")

    def expire_due(self) -> int:
        now = self.clock()
        return self.store.expire_due(now, now - RUNNING_LEASE)

    # ---- the agent's side: keep the call ----

    def request(self, tool_name: str, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ApprovalNotice:
        self._check_enabled()
        turn_id = (tool_context or {}).get("turn_id")
        if not turn_id:
            raise ApprovalError("NOT_A_DISCORD_TURN", f"{tool_name} cần người dùng duyệt, mà chỉ duyệt được trong cuộc trò chuyện Discord. Nói rõ là ở đây chưa làm được.")
        identity = self.load_turn(str(turn_id))
        if identity is None:
            raise ApprovalError("NO_SPEAKER", "Không xác định được người đang nói nên không xin duyệt được. Nói thật với người dùng là chưa làm.")
        if not self.guild_allowed(identity.guild_id):
            raise ApprovalError("GUILD_NOT_ALLOWED", "Xin duyệt chưa bật ở server này.")
        shown = _canonical(arguments)
        now = self.clock()
        self.expire_due()
        for earlier in self.store.by_turn(str(turn_id)):
            # A turn the worker runs again must not ask twice for the same thing.
            if earlier.tool_name == tool_name and earlier.arguments == shown and earlier.status == "pending" and earlier.expires_at > now:
                return self._notice(earlier)
        if len(self.store.pending_for(identity.guild_id, identity.author_id, now)) >= MAX_PENDING_PER_MEMBER:
            raise ApprovalError("TOO_MANY_PENDING", f"Người này đang có {MAX_PENDING_PER_MEMBER} việc chờ duyệt. Nói họ duyệt hoặc từ chối bớt rồi hãy nhờ thêm.")
        approval = Approval(
            id=str(uuid4()), guild_id=identity.guild_id, channel_id=identity.channel_id, thread_id=identity.thread_id,
            requester_id=identity.author_id, tool_name=tool_name, arguments=shown, status="pending",
            expires_at=now + self.ttl, source_turn_id=str(turn_id),
        )
        self.store.add(approval)
        return self._notice(approval)

    def _notice(self, approval: Approval) -> ApprovalNotice:
        # An "@" in the model's words must not read as a ping when the bot posts this.
        shown = approval.arguments.replace("@", "@​")
        minutes = max(1, round(self.ttl.total_seconds() / 60))
        return ApprovalNotice(approval.id, (
            f"Mình cần bạn duyệt trước khi làm việc này.\n"
            f"Công cụ: {approval.tool_name}\n"
            f"Nội dung: {shown}\n"
            f"Mã duyệt: {approval.short_id}\n"
            f"Chỉ bạn duyệt hoặc từ chối được: bấm nút bên dưới, hoặc dùng /approvals. Sau {minutes} phút không ai duyệt thì việc này bị huỷ và không chạy."
        ))

    # ---- the member's side: approve or deny ----

    def list_for(self, guild_id: str, member_id: str) -> list[Approval]:
        self._check_enabled()
        self.expire_due()
        return self.store.pending_for(guild_id, member_id, self.clock())

    def decide(self, approval_id: str, *, guild_id: str, actor_id: str, approve: bool) -> Decision:
        self._check_enabled()
        try:
            key = str(UUID(approval_id))
        except ValueError as error:
            raise ApprovalError("APPROVAL_NOT_FOUND", "Không có việc chờ duyệt nào mang mã đó.") from error
        self.expire_due()
        row = self.store.get(key)
        if row is None or row.guild_id != guild_id:
            raise ApprovalError("APPROVAL_NOT_FOUND", "Không có việc chờ duyệt nào mang mã đó.")
        if row.requester_id != actor_id:
            raise ApprovalError("APPROVAL_NOT_YOURS", "Chỉ người nhờ việc này mới duyệt hoặc từ chối được.")
        now = self.clock()
        if row.status == "pending" and row.expires_at <= now:
            self.store.move(row.id, "pending", "expired", now)
            raise ApprovalError("APPROVAL_EXPIRED", "Việc này đã quá hạn duyệt nên bị huỷ, không chạy.")
        if row.status == "expired":
            raise ApprovalError("APPROVAL_EXPIRED", "Việc này đã quá hạn duyệt nên bị huỷ, không chạy.")
        if row.status != "pending":
            raise ApprovalError("APPROVAL_NOT_PENDING", "Việc này đã được xử lý rồi.")
        if not self.guild_allowed(row.guild_id):
            raise ApprovalError("GUILD_NOT_ALLOWED", "Xin duyệt chưa bật ở server này.")
        if not approve:
            if not self.store.move(row.id, "pending", "denied", now):
                raise ApprovalError("APPROVAL_NOT_PENDING", "Việc này đã được xử lý rồi.")
            return Decision("denied", row.tool_name)
        if not self.store.move(row.id, "pending", "running", now, before_expiry=True):
            # Lost to another click, or the time ran out between the read and the update.
            self.store.expire_due(now, now - RUNNING_LEASE)
            again = self.store.get(row.id)
            if again is not None and again.status == "expired":
                raise ApprovalError("APPROVAL_EXPIRED", "Việc này đã quá hạn duyệt nên bị huỷ, không chạy.")
            raise ApprovalError("APPROVAL_NOT_PENDING", "Việc này đã được xử lý rồi.")
        return self._run(row)

    def _run(self, row: Approval) -> Decision:
        context: dict[str, Any] = {"guild_id": row.guild_id}
        if row.source_turn_id:
            context["turn_id"] = row.source_turn_id
        try:
            text, code, _ = self.run_approved(row.tool_name, json.loads(row.arguments), context)
        except Exception as error:
            logger.warning("approved {} failed: {}", row.tool_name, type(error).__name__)
            text, code = None, TOOL_FAILED
        status = "done" if code is None else "failed"
        try:
            if not self.store.move(row.id, "running", status, self.clock(), result_code=code, stamp=False):
                # The tool outlived RUNNING_LEASE and expire_due already wrote `failed` (interrupted). The
                # member still gets what came back; the row cannot say more than that it was cut off.
                logger.warning("approval {} finished as {} but its row was no longer running", row.short_id, status)
        except Exception as error:
            # The tool already ran and must not run again; the row stays `running` and is marked
            # `failed` (interrupted) after RUNNING_LEASE. The member still gets what came back.
            logger.warning("approval {} could not be closed: {}", row.short_id, type(error).__name__)
        return Decision(status, row.tool_name, text, code)


def approval_payload(approval: Approval) -> dict[str, object]:
    return {
        "id": approval.id, "short_id": approval.short_id, "guild_id": approval.guild_id,
        "channel_id": approval.thread_id or approval.channel_id, "requester_id": approval.requester_id,
        "tool_name": approval.tool_name, "arguments": approval.arguments,
        "expires_at": approval.expires_at.isoformat(), "status": approval.status, "source_turn_id": approval.source_turn_id,
    }
