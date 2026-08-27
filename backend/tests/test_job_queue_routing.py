from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import job_queue_service
from app.services.job_queue_service import JobQueueService
from app.services.job_routing import (
    UnknownJobTypeError,
    resolve_job_route,
)
from app.config.settings import Settings


@pytest.mark.parametrize(
    ("job_type", "queue_name", "task"),
    [
        (
            "extract_document",
            "ocr",
            "app.workers.tasks.extract_document",
        ),
        (
            "index_document",
            "index",
            "app.workers.tasks.index_document",
        ),
        (
            "discord_memory_ingest",
            "memory_extract",
            "app.workers.memory_tasks.discord_memory_ingest",
        ),
    ],
)
def test_bounded_job_route_registry(job_type, queue_name, task):
    route = resolve_job_route(
        job_type,
        memory_queue_name="memory_extract",
    )
    assert route.queue_name == queue_name
    assert route.task_path == task


def test_unknown_job_type_fails_closed_before_redis_access(monkeypatch):
    monkeypatch.setattr(
        job_queue_service.Redis,
        "from_url",
        lambda *_: SimpleNamespace(),
    )
    service = JobQueueService("redis://unused", "test")
    with pytest.raises(UnknownJobTypeError):
        service.enqueue("unknown_type", "job-1")


def test_discord_memory_configuration_defaults_are_safe():
    settings = Settings(
        database_url="postgresql+psycopg://user:password@localhost/test",
        _env_file=None,
    )
    assert settings.discord_memory_ingestion_enabled is False
    assert settings.discord_memory_extractor_enabled is False
    # P2-1b: the shipped default moved to 9b after the 19/08 benchmark showed
    # 2b poisons ~49% of auto-applies and no harness fixes it.
    assert settings.discord_memory_extractor_model == "qwen3.5:9b"
    # 28/08: v2 = vocabulary v2 (user.birthday, user.favorite_drink/food);
    # the wire format is unchanged, the bump re-keys idempotency.
    assert settings.discord_memory_extractor_schema_version == "v2"
    assert settings.discord_memory_extractor_num_ctx == 4096
    assert settings.discord_memory_extractor_temperature == 0.0
    assert settings.discord_memory_extractor_seed == 424242
    assert settings.discord_memory_extractor_json_fallback is False
    assert settings.discord_memory_extractor_timeout_seconds == 60.0
    assert settings.discord_memory_extractor_retry_count == 1
    assert settings.discord_memory_queue_name == "memory_extract"


def test_queue_service_uses_memory_queue_and_deterministic_job_id(monkeypatch):
    calls = []

    class FakeQueue:
        def __init__(self, name, connection):
            self.name = name

        def enqueue(self, task, *args, **kwargs):
            calls.append((self.name, task, args[0], kwargs))
            return SimpleNamespace(id=kwargs["job_id"])

    monkeypatch.setattr(
        job_queue_service.Redis,
        "from_url",
        lambda *_: SimpleNamespace(),
    )
    monkeypatch.setattr(
        job_queue_service.Job,
        "fetch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyError()),
    )
    monkeypatch.setattr(job_queue_service, "Queue", FakeQueue)
    result = JobQueueService(
        "redis://unused",
        "local-ai:test",
        memory_queue_name="memory_extract",
    ).enqueue("discord_memory_ingest", "job-memory-1")
    assert result == "job-memory-1"
    assert calls[0][:3] == (
        "local-ai:test:memory_extract",
        "app.workers.memory_tasks.discord_memory_ingest",
        "job-memory-1",
    )
