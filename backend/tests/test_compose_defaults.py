"""docker-compose.yml carries no defaults of its own; Settings keeps them all.

A `${VAR:-x}` in compose is a second default: when the operator's .env leaves
VAR unset, a container gets x while a process on the host gets the Settings
default. DISCORD_MEMORY_EXTRACTOR_SCHEMA_VERSION drifted exactly so (compose v1,
Settings v2 since 28/08), and a Docker memory worker would then fail every job
the host API enqueued as MEMORY_SCHEMA_VERSION_STALE. So every Settings field is
passed through as a bare key (`VAR:`): compose copies it from the operator's
shell or .env, and when neither sets it the variable is ABSENT in the container
and Settings decides. `docker compose config` prints such a key as `null`.

The model pins keep their old rule in the new shape (design §4 "Docker
workers"): a default would pin every container to one tag or version forever,
silently overriding the registry's `active` pointer.
"""
from __future__ import annotations

import contextlib
import re
from types import SimpleNamespace
from uuid import uuid4

import yaml

from app.config.model_registry import PROJECT_ROOT
from app.config.settings import Settings
from app.postgres.discord_memory_job_repository import (
    DiscordMemoryEligibility,
    DiscordMemoryJobRepository,
)
from app.postgres.discord_memory_repositories import DiscordMemoryRepository
from app.services.discord_memory_completion_service import DiscordMemoryCompletionService
from app.services.discord_memory_worker_service import DiscordMemoryWorkerService
from app.services.job_routing import DISCORD_MEMORY_INGEST_JOB_TYPE

COMPOSE = PROJECT_ROOT / "docker-compose.yml"
WORKERS = ("worker-ocr", "worker-index", "worker-memory")
PINS = ("MODEL_VERSION_EXTRACTOR", "MODEL_VERSION_VERIFIER", "MODEL_VERSION_EMBEDDING")
FIELDS = frozenset(name.upper() for name in Settings.model_fields)
# Container wiring, not a copy of a Settings default: the compose network's
# hosts and the queue backend these containers exist to run.
WIRING = frozenset({"INGESTION_EXECUTION_BACKEND", "DATABASE_URL", "REDIS_URL", "OLLAMA_BASE_URL", "QDRANT_URL"})
# The one deliberate exception. The rq CLI takes its queue name on the command
# line, so without a default an unset prefix would make a worker listen on
# ":ocr" while jobs land on "local-ai:dev:ocr". These two may keep a default
# on `command:`, but only the one Settings ships. The cleaner fix is a worker
# entrypoint that builds the name from Settings.
COMMAND_DEFAULTS = frozenset({"RQ_QUEUE_PREFIX", "DISCORD_MEMORY_QUEUE_NAME"})
DEFAULTED = re.compile(r"\$\{(\w+):?-")


def compose_default(text: str, var: str) -> str:
    """The default after `${VAR:-` (or `${VAR-`), up to ITS closing brace.

    A `[^}]*` regex stops at the first `}`, so `${A:-${B}}` read as `${B`:
    harmless today (only CONTAINER_DATABASE_URL nests, and it is not a Settings
    field) but wrong the day a Settings field's default nests."""
    start = re.search(rf"\$\{{{var}:?-", text).end()
    depth = 1
    for index in range(start, len(text)):
        if text.startswith("${", index):
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index]
    raise ValueError(f"unbalanced braces after ${{{var}: {text!r}")


def test_a_nested_default_is_read_to_its_own_closing_brace():
    assert compose_default("${CONTAINER_DATABASE_URL:-${DATABASE_URL}}", "CONTAINER_DATABASE_URL") == "${DATABASE_URL}"
    assert compose_default("${A:-${B:-x}}/tail", "B") == "x"
    assert compose_default("rq worker ${RQ_QUEUE_PREFIX:-local-ai:dev}:ocr", "RQ_QUEUE_PREFIX") == "local-ai:dev"


