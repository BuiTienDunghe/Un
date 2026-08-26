"""Passive-listening COUNTER — the measurement gate before the raw ledger.

memory_design.md §13.6 job 1 / invariant #8: the sổ gốc migration is written
only after a counter shows real passive flow. This module is that counter:
it counts messages in the explicitly listed channels and stores NO content —
one JSON line per message with ids, timestamps and flags only.

Rules carried over from the design:
- A thread counts toward its parent channel (§5.4 "thread theo kênh cha").
- DMs are never counted: a DM channel id is simply never in the listen list,
  and there is no wildcard.
- Counting must never break answering: every write failure is swallowed and
  logged (the same telemetry-never-worsens-an-outage rule as D4-lite).
- Bot-authored messages ARE counted, tagged `author_is_bot` — §9.3 (does the
  bot's own output belong in the sổ gốc?) is an open question this counter
  exists to answer with data.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Anchored to the repo root via __file__, NOT the working directory: the bot
# container's CWD is /app/backend, so a relative "data/..." would land outside
# the ./data mount and silently vanish on the next container recreation.
DEFAULT_COUNTS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "discord_listen" / "passive_counts.jsonl"
)


def parse_listen_channel_ids(raw: str) -> frozenset[str]:
    """Comma-separated channel ids from the env var; whitespace-tolerant."""
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def resolve_listened_channel(
    channel_id: str,
    parent_channel_id: str | None,
    listened: frozenset[str],
) -> str | None:
    """The channel this message counts toward, or None when not listened.

    A thread inherits its parent channel's listening decision so that opening
    a thread never silently escapes (or requires re-granting) the channel's
    configuration.
    """
    if channel_id in listened:
        return channel_id
    if parent_channel_id is not None and parent_channel_id in listened:
        return parent_channel_id
    return None


class PassiveListener:
    def __init__(
        self,
        counts_path: Path,
        listened_channel_ids: frozenset[str],
    ) -> None:
        self.counts_path = counts_path
        self.listened_channel_ids = listened_channel_ids
        self.recorded = 0

    @property
    def enabled(self) -> bool:
        return bool(self.listened_channel_ids)

    def record(
        self,
        *,
        guild_id: str | None,
        channel_id: str,
        parent_channel_id: str | None,
        author_id: str,
        author_is_bot: bool,
        is_mention: bool,
    ) -> bool:
        """Count one message. Returns True only when a line was written."""
        if not self.enabled or guild_id is None:
            return False
        target = resolve_listened_channel(
            channel_id, parent_channel_id, self.listened_channel_ids
        )
        if target is None:
            return False
        row = {
            "ts": datetime.now(UTC).isoformat(),
            "guild_id": guild_id,
            "channel_id": target,
            # The concrete thread the message was posted in, when it was one.
            "thread_id": channel_id if target != channel_id else None,
            "author_id": author_id,
            "author_is_bot": author_is_bot,
            "is_mention": is_mention,
        }
        try:
            self.counts_path.parent.mkdir(parents=True, exist_ok=True)
            with self.counts_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception(
                "passive counter write failed; answering continues unaffected"
            )
            return False
        self.recorded += 1
        return True
