"""What a running Discord turn is doing, for the bot to show while it waits (ticket 20 #4, P-a).

The bot's execute call blocks until the answer exists; meanwhile it can ask
GET /api/discord/sessions/turns/{id}/progress, which reads this store. The API runs one
uvicorn process (run-local-ai-core.bat), so a dict behind a lock is enough: the turn's
executing thread writes, the progress endpoint reads from another.

An entry holds a kind of work and counts, never an argument, a result or an answer (the
agent's on_step events are built that way). It goes when its turn ends, and any entry older
than MAX_AGE_SECONDS goes on the next write or read, so a turn that died without ending
cannot keep one forever.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic

# Twice the agent's 90 s turn budget plus the bot's 180 s wait: no live turn is older.
MAX_AGE_SECONDS = 600.0


class TurnProgress:
    def __init__(self, clock: Callable[[], float] = monotonic, max_age_seconds: float = MAX_AGE_SECONDS) -> None:
        self._entries: dict[str, dict[str, object]] = {}
        self._lock = threading.Lock()
        self._clock = clock
        self._max_age = max_age_seconds

    def recorder(self, turn_id: str) -> Callable[[dict[str, object]], None]:
        """The agent's on_step for one turn."""
        return lambda event: self.record(turn_id, event)

    def record(self, turn_id: str, event: dict[str, object]) -> None:
        with self._lock:
            self._prune()
            entry = self._entries.setdefault(turn_id, {"steps": 0, "label": None})
            entry["steps"] = int(entry["steps"]) + 1
            entry["kind"] = event.get("kind")
            entry["round"] = event.get("round")
            if event.get("label"):
                entry["label"] = event["label"]
            entry["updated_at"] = datetime.now(UTC).isoformat()
            entry["_at"] = self._clock()

    def get(self, turn_id: str) -> dict[str, object] | None:
        with self._lock:
            self._prune()
            entry = self._entries.get(turn_id)
            return None if entry is None else {key: value for key, value in entry.items() if not key.startswith("_")}

    def finish(self, turn_id: str) -> None:
        with self._lock:
            self._entries.pop(turn_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _prune(self) -> None:
        cutoff = self._clock() - self._max_age
        for turn_id in [key for key, entry in self._entries.items() if float(entry["_at"]) < cutoff]:
            del self._entries[turn_id]
