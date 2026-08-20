"""P3-2 (bot control via docker compose) and P3-3 (dashboard timeseries)."""
from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import RequestLog
from app.services.bot_control_service import (
    BotControlService,
    BotControlError,
    BotTokenMissingError,
)

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


class FakeRun:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def make_service(tmp_path: Path, token: str | None = "DISCORD_TOKEN=abc123") -> BotControlService:
    env = tmp_path / ".env"
    env.write_text(f"{token}\n" if token else "OTHER=1\n", encoding="utf-8")
    return BotControlService(tmp_path, env_path=env)


def test_status_maps_compose_states(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return FakeRun(stdout='{"State": "running", "Name": "un-discord-bot-1"}\n')

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert service.status() == {"state": "running", "detail": "running"}
    assert calls[0][:4] == ["docker", "compose", "--profile", "discord"]

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeRun(stdout=""))
    assert service.status()["state"] == "stopped"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeRun(stdout='{"State": "exited"}'))
    assert service.status()["state"] == "stopped"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeRun(returncode=1, stderr="boom"))
    assert service.status() == {"state": "unknown", "detail": "boom"}

    def missing(*a, **k):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", missing)
    assert service.status()["state"] == "unknown"


def test_start_requires_a_token_and_uses_compose_up(tmp_path, monkeypatch):
    without_token = make_service(tmp_path, token=None)
    with pytest.raises(BotTokenMissingError):
        without_token.start()

    service = make_service(tmp_path)
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if "up" in args:
            return FakeRun()
        return FakeRun(stdout='{"State": "running"}')

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert service.start()["state"] == "running"
    assert ["docker", "compose", "--profile", "discord", "up", "-d", "discord-bot"] in calls

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeRun(returncode=1, stderr="build failed"))
    with pytest.raises(BotControlError):
        service.start()


def test_bot_endpoints_map_errors(client, mock_ollama, monkeypatch):
    class StubService:
        def status(self):
            return {"state": "stopped", "detail": None}

        def start(self):
            raise BotTokenMissingError("DISCORD_TOKEN trống")

        def stop(self):
            return {"state": "stopped", "detail": None}

    monkeypatch.setattr(client.app.state, "bot_control_service", StubService())
    assert client.get("/api/bot/status").json()["state"] == "stopped"
    started = client.post("/api/bot/start")
    assert started.status_code == 409 and started.json()["error_code"] == "DISCORD_TOKEN_MISSING"
    assert client.post("/api/bot/stop").status_code == 200


def test_timeseries_buckets_zero_fills_and_windows(client, mock_ollama):
    factory = create_session_factory(create_postgres_engine(str(URL)))
    now = datetime.now(UTC)
    sentinel = 987_601
    rows = [
        RequestLog(endpoint="/chat", latency_ms=sentinel + 0, status="ok", created_at=now),
        RequestLog(endpoint="/chat", latency_ms=sentinel + 100, status="ok", created_at=now),
        RequestLog(endpoint="/rag/chat", latency_ms=sentinel + 200, status="ok", created_at=now),
        RequestLog(endpoint="/memory/add", latency_ms=1, status="ok", created_at=now),  # not a question
        RequestLog(endpoint="/chat", latency_ms=5, status="error", error_code="MODEL_TIMEOUT", created_at=now),
        RequestLog(endpoint="/chat", latency_ms=9, status="ok", created_at=now - timedelta(days=10)),  # outside window
    ]
    with factory.begin() as session:
        for row in rows:
            session.add(row)
    try:
        payload = client.get("/api/dashboard/timeseries?days=3").json()
        days = payload["days"]
        assert len(days) == 3
        today = days[-1]
        assert today["date"] == datetime.now().astimezone().date().isoformat()
        # 3 ok questions + 1 error question today; the memory/add row is excluded.
        assert today["questions"] >= 4 and today["errors"] >= 1
        assert isinstance(today["p50_ms"], int) and isinstance(today["p95_ms"], int)
        # Zero-filled older days exist even with no rows.
        assert days[0]["questions"] >= 0 and days[0]["p50_ms"] is None or isinstance(days[0]["p50_ms"], int)
    finally:
        with factory.begin() as session:
            session.execute(delete(RequestLog).where(RequestLog.latency_ms >= sentinel))
            session.execute(delete(RequestLog).where(RequestLog.latency_ms.in_((1, 5, 9)), RequestLog.endpoint.in_(("/chat", "/memory/add"))))
