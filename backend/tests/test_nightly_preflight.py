"""nightly_eval's exit 93: a dependency down before the lab API starts (ticket 01, M1a).

From 17/09 to 27/10, 51 nights ended in exit 97 — "no /health in 180 s" — and
the evidence beside them showed the same thing every time: Docker Desktop not
running (30 nights) or running with the stack off (18). What is locked here:
that the nightly asks the three dependencies itself, bounded, before starting
anything; that it tells those two Docker states apart from what `docker compose
ps` really printed on those nights; and that it names a foreign container
holding the Postgres port. No stack needed: docker is faked, the ports are local.
"""
from __future__ import annotations

import socket
import subprocess
import time

import pytest

from scripts import nightly_eval as nightly

# Verbatim from data/logs/nightly_eval.log, the 30 nights Docker Desktop was not running.
DOCKER_DOWN_STDERR = (
    "failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; check if the path is correct "
    "and if the daemon is running: open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified."
)
OURS_EXITED = "local-ai-core-postgres-1|exited\nlocal-ai-qdrant|exited\nlocal-ai-core-redis-1|exited\n"


@pytest.fixture
def silent_port():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(16)
    yield server.getsockname()[1]
    server.close()


def fake_docker(monkeypatch, compose, holders: str = "") -> list[list[str]]:
    """Answer `docker compose ps` with `compose` (a result, or an exception to raise)
    and `docker ps --filter publish=...` with `holders`; return the commands run."""
    commands: list[list[str]] = []

    def run(command, **kwargs):
        commands.append(command)
        if command[1] == "compose":
            if isinstance(compose, BaseException):
                raise compose
            return subprocess.CompletedProcess(command, *compose)
        return subprocess.CompletedProcess(command, 0, holders, "")

    monkeypatch.setattr(nightly.subprocess, "run", run)
    return commands


def test_docker_desktop_not_running_is_said_so(monkeypatch):
    fake_docker(monkeypatch, (1, "", DOCKER_DOWN_STDERR))

    state = nightly.docker_state(postgres_port=5432)

    assert state.startswith("Docker Desktop is not answering (docker compose ps exit 1)")
    assert "dockerDesktopLinuxEngine" in state


def test_a_hung_docker_desktop_is_not_answering_too(monkeypatch):
    fake_docker(monkeypatch, subprocess.TimeoutExpired(["docker"], nightly.DOCKER_TIMEOUT_SECONDS))

    assert "did not return within" in nightly.docker_state(postgres_port=None)


def test_docker_up_with_the_stack_off_lists_the_stopped_containers(monkeypatch):
    fake_docker(monkeypatch, (0, OURS_EXITED, ""))

    state = nightly.docker_state(postgres_port=None)

    assert state.startswith("Docker answers, but none of this project's containers is running")
    assert "local-ai-core-postgres-1 (exited)" in state


def test_a_project_with_no_containers_is_not_read_as_running(monkeypatch):
    # The 18 nights' real output: exit 0 and a header, no rows.
    fake_docker(monkeypatch, (0, "", ""))

    assert "has no containers at all" in nightly.docker_state(postgres_port=None)


def test_a_foreign_container_on_the_postgres_port_is_named(monkeypatch):
    commands = fake_docker(monkeypatch, (0, OURS_EXITED, ""), holders="edu-postgres-1\n")

    state = nightly.docker_state(postgres_port=5432)

    assert "Port 5432 is held by edu-postgres-1, a container that is not this project's." in state
    assert ["docker", "ps", "--filter", "publish=5432", "--format", "{{.Names}}"] in commands


def test_our_own_postgres_on_the_port_is_not_called_foreign(monkeypatch):
    fake_docker(monkeypatch, (0, "local-ai-core-postgres-1|running\n", ""), holders="local-ai-core-postgres-1\n")

    assert "not this project's" not in nightly.docker_state(postgres_port=5432)


def test_the_port_holder_is_only_asked_when_postgres_is_down(monkeypatch):
    commands = fake_docker(monkeypatch, (0, OURS_EXITED, ""))

    nightly.docker_state(postgres_port=None)

    assert all(command[1] == "compose" for command in commands)


def test_dead_dependencies_are_each_named_within_seconds_and_without_the_password(silent_port):
    started = time.monotonic()
    down = nightly.check_dependencies(
        f"postgresql+psycopg://lab:s3cret@127.0.0.1:{silent_port}/local_ai_core_lab_20260821",
        f"http://127.0.0.1:{silent_port}",
        f"redis://:s3cret@127.0.0.1:{silent_port}/0",
        timeout=1,
    )

    assert set(down) == {"postgres", "qdrant", "redis"}
    assert down["postgres"].startswith(f"127.0.0.1:{silent_port}/local_ai_core_lab_20260821: ")
    assert all("s3cret" not in why for why in down.values())
    # libpq's 2 s floor + 1 s + 1 s, with room for a slow CI machine.
    assert time.monotonic() - started < 12


def test_a_down_dependency_ends_the_night_with_93_before_the_lab_api_starts(monkeypatch, tmp_path):
    monkeypatch.setattr(nightly, "LOG", tmp_path / "nightly_eval.log")
    monkeypatch.setattr(nightly, "ATTENTION", tmp_path / "ATTENTION_nightly_eval.txt")
    monkeypatch.setattr(nightly, "lab_database_url", lambda: "postgresql+psycopg://lab:s3cret@127.0.0.1:5432/local_ai_core_lab_20260821")
    monkeypatch.setattr(nightly, "check_dependencies", lambda *args, **kwargs: {"postgres": "127.0.0.1:5432/local_ai_core_lab_20260821: OperationalError: refused"})
    fake_docker(monkeypatch, (0, OURS_EXITED, ""), holders="edu-postgres-1\n")

    def no_lab_api(*args, **kwargs):
        raise AssertionError("the lab API was started although a dependency is down")

    monkeypatch.setattr(nightly.subprocess, "Popen", no_lab_api)

    assert nightly.main() == 93
    attention = (tmp_path / "ATTENTION_nightly_eval.txt").read_text(encoding="utf-8")
    assert "exit 93" in attention
    assert "Not starting the lab API: postgres is down." in attention
    assert "none of this project's containers is running" in attention
    assert "edu-postgres-1" in attention
