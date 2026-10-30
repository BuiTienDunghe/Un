"""Decided's suggestions for heard messages, and a person's review of them (ticket 36).

The trial's rule: nothing reaches a memory on the model's word. Every suggestion waits here for a
person, except an "ignore" the model is sure of, which is recorded and left out of the queue. The
agreement between model and person, per label, is the number that will say whether a threshold
can ever be trusted. A label holds no text: reads join the ledger, so a deleted message vanishes.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import sessionmaker

from app.postgres.models import DiscordChannelMessage, DiscordMessageLabel

LABELS = ("fact", "decision", "joke", "ignore")
SURE_IGNORE = 0.8
BATCH = 20
MIN_TEXT_CHARS = 2
MEMORY_LINE_CHARS = 400
# What a person approved is that text: an edit made afterwards needs reviewing again.
_UNCHANGED = or_(DiscordChannelMessage.edited_at.is_(None), DiscordChannelMessage.edited_at <= DiscordMessageLabel.reviewed_at)


class LabelNotFoundError(LookupError):
    pass


class MessageLabelService:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def unlabelled(self, limit: int = BATCH) -> list[tuple[str, str, str]]:
        """(message id, guild, text) of people's messages no label covers yet, oldest first."""
        with self.sessions() as database:
            rows = database.execute(
                select(DiscordChannelMessage.discord_message_id, DiscordChannelMessage.guild_id, DiscordChannelMessage.content)
                .outerjoin(DiscordMessageLabel, DiscordMessageLabel.discord_message_id == DiscordChannelMessage.discord_message_id)
                .where(
                    DiscordMessageLabel.id.is_(None), DiscordChannelMessage.is_bot.is_(False),
                    DiscordChannelMessage.deleted_at.is_(None), DiscordChannelMessage.content.is_not(None),
                )
                .order_by(DiscordChannelMessage.sent_at).limit(limit)
            ).all()
        return [(str(row[0]), str(row[1]), str(row[2])) for row in rows]

    def record(self, message_id: str, guild_id: str, result: dict[str, Any]) -> None:
        label, confidence = str(result["label"]), float(result["confidence"])
        if label not in LABELS:
            raise ValueError(f"unknown label {label!r}")
        skipped = label == "ignore" and confidence >= SURE_IGNORE
        with self.sessions.begin() as database:
            database.add(DiscordMessageLabel(
                discord_message_id=message_id, guild_id=guild_id, suggested_label=label, confidence=confidence,
                stable=bool(result.get("stable")), probs=dict(result.get("probs") or {}), model=str(result.get("model") or "decided"),
                status="skipped" if skipped else "pending",
            ))

    def _rows(self, *conditions: Any, limit: int, offset: int = 0) -> list[dict[str, object]]:
        with self.sessions() as database:
            rows = database.execute(
                select(DiscordMessageLabel, DiscordChannelMessage)
                .join(DiscordChannelMessage, DiscordChannelMessage.discord_message_id == DiscordMessageLabel.discord_message_id)
                .where(DiscordChannelMessage.deleted_at.is_(None), DiscordChannelMessage.content.is_not(None), *conditions)
                .order_by(DiscordChannelMessage.sent_at.desc()).limit(limit).offset(offset)
            ).all()
            return [
                {
                    "id": str(label.id), "text": message.content, "author": message.author_display_name, "author_id": message.author_id,
                    "guild_id": label.guild_id, "sent_at": message.sent_at.isoformat(), "suggested_label": label.suggested_label,
                    "final_label": label.final_label, "confidence": label.confidence, "stable": label.stable, "status": label.status,
                }
                for label, message in rows
            ]

    def pending(self, limit: int = 50, offset: int = 0) -> list[dict[str, object]]:
        edited = DiscordMessageLabel.status == "approved", ~_UNCHANGED
        rows = self._rows(or_(DiscordMessageLabel.status == "pending", and_(*edited)), limit=limit, offset=offset)
        return [{**row, "status": "pending"} for row in rows]

    def approved(self, guild_id: str | None = None, labels: tuple[str, ...] = LABELS, limit: int = 50) -> list[dict[str, object]]:
        conditions = [DiscordMessageLabel.status == "approved", DiscordMessageLabel.final_label.in_(labels), _UNCHANGED]
        if guild_id is not None:
            conditions.append(DiscordMessageLabel.guild_id == guild_id)
        return self._rows(*conditions, limit=limit)

    def review(self, label_id: UUID, *, status: str, final_label: str | None = None) -> dict[str, object]:
        """Approve (optionally correcting the label), reject, or put back to pending."""
        if final_label is not None and final_label not in LABELS:
            raise ValueError(f"unknown label {final_label!r}")
        with self.sessions.begin() as database:
            label = database.get(DiscordMessageLabel, label_id)
            if label is None:
                raise LabelNotFoundError(str(label_id))
            label.status = status
            label.final_label = (final_label or label.suggested_label) if status == "approved" else None
            label.reviewed_at = datetime.now(UTC) if status != "pending" else None
            return {"id": str(label.id), "status": label.status, "final_label": label.final_label}

    def stats(self) -> dict[str, object]:
        """Counts, and how often the person agreed with the model, per suggested label."""
        with self.sessions() as database:
            rows = database.execute(select(DiscordMessageLabel.suggested_label, DiscordMessageLabel.status, DiscordMessageLabel.final_label)).all()
        status = Counter(row[1] for row in rows)
        agreement: dict[str, dict[str, int]] = {}
        for suggested, state, final in rows:
            if state in ("approved", "rejected"):
                entry = agreement.setdefault(suggested, {"reviewed": 0, "agreed": 0})
                entry["reviewed"] += 1
                entry["agreed"] += int(state == "approved" and final == suggested)
        return {"status": dict(status), "agreement": agreement}

    def memory_lines(self, guild_id: str, limit: int = 30) -> list[str]:
        """Approved facts and decisions, for a turn's memory block. Jokes never go here."""
        lines = []
        for row in self.approved(guild_id, ("fact", "decision"), limit):
            about = f"về author_id={row['author_id']}" if row["final_label"] == "fact" else "quyết định chung"
            # On one line and clipped: a message cannot forge a second approved line in the block.
            text = " ".join(str(row["text"]).split())[:MEMORY_LINE_CHARS]
            lines.append(f"- [đã duyệt | {about}] {text}")
        return lines