def services() -> dict[str, dict]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def environment(service: dict) -> dict[str, str | None]:
    block = service.get("environment") or {}
    # Compose accepts a mapping or a list of KEY=VALUE strings; the file uses the
    # mapping form, but the rule must hold whichever shape a future edit picks.
    # A bare key (`KEY:` or `- KEY`) reads as None.
    if isinstance(block, list):
        return {key: value if sep else None for key, sep, value in (item.partition("=") for item in block)}
    return {str(key): None if value is None else str(value) for key, value in block.items()}


def strings(node: object):
    """Every string compose interpolates, wherever it sits in a service."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from strings(value)


def test_every_settings_field_passes_through_bare():
    offenders = [
        f"{name}.{key}={value}"
        for name, service in services().items()
        for key, value in environment(service).items()
        if key in FIELDS and key not in WIRING and value is not None
    ]
    assert offenders == [], "compose sets a Settings field itself; pass it through bare: " + ", ".join(offenders)


def test_no_settings_field_gets_a_compose_default_but_the_rq_queue_names():
    offenders = []
    for name, service in services().items():
        for part, node in service.items():
            for text in strings(node):
                for var in DEFAULTED.findall(text):
                    if var not in FIELDS:
                        continue
                    default = compose_default(text, var)
                    shipped = str(Settings.model_fields[var.lower()].default)
                    if not (part == "command" and var in COMMAND_DEFAULTS and default == shipped):
                        offenders.append(f"{name}.{part}: {var} defaults to {default!r}, Settings ships {shipped!r}")
    assert offenders == [], "a second default drifts from Settings: " + "; ".join(offenders)


def test_no_model_or_version_line_carries_a_default():
    offenders = []
    for name, service in services().items():
        for key, value in environment(service).items():
            if (key.endswith("_MODEL") or key.startswith("MODEL_VERSION_")) and value is not None:
                offenders.append(f"{name}.{key}={value}")
    assert offenders == [], "a compose value would pin a model for every container: " + ", ".join(offenders)


def test_the_three_workers_pass_every_registry_pin_through_bare():
    for worker in WORKERS:
        env = environment(services()[worker])
        for pin in PINS:
            assert pin in env and env[pin] is None, f"{worker} must pass {pin} through bare"
    # The ad-hoc tag pin lost its qwen3.5:9b default with the registry: unset =
    # follow roles.extractor.active.
    env = environment(services()["worker-memory"])
    assert "DISCORD_MEMORY_EXTRACTOR_MODEL" in env and env["DISCORD_MEMORY_EXTRACTOR_MODEL"] is None


def test_an_empty_pass_through_is_unset_for_settings(monkeypatch):
    """A bare key still delivers "" when the operator's shell says `set X=`, and
    Settings must read that as no pin at all."""
    for key in (*PINS, "DISCORD_MEMORY_EXTRACTOR_MODEL"):
        monkeypatch.setenv(key, "")
    settings = Settings()
    assert settings.model_version_extractor is None
    assert settings.model_version_verifier is None
    assert settings.model_version_embedding is None
    assert settings.discord_memory_extractor_model is None


def interpolate(text: str, operator: dict[str, str]) -> str:
    """Compose's `${X}` and `${X:-default}` (defaults may nest) against the
    operator's shell + .env."""
    out, at = [], 0
    while (start := text.find("${", at)) != -1:
        depth, end = 1, start + 2
        while depth:
            if text.startswith("${", end):
                depth, end = depth + 1, end + 2
                continue
            if text[end] == "}":
                depth -= 1
            end += 1
        name, has_default, default = text[start + 2 : end - 1].partition(":-")
        out += [text[at:start], operator.get(name) or (interpolate(default, operator) if has_default else "")]
        at = end
    return "".join(out) + text[at:]


def container_environment(service: dict, operator: dict[str, str]) -> dict[str, str]:
    """What the process inside the container finds in os.environ."""
    seen = {}
    for key, value in environment(service).items():
        if value is not None:
            seen[key] = interpolate(value, operator)
        elif key in operator:
            seen[key] = operator[key]
    return seen


