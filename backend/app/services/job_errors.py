from __future__ import annotations

import socket

from sqlalchemy.exc import OperationalError

BACKOFF_SECONDS = (10, 30, 90)


def classify_error(error: Exception) -> tuple[bool, str]:
    if isinstance(error, (TimeoutError, ConnectionError, socket.timeout, OperationalError)):
        return True, "TRANSIENT_DEPENDENCY"
    if getattr(error, "status_code", None) in {429, 502, 503, 504}:
        return True, f"HTTP_{error.status_code}"
    if isinstance(error, (FileNotFoundError, ValueError, KeyError)):
        return False, "NON_RETRYABLE_INPUT"
    return False, "UNEXPECTED_ERROR"


def retry_delay(attempts: int) -> int:
    return BACKOFF_SECONDS[min(max(attempts - 1, 0), len(BACKOFF_SECONDS) - 1)]
