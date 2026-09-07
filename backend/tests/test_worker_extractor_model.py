"""Memory worker (design §4 "Memory worker"): the extractor and verifier tags come from
the model registry resolver, and a role that does not serve leaves the worker on the
rule-filter-only path. discord_memory_ingest runs with every I/O boundary faked — no
Postgres, no Redis, no Ollama — so what is asserted is exactly the wiring.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config.model_registry import PostgresCounts, ProductionProbes
from app.config.settings import Settings
from app.workers import memory_tasks

DATABASE_URL = "postgresql+psycopg://user:password@localhost/test"
# roles.extractor.active = extractor-v0 and roles.verifier.active = verifier-v0 both name it.
SHIPPED_TAG = "qwen3.5:9b"


class Recorder:
    """Stands in for an adapter, a store or the worker service: keeps its constructor arguments."""

    def __init__(self, *args, **kwargs) -> None:
        self.args, self.kwargs = args, kwargs

    def process(self, job_id: str):
        self.job_id = job_id
        return SimpleNamespace(status="completed")


def settings(**overrides) -> Settings:
    """Init kwargs outrank the env pins conftest sets, so each test states its own flags."""
    defaults = dict(database_url=DATABASE_URL, _env_file=None, model_startup_probes=False, discord_memory_auto_apply_threshold=None)
    defaults.update(overrides)
    return Settings(**defaults)


def recording(bucket: list):
    class Fake(Recorder):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            bucket.append(self)

    return Fake


@pytest.fixture
def run_worker(monkeypatch):
    """discord_memory_ingest("job-1") against the given Settings; returns what it built."""

    def run(config: Settings) -> SimpleNamespace:
        built = SimpleNamespace(extractors=[], verifiers=[], workers=[])
        monkeypatch.setattr(memory_tasks, "get_settings", lambda: config)
        monkeypatch.setattr(memory_tasks, "create_postgres_engine", lambda url: SimpleNamespace(url=url))
        monkeypatch.setattr(memory_tasks, "create_session_factory", lambda engine: SimpleNamespace(engine=engine))
        monkeypatch.setattr(memory_tasks, "DiscordMemoryExtractorAdapter", recording(built.extractors))
        monkeypatch.setattr(memory_tasks, "DiscordMemoryVerifierAdapter", recording(built.verifiers))
        monkeypatch.setattr(memory_tasks, "DiscordMemoryWorkerService", recording(built.workers))
        memory_tasks.discord_memory_ingest("job-1")
        assert len(built.workers) == 1 and built.workers[0].job_id == "job-1"
        built.worker = built.workers[0].kwargs
        return built

    return run


def ollama_serves(monkeypatch, tags: dict[str, str]) -> None:
    """Ollama answers /api/tags with `tags` only; the embedding side is a fresh install."""
    monkeypatch.setattr(ProductionProbes, "ollama_tags", lambda self: dict(tags))
    monkeypatch.setattr(ProductionProbes, "ollama_embed_dimension", lambda self, model: 1024)
    monkeypatch.setattr(ProductionProbes, "qdrant_dimension", lambda self, collection: None)
    monkeypatch.setattr(ProductionProbes, "qdrant_point_count", lambda self, collection: 0)
    monkeypatch.setattr(ProductionProbes, "postgres_counts", lambda self: PostgresCounts(0, 0))


def test_worker_receives_the_resolvers_extractor_name_when_the_env_var_is_unset(run_worker):
    config = settings(discord_memory_extractor_enabled=True)
    assert config.discord_memory_extractor_model is None

    built = run_worker(config)

    role = config.resolve_models().roles["extractor"]
    assert (role.requested_id, role.source, role.status, role.serving) == ("extractor-v0", "registry", "active", True)
    assert [adapter.kwargs["model"] for adapter in built.extractors] == [SHIPPED_TAG]
    assert built.worker["extractor_enabled"] is True and built.worker["extractor_model"] == SHIPPED_TAG
    assert built.worker["extractor"] is built.extractors[0]
    assert built.worker["verifier"] is None and built.verifiers == []


def test_an_ad_hoc_tag_pin_is_served_as_env_tag_with_a_chain_of_one(run_worker):
    config = settings(discord_memory_extractor_enabled=True, discord_memory_extractor_model="qwen3.5:2b")

    built = run_worker(config)

    role = config.resolve_models().roles["extractor"]
    assert (role.requested_id, role.source, len(role.chain)) == ("env:qwen3.5:2b", "env_tag", 1)
    assert built.extractors[0].kwargs["model"] == "qwen3.5:2b" and built.worker["extractor_model"] == "qwen3.5:2b"


def test_a_tag_absent_from_ollama_disables_the_extractor_and_keeps_the_rule_filter(run_worker, monkeypatch):
    ollama_serves(monkeypatch, {"qwen3-embedding:0.6b": "sha256:b", "glm-ocr:latest": "sha256:c"})
    config = settings(discord_memory_extractor_enabled=True, discord_memory_verifier_enabled=True, model_startup_probes=True)

    built = run_worker(config)

    roles = config.resolve_models().roles
    assert (roles["extractor"].status, roles["extractor"].serving) == ("disabled", False)
    assert roles["verifier"].status == "disabled"
    assert built.extractors == [] and built.verifiers == []
    assert built.worker["extractor_enabled"] is False and built.worker["extractor"] is None and built.worker["verifier"] is None
    # The record is kept on `disabled`, so the candidate row still names the model that did not run.
    assert built.worker["extractor_model"] == SHIPPED_TAG


def test_verifier_is_built_only_when_both_flags_are_on_and_its_version_serves(run_worker):
    both = run_worker(settings(discord_memory_extractor_enabled=True, discord_memory_verifier_enabled=True))
    assert [adapter.kwargs["model"] for adapter in both.verifiers] == [SHIPPED_TAG]
    assert both.worker["verifier"] is both.verifiers[0]

    verifier_alone = run_worker(settings(discord_memory_verifier_enabled=True))
    assert verifier_alone.verifiers == [] and verifier_alone.worker["verifier"] is None


def test_extractor_flag_off_keeps_the_pointer_name_for_the_candidate_row(run_worker):
    config = settings()      # DISCORD_MEMORY_EXTRACTOR_ENABLED=false: the suite default

    built = run_worker(config)

    role = config.resolve_models().roles["extractor"]
    assert (role.status, role.reason) == ("off", "DISCORD_MEMORY_EXTRACTOR_ENABLED=false")
    assert built.extractors == [] and built.worker["extractor_enabled"] is False
    assert built.worker["extractor_model"] == SHIPPED_TAG


def test_auto_apply_review_service_gets_the_memories_sweep_and_the_embedding_refusal(run_worker, monkeypatch):
    stores: list[Recorder] = []
    monkeypatch.setattr(memory_tasks, "QdrantStore", recording(stores))
    config = settings(discord_memory_extractor_enabled=True, discord_memory_auto_apply_threshold=0.8)

    built = run_worker(config)

    review = built.worker["review_service"]
    assert built.worker["auto_apply_threshold"] == 0.8
    collections = config.qdrant_collections()
    assert len(stores) == 1 and review.memory_service.qdrant is stores[0]
    assert stores[0].args == (config.qdrant_url, config.qdrant_timeout_seconds, collections.memories)
    assert stores[0].kwargs == {"memories_sweep": collections.all_memories}
    assert review.memory_service.router.embedding_refusal is None
    assert review.memory_service.router.models is config.load_models()
