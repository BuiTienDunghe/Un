"""A wall-clock deadline for the model calls inside one agent turn (ticket 16).

The agent sets it around each call; the provider clients read it. A request waits
at most what is left, a retry is not started once the deadline has passed, and no
back-off sleep runs past it. Without it each call could wait 120 s three times over
(chat_timeout x (retry_count + 1)), so one agent answer could take ~24 minutes.

A ContextVar for usage.py's reason: router.chat and chat_tools are reached through
wrappers and test doubles (agent_eval's UsageRecordingRouter among them) that would
all have to grow a parameter to carry one number. Unset — every caller outside an
agent turn — the clients behave exactly as before.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_DEADLINE: ContextVar[float | None] = ContextVar("llm_call_deadline", default=None)


class ModelCallTimeoutError(Exception):
    """Base of every provider's timeout error: lets the agent tell "out of time" from "broken"."""


@contextmanager
def call_deadline(at: float | None) -> Iterator[None]:
    """Bound the model calls made inside this block by `at`, a time.monotonic() value."""
    token = _DEADLINE.set(at)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def call_within(seconds: float):
    """call_deadline `seconds` from now, on this module's clock."""
    return call_deadline(time.monotonic() + max(0.0, seconds))


def _left() -> float | None:
    at = _DEADLINE.get()
    return None if at is None else at - time.monotonic()


def request_timeout(default: float) -> float | None:
    """The timeout for the next request: the client's own, or what is left if that is
    shorter. None when the deadline has already passed — the caller must not send."""
    left = _left()
    if left is None:
        return default
    return min(default, left) if left > 0 else None


def spent() -> bool:
    left = _left()
    return left is not None and left <= 0


def can_wait(seconds: float) -> bool:
    """Whether a back-off of `seconds` still ends before the deadline."""
    left = _left()
    return left is None or left > seconds
