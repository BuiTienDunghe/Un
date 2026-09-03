"""Tier 3 — condensation of raw-ledger spans into discrete propositions.

memory_design.md §7. The shape this file implements, and why each piece is
the way it is:

- **A batch table with status and a lease**, not an integer cursor (§7.4).
  Coverage is marked per message (``condensation_batch_id``), so a message
  that arrives late simply carries NULL and joins the next batch.
- **Discrete propositions** carrying content + source_message_ids +
  speaker_id + said_at (§7.5) — the last two are what make §9.5's hardest
  case (deleting one person from a summary) a plain DELETE.
- **The model never supplies identity.** It sees numbered lines and returns
  line numbers; the server maps those back to real message ids and authors.
  Same trusted-binding lesson as the extractor envelope (§3.1, §7.5).
- **No model call inside a transaction** (invariant #2), and none of this
  runs on the answer path (invariant #7) — a background worker owns it.
- Propositions NEVER become facts: §9.1 blocks tier-3 auto-apply and §9.7
  shows the candidate queue cannot hold them. They are read context that a
  human can revoke from the dashboard.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.postgres.models import (
    DiscordChannelMessage,
    DiscordCondensationBatch,
    DiscordCondensationProposition,
)

logger = logging.getLogger(__name__)

CONDENSER_PROMPT_VERSION = "condense-v1"

_SYSTEM_PROMPT = """\
Bạn rút gọn một đoạn hội thoại Discord thành các MỆNH ĐỀ rời rạc, đáng nhớ.

Đầu vào là các dòng đánh số: `#<số> [ngày giờ] <tên>: <nội dung>`.
Dòng có dấu `[BOT]` là lời của trợ lý, KHÔNG phải lời thành viên.

Trả về DUY NHẤT một mảng JSON, mỗi phần tử:
{"content": "<mệnh đề>", "source": [<số dòng>, ...]}

Luật bắt buộc:
- Viết mệnh đề bằng CHÍNH NGÔN NGỮ của hội thoại (tiếng Việt thì viết tiếng Việt).
- Mỗi mệnh đề phải suy ra trực tiếp từ các dòng liệt kê trong "source"; không suy diễn, không thêm điều không có.
- Số dòng ĐẦU TIÊN trong "source" phải là dòng của THÀNH VIÊN (không có `[BOT]`) — đó là người nói chính của mệnh đề. Nếu một thông tin chỉ xuất hiện trong lời trợ lý thì BỎ QUA nó: lời trợ lý có thể sai, và không được ghi nhớ như sự thật.
- Có thể thêm dòng `[BOT]` vào "source" để làm ngữ cảnh, nhưng không bao giờ đặt ở vị trí đầu tiên.
- Nêu rõ AI nói/làm điều đó theo tên hiển thị trong dòng nguồn.
- Bỏ qua chào hỏi, đùa vui, tin không mang thông tin lâu dài. Không có gì đáng nhớ thì trả về [].
- Tối đa 12 mệnh đề. Không giải thích, không markdown, chỉ JSON.
"""


class CondenserBackend(Protocol):
    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class CondensationOutcome:
    status: str
    batch_id: int | None = None
    reason: str = ""
    proposition_count: int = 0


def _render_transcript(rows: list[DiscordChannelMessage]) -> str:
    """Bot lines stay in the transcript — §9.3 stores them precisely because a
    decision spoken half by a member and half by the assistant is incoherent
    without them — but they are marked, and a proposition may never be
    ATTRIBUTED to one (see the head-must-be-human rule)."""
    lines = []
    for index, row in enumerate(rows, start=1):
        stamp = row.sent_at.strftime("%d/%m %H:%M")
        speaker = " ".join((row.author_display_name or "?").split())
        marker = "[BOT] " if row.is_bot else ""
        text = " ".join((row.content or "").split())
        lines.append(f"#{index} [{stamp}] {marker}{speaker}: {text}")
    return "\n".join(lines)


def _parse_propositions(raw: str, line_count: int) -> list[dict[str, Any]]:
    """Defensive parse: strip fences, take the outermost array, and drop any
    entry whose source lines are not real. A malformed answer costs the batch,
    never the ledger."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    cleaned: list[dict[str, Any]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        content = str(entry.get("content") or "").strip()
        source = entry.get("source")
        if not content or not isinstance(source, list):
            continue
        indices: list[int] = []
        for value in source:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= line_count and number not in indices:
                indices.append(number)
        if not indices:
            continue
        cleaned.append({"content": content[:4000], "source": indices})
        if len(cleaned) >= 12:
            break
    return cleaned


