"""/health says "degraded" within seconds when a dependency never answers (ticket 01, M1a).

Measured 27/10 with the stack off: the Postgres probe, with no connect timeout,
took minutes on an empty port and never returned on one that accepts and stays
silent; the Redis PING, with no socket timeout, never returned on a silent one;
Qdrant's retrying healthcheck took 8 s closed and 32 s silent. A listening socket
that is never read from is that silent port — no stack needed.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.postgres.database import create_postgres_engine, create_session_factory
from app.services.operational_service import OperationalService


@pytest.fixture
def silent_port():
    """A port whose kernel completes the TCP handshake and then nothing ever answers."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(16)
    yield server.getsockname()[1]
    server.close()


class Answers:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok

    def healthcheck(self) -> bool:
        return self.ok


class HungQdrant:
    """A healthcheck that blocks until released, counting how often it was started."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls = 0

    def healthcheck(self) -> bool:
        self.calls += 1
        self.release.wait(30)
        return True


def health_within(service: OperationalService, seconds: float) -> dict:
    """service.health(), failing — rather than hanging the suite — if it outlives `seconds`."""
    box: dict = {}
    worker = threading.Thread(target=lambda: box.update(result=service.health()), daemon=True)
    worker.start()
    worker.join(seconds)
    assert not worker.is_alive(), f"/health was still probing after {seconds} s"
    return box["result"]


def test_silent_postgres_and_redis_read_as_degraded_within_seconds(silent_port):
    sessions = create_session_factory(create_postgres_engine(f"postgresql+psycopg://probe:probe@127.0.0.1:{silent_port}/probe"))
    service = OperationalService(sessions, f"redis://127.0.0.1:{silent_port}/0", "test", Answers(), Answers(), probe_timeout_seconds=1)

    started = time.monotonic()
    health = health_within(service, 15)

    assert health["status"] == "degraded"
    assert health["postgres"] == "unavailable"
    assert health["redis"] == "unavailable"
    # The outbox count goes through the API's own engine, which has no connect
    # timeout: asked with Postgres down, it would be the second hang.
    assert health["outbox_dispatcher"] == "unavailable"
    # libpq's 2 s floor plus Redis's 1 s, with room for a slow CI machine.
    assert time.monotonic() - started < 10


def test_a_hung_qdrant_reads_unavailable_and_is_not_probed_again_while_hung(silent_port):
    # SQLite has no network to hang on, so Postgres answers at once here.
    sessions = sessionmaker(bind=create_engine("sqlite://"))
    qdrant = HungQdrant()
    service = OperationalService(sessions, f"redis://127.0.0.1:{silent_port}/0", "test", qdrant, Answers(), probe_timeout_seconds=0.5)
    try:
        first = health_within(service, 5)
        second = health_within(service, 5)

        assert first["qdrant"] == second["qdrant"] == "unavailable"
        assert first["postgres"] == "ok"
        # The probe still running from the first call is the second call's answer.
        assert qdrant.calls == 1
        # Abandoned, it must not hold up the process's exit.
        assert all(thread.daemon for thread in threading.enumerate() if thread.name == "health-qdrant")

        qdrant.release.set()
        assert health_within(service, 5)["qdrant"] == "ok"
    finally:
        qdrant.release.set()