def settings_seeing(monkeypatch, env: dict[str, str]) -> Settings:
    for field in FIELDS:
        monkeypatch.delenv(field, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # Neither the image nor this test reads a .env: env is all there is.
    return Settings(_env_file=None)


class _Sessions:
    @contextlib.contextmanager
    def begin(self):
        yield SimpleNamespace(flush=lambda: None)


class _CandidateKeyed(Exception):
    pass


def test_a_job_the_host_enqueues_is_one_the_docker_memory_worker_keys(monkeypatch):
    """The operator's .env sets only the databases (the real .env does not set
    the schema version). The host API keys the turn's job under the version
    Settings ships; the compose memory worker must key the candidate under that
    same version, not fail the job as stale. Postgres is stubbed: a run against
    a real stack is the integration check, not this one."""
    shipped = Settings.model_fields["discord_memory_extractor_schema_version"].default
    turn_id, session_id = uuid4(), uuid4()
    source = SimpleNamespace(
        turn_id=turn_id,
        session_id=session_id,
        source_discord_message_id="1",
        source_author_id="2",
        source_author_display_name=None,
        guild_id="3",
        channel_id="4",
        thread_id=None,
    )
    enqueued, failed, keyed = {}, {}, {}

    def create_job_and_outbox(self, *, turn_id, session_id, schema_version, max_attempts):
        enqueued["key"] = self.job_idempotency_key(turn_id, schema_version)
        enqueued["payload"] = self._expected_payload(turn_id, session_id, schema_version)
        return SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4()), True

    def fail_owned(self, job_id, **fields):
        failed.update(fields)
        return "failed"

    def create_or_get_candidate(self, **fields):
        keyed.update(fields)
        raise _CandidateKeyed

    monkeypatch.setattr(DiscordMemoryJobRepository, "assess_source", lambda self, turn: DiscordMemoryEligibility(True, "eligible", source))
    monkeypatch.setattr(DiscordMemoryJobRepository, "create_job_and_outbox", create_job_and_outbox)
    monkeypatch.setattr(DiscordMemoryJobRepository, "get_job", lambda self, job_id, lock=False: SimpleNamespace(payload=enqueued["payload"]))
    monkeypatch.setattr(DiscordMemoryJobRepository, "fail_owned", fail_owned)
    monkeypatch.setattr(DiscordMemoryRepository, "create_or_get_candidate", create_or_get_candidate)

    # Host side, wired as app/main.py wires it.
    host = settings_seeing(monkeypatch, {"DATABASE_URL": "postgresql+psycopg://local_ai:x@127.0.0.1:5432/local_ai_core"})
    DiscordMemoryCompletionService(
        enabled=True,
        extractor_schema_version=host.discord_memory_extractor_schema_version,
        max_attempts=host.job_max_attempts,
    ).on_first_completion(SimpleNamespace(flush=lambda: None), turn_id)
    assert enqueued["key"] == f"{DISCORD_MEMORY_INGEST_JOB_TYPE}:{turn_id}:{shipped}"

    # Container side, wired as app/workers/memory_tasks.py wires it.
    operator = {"CONTAINER_DATABASE_URL": "postgresql+psycopg://local_ai:x@postgres:5432/local_ai_core"}
    container = settings_seeing(monkeypatch, container_environment(services()["worker-memory"], operator))
    worker = DiscordMemoryWorkerService(
        _Sessions(),
        worker_id="test",
        lease_seconds=container.job_stale_timeout_seconds,
        extractor_schema_version=container.discord_memory_extractor_schema_version,
    )
    with contextlib.suppress(_CandidateKeyed):
        worker._prepare("job-1")
    assert failed == {}, f"the Docker memory worker refused the host's job: {failed.get('error_message')}"
    assert (keyed["source_turn_id"], keyed["extractor_schema_version"]) == (turn_id, shipped)