class DiscordCondensationService:
    def __init__(
        self,
        sessions: sessionmaker,
        condenser: CondenserBackend | None = None,
        *,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.2,
        max_tokens: int = 4096,
        min_batch: int = 20,
        max_batch: int = 100,
        silence_gap_minutes: int = 10,
        lease_seconds: int = 300,
        max_attempts: int = 3,
        worker_id: str = "condenser",
    ) -> None:
        self.sessions = sessions
        self.condenser = condenser
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        # §13.5 replaced the 24h-per-channel floor (it produced ~9 near-empty
        # batches/day at 3 guilds) with an unprocessed-message threshold.
        self.min_batch = max(1, min_batch)
        self.max_batch = max(self.min_batch, max_batch)
        self.silence_gap = timedelta(minutes=max(0, silence_gap_minutes))
        self.lease_seconds = max(30, lease_seconds)
        self.max_attempts = max(1, max_attempts)
        self.worker_id = worker_id

    @property
    def enabled(self) -> bool:
        return self.condenser is not None

    # ── planning ─────────────────────────────────────────────────────────

    def ready_channels(self) -> list[tuple[str, str, int]]:
        """(guild_id, channel_id, unprocessed_count) at or above the floor."""
        with self.sessions() as database:
            rows = database.execute(
                select(
                    DiscordChannelMessage.guild_id,
                    DiscordChannelMessage.channel_id,
                    func.count().label("pending"),
                )
                .where(
                    DiscordChannelMessage.condensation_batch_id.is_(None),
                    DiscordChannelMessage.deleted_at.is_(None),
                    DiscordChannelMessage.content.is_not(None),
                )
                .group_by(
                    DiscordChannelMessage.guild_id,
                    DiscordChannelMessage.channel_id,
                )
                .having(func.count() >= self.min_batch)
            ).all()
        return [(row.guild_id, row.channel_id, row.pending) for row in rows]

    def _cut_point(self, rows: list[DiscordChannelMessage]) -> int:
        """Prefer the last silence gap >= the threshold (§7.4: a hard cut at
        message N splits a decision spoken across N-2..N+2). Falls back to the
        whole window, and never cuts below min_batch."""
        if len(rows) <= self.min_batch or not self.silence_gap:
            return len(rows)
        for index in range(len(rows) - 1, self.min_batch - 1, -1):
            if rows[index].sent_at - rows[index - 1].sent_at >= self.silence_gap:
                return index
        return len(rows)

    def plan_batch(self, guild_id: str, channel_id: str) -> CondensationOutcome:
        with self.sessions.begin() as database:
            rows = list(
                database.execute(
                    select(DiscordChannelMessage)
                    .where(
                        DiscordChannelMessage.guild_id == guild_id,
                        DiscordChannelMessage.channel_id == channel_id,
                        DiscordChannelMessage.condensation_batch_id.is_(None),
                        DiscordChannelMessage.deleted_at.is_(None),
                        DiscordChannelMessage.content.is_not(None),
                    )
                    .order_by(DiscordChannelMessage.sent_at, DiscordChannelMessage.id)
                    .limit(self.max_batch)
                ).scalars()
            )
            if len(rows) < self.min_batch:
                return CondensationOutcome("skipped", reason="below_floor")
            span = rows[: self._cut_point(rows)]
            batch = DiscordCondensationBatch(
                guild_id=guild_id,
                channel_id=channel_id,
                from_message_id=span[0].discord_message_id,
                to_message_id=span[-1].discord_message_id,
                from_sent_at=span[0].sent_at,
                to_sent_at=span[-1].sent_at,
                message_count=len(span),
                status="pending",
                max_attempts=self.max_attempts,
            )
            database.add(batch)
            try:
                database.flush()
            except IntegrityError:
                # Another planner already claimed this span.
                return CondensationOutcome("skipped", reason="duplicate_span")
            # Claim the messages immediately so a second planner cannot build
            # an overlapping span; a failed batch releases them again.
            database.execute(
                update(DiscordChannelMessage)
                .where(
                    DiscordChannelMessage.id.in_([row.id for row in span]),
                    DiscordChannelMessage.condensation_batch_id.is_(None),
                )
                .values(condensation_batch_id=batch.id)
            )
            return CondensationOutcome(
                "planned", batch_id=batch.id, reason=f"{len(span)} tin"
            )

    # ── running ──────────────────────────────────────────────────────────

    def _claim(self, batch_id: int) -> DiscordCondensationBatch | None:
        now = datetime.now(UTC)
        with self.sessions.begin() as database:
            batch = database.get(
                DiscordCondensationBatch, batch_id, with_for_update=True
            )
            if batch is None:
                return None
            claimable = batch.status == "pending" or (
                batch.status == "running"
                and batch.lease_expires_at is not None
                and batch.lease_expires_at < now
            )
            if not claimable:
                return None
            if batch.attempt_count >= batch.max_attempts:
                batch.status = "failed"
                batch.error_code = "attempts_exhausted"
                return None
            batch.status = "running"
            batch.worker_id = self.worker_id
            batch.attempt_count += 1
            batch.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            database.flush()
            database.expunge(batch)
            return batch

    def run_batch(self, batch_id: int) -> CondensationOutcome:
        if self.condenser is None:
            return CondensationOutcome(
                "skipped", batch_id=batch_id, reason="condenser_not_configured"
            )
        batch = self._claim(batch_id)
        if batch is None:
            return CondensationOutcome("skipped", batch_id=batch_id, reason="not_claimable")

        # Read the span, then close the transaction BEFORE the model call.
        with self.sessions() as database:
            rows = list(
                database.execute(
                    select(DiscordChannelMessage)
                    .where(DiscordChannelMessage.condensation_batch_id == batch_id)
                    .order_by(DiscordChannelMessage.sent_at, DiscordChannelMessage.id)
                ).scalars()
            )
        if not rows:
            return self._fail(batch_id, "empty_span", "batch covers no messages")

        transcript = _render_transcript(rows)
        try:
            raw = self.condenser.chat(
                self.model,
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": transcript},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        except Exception as error:  # transport, auth, timeout — all bounded
            logger.warning(
                "condensation batch=%s model call failed: %s",
                batch_id,
                type(error).__name__,
            )
            return self._fail(batch_id, "condenser_error", f"{type(error).__name__}")

        parsed = _parse_propositions(raw, len(rows))
        with self.sessions.begin() as database:
            live = database.get(
                DiscordCondensationBatch, batch_id, with_for_update=True
            )
            if live is None or live.status != "running" or live.worker_id != self.worker_id:
                return CondensationOutcome(
                    "skipped", batch_id=batch_id, reason="ownership_lost"
                )
            kept = 0
            for entry in parsed:
                sources = [rows[number - 1] for number in entry["source"]]
                head = sources[0]
                if head.is_bot:
                    # MEASURED 28/08 on real data: with only the prompt rule,
                    # 9/10 propositions were attributed to the assistant — and
                    # two of them crystallised its own hallucinations ("Ún là
                    # AI nên không có ngày sinh" came straight out of the
                    # echo-lock failure). §9.3 stores bot lines for coherence;
                    # this is where "extraction never eats them" is enforced.
                    logger.info(
                        "condensation batch=%s dropped a bot-attributed "
                        "proposition",
                        batch_id,
                    )
                    continue
                kept += 1
                database.add(
                    DiscordCondensationProposition(
                        batch_id=batch_id,
                        guild_id=live.guild_id,
                        channel_id=live.channel_id,
                        content=entry["content"],
                        source_message_ids=[
                            row.discord_message_id for row in sources
                        ],
                        # Identity comes from OUR rows, never from the model.
                        speaker_id=head.author_id,
                        speaker_display_name=head.author_display_name,
                        said_at=head.sent_at,
                    )
                )
            live.status = "completed"
            live.model_used = self.model
            live.prompt_version = CONDENSER_PROMPT_VERSION
            live.lease_expires_at = None
            live.error_code = None
            live.error_message = None
        return CondensationOutcome(
            "completed", batch_id=batch_id, proposition_count=kept
        )

    def _fail(self, batch_id: int, code: str, message: str) -> CondensationOutcome:
        """A failed batch RELEASES its messages: they must be condensable
        again, or a network blip would silently drop a span forever (§7.7)."""
        with self.sessions.begin() as database:
            batch = database.get(
                DiscordCondensationBatch, batch_id, with_for_update=True
            )
            if batch is None:
                return CondensationOutcome("skipped", reason="missing_batch")
            terminal = batch.attempt_count >= batch.max_attempts
            batch.status = "failed" if terminal else "pending"
            batch.error_code = code
            batch.error_message = message[:500]
            batch.lease_expires_at = None
            batch.worker_id = None
            if terminal:
                database.execute(
                    update(DiscordChannelMessage)
                    .where(DiscordChannelMessage.condensation_batch_id == batch_id)
                    .values(condensation_batch_id=None)
                )
        return CondensationOutcome(
            "failed" if terminal else "retrying", batch_id=batch_id, reason=code
        )

    def run_once(self) -> list[CondensationOutcome]:
        outcomes: list[CondensationOutcome] = []
        for guild_id, channel_id, _count in self.ready_channels():
            planned = self.plan_batch(guild_id, channel_id)
            outcomes.append(planned)
            if planned.batch_id is not None:
                outcomes.append(self.run_batch(planned.batch_id))
        # Pick up batches left pending by an earlier failure or a dead worker.
        with self.sessions() as database:
            stale_ids = list(
                database.scalars(
                    select(DiscordCondensationBatch.id)
                    .where(DiscordCondensationBatch.status == "pending")
                    .order_by(DiscordCondensationBatch.created_at)
                    .limit(10)
                )
            )
        for batch_id in stale_ids:
            outcomes.append(self.run_batch(batch_id))
        return outcomes

    # ── read path (§9.4) ─────────────────────────────────────────────────

    def recent_propositions(
        self,
        *,
        guild_id: str,
        channel_id: str | None = None,
        limit: int = 8,
    ) -> list[DiscordCondensationProposition]:
        """The tier-3 read the design demanded before tier 3 could ship: the
        newest propositions of this guild (optionally this channel), oldest
        first so the injected block reads as a timeline."""
        bounded = max(1, min(int(limit), 20))
        if not guild_id:
            return []
        conditions = [DiscordCondensationProposition.guild_id == guild_id]
        if channel_id:
            conditions.append(
                DiscordCondensationProposition.channel_id == channel_id
            )
        with self.sessions() as database:
            rows = list(
                database.execute(
                    select(DiscordCondensationProposition)
                    .where(*conditions)
                    .order_by(
                        DiscordCondensationProposition.said_at.desc(),
                        DiscordCondensationProposition.id.desc(),
                    )
                    .limit(bounded)
                ).scalars()
            )
        rows.reverse()
        return rows

    # ── operator surface (§9.7 / invariant #6) ───────────────────────────

    def mark_stale(self, *, discord_message_id: str) -> int:
        """An edited message invalidates the batch that covered it (§7.4):
        the summary quotes text that no longer exists."""
        with self.sessions.begin() as database:
            batch_id = database.scalar(
                select(DiscordChannelMessage.condensation_batch_id).where(
                    DiscordChannelMessage.discord_message_id == discord_message_id
                )
            )
            if batch_id is None:
                return 0
            batch = database.get(DiscordCondensationBatch, batch_id)
            if batch is None or batch.status in {"stale", "deleted"}:
                return 0
            batch.status = "stale"
            return batch_id

    def list_batches(self, *, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        """Dashboard view: newest batches with their propositions inline."""
        bounded_limit = max(1, min(int(limit), 100))
        bounded_offset = max(0, int(offset))
        with self.sessions() as database:
            batches = list(
                database.execute(
                    select(DiscordCondensationBatch)
                    .order_by(DiscordCondensationBatch.created_at.desc())
                    .offset(bounded_offset)
                    .limit(bounded_limit)
                ).scalars()
            )
            if not batches:
                return []
            propositions = list(
                database.execute(
                    select(DiscordCondensationProposition)
                    .where(
                        DiscordCondensationProposition.batch_id.in_(
                            [batch.id for batch in batches]
                        )
                    )
                    .order_by(DiscordCondensationProposition.said_at)
                ).scalars()
            )
            by_batch: dict[int, list[dict[str, Any]]] = {}
            for row in propositions:
                by_batch.setdefault(row.batch_id, []).append(
                    {
                        "content": row.content,
                        "speaker": row.speaker_display_name or row.speaker_id,
                        "speaker_id": row.speaker_id,
                        "said_at": row.said_at.isoformat(),
                        "source_message_ids": list(row.source_message_ids),
                    }
                )
            return [
                {
                    "batch_id": batch.id,
                    "guild_id": batch.guild_id,
                    "channel_id": batch.channel_id,
                    "status": batch.status,
                    "message_count": batch.message_count,
                    "from_sent_at": batch.from_sent_at.isoformat(),
                    "to_sent_at": batch.to_sent_at.isoformat(),
                    "model_used": batch.model_used,
                    "error_code": batch.error_code,
                    "propositions": by_batch.get(batch.id, []),
                }
                for batch in batches
            ]

    def delete_batch(self, batch_id: int) -> bool:
        """Revoke a summary: propositions cascade, and the messages become
        condensable again so a regenerate can replace it."""
        with self.sessions.begin() as database:
            batch = database.get(DiscordCondensationBatch, batch_id)
            if batch is None:
                return False
            database.execute(
                update(DiscordChannelMessage)
                .where(DiscordChannelMessage.condensation_batch_id == batch_id)
                .values(condensation_batch_id=None)
            )
            database.delete(batch)
        return True

    def forget_member(self, *, guild_id: str, speaker_id: str) -> int:
        """§9.5 at proposition granularity — the reason speaker_id is a
        column: one person leaves a summary without destroying the span."""
        with self.sessions.begin() as database:
            result = database.execute(
                DiscordCondensationProposition.__table__.delete().where(
                    DiscordCondensationProposition.guild_id == guild_id,
                    DiscordCondensationProposition.speaker_id == speaker_id,
                )
            )
            return int(result.rowcount or 0)
