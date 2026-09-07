"""Model registry through the running app (design §4 "Tests"; acceptance C and D).

/models.registry, /models.rag, /health.model_fallback, the ATTENTION marker and the
model_version_fallback log line are read from a TestClient(app) whose lifespan ran
the real resolver and the real reranker warmup. The registry_app fixture turns the
probes ON against a fixture registry — the shipped file with one edit — and fakes
every probe answer and the cross-encoder loader, so nothing here talks to Ollama,
imports torch or downloads weights.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from loguru import logger

from app.config.model_registry import (
    ATTENTION_FILENAME,
    DEFAULT_REGISTRY_PATH,
    PROJECT_ROOT,
    ROLES,
    PostgresCounts,
    ProductionProbes,
)
from app.config.settings import get_settings
from app.main import app
from app.services.reranker_service import RerankerService

SHIPPED = yaml.safe_load(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
V0 = next(record for record in SHIPPED["roles"]["reranker"]["versions"] if record["id"] == "reranker-v0")
BROKEN_ID = "reranker-missing-v9"
BROKEN_DIR = PROJECT_ROOT / "data" / "models" / "reranker" / BROKEN_ID
# Every Ollama tag the shipped file names, present with an arbitrary digest.
TAGS = {"qwen3.5:9b": "sha256:general", "qwen3-embedding:0.6b": "sha256:embedding", "glm-ocr:latest": "sha256:ocr"}
# The states that are a decision, never a deviation (RoleResolution.deviates).
DELIBERATE = {"active", "off", "unconfigured"}


def marker_path() -> Path:
    # conftest points LOG_DIR at tests/test_logs; Settings.logs_path follows it.
    return Path(os.environ["LOG_DIR"]) / ATTENTION_FILENAME


def broken_active_registry(tmp_path: Path) -> Path:
    """The shipped registry with reranker.active pointed at a version whose weights are
    absent — a `path` entry with no directory — listed right after reranker-v0, so the
    chain is [broken, reranker-v0] and reranker-d2-v1 stays a candidate after it."""
    document = copy.deepcopy(SHIPPED)
    reranker = document["roles"]["reranker"]
    reranker["versions"].insert(1, {
        "id": BROKEN_ID, "provider": "sentence-transformers", "path": f"data/models/reranker/{BROKEN_ID}",
        "activation": "identity", "num_labels": 1, "max_length": 512, "vram_mib": 643,
        "digest": {"file": "model.safetensors", "sha256": None},
        "probe": {"pairs": [], "scores": None, "tolerance": 0.05, "max_ms": 500},
        "eval": {"reports": {"d1_multidoc": None}},
    })
    reranker["active"] = BROKEN_ID
    path = tmp_path / "model_versions.yaml"
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


class FakeCrossEncoder:
    """What a loaded reranker-v0 looks like to warmup: one head, the 512 window on the
    tokenizer (max_length None is the real 3.4.1 shape) and the recorded probe scores,
    cycled over any batch, so parity passes and the timed predict has something to time."""

    def __init__(self) -> None:
        self.model = SimpleNamespace(config=SimpleNamespace(num_labels=V0["num_labels"]))
        self.max_length = None
        self.tokenizer = SimpleNamespace(model_max_length=V0["max_length"])

    def predict(self, pairs):
        scores = V0["probe"]["scores"]
        return [scores[index % len(scores)] for index in range(len(pairs))]


class Loader:
    """The cross-encoder loader: reranker-v0 loads, anything else has no weights.
    Records every call so a test can prove the fallback never reached the hub."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name, **kwargs):
        self.calls.append((name, dict(kwargs)))
        if name == V0["hub"]:
            return FakeCrossEncoder()
        raise OSError(f"{name} is not a local folder and no cached snapshot exists")


def fake_probes(monkeypatch) -> None:
    """Every tag present, the probe embed 1024 wide, no collection yet, an empty corpus:
    the fresh-install state, in which every probed pointer resolves `active`."""
    monkeypatch.setattr(ProductionProbes, "ollama_tags", lambda self: dict(TAGS))
    monkeypatch.setattr(ProductionProbes, "ollama_embed_dimension", lambda self, model: 1024)
    monkeypatch.setattr(ProductionProbes, "qdrant_dimension", lambda self, collection: None)
    monkeypatch.setattr(ProductionProbes, "qdrant_point_count", lambda self, collection: 0)
    monkeypatch.setattr(ProductionProbes, "postgres_counts", lambda self: PostgresCounts(0, 0))


@pytest.fixture
def registry_events():
    """Every loguru record emitted while a fixture app boots and answers."""
    sink: list[dict] = []
    handle = logger.add(lambda message: sink.append(message.record), level="INFO")
    yield sink
    logger.remove(handle)


def _boot(monkeypatch, *, registry: Path | None, reranker_on: bool, loader: Loader, pins: dict[str, str] | None = None):
    """The design's registry_app recipe: clear the Settings cache, point the env at the
    fixture with the probes ON, fake the probes and the loader, boot the app; on the way
    out undo the env and prove the suite default (probes off) is what the next test gets.
    `pins` are MODEL_VERSION_<ROLE> variables for this boot only (a shell pin)."""
    get_settings.cache_clear()
    monkeypatch.setenv("MODEL_STARTUP_PROBES", "true")
    if registry is not None:
        monkeypatch.setenv("MODEL_REGISTRY_PATH", str(registry))
    for name, value in (pins or {}).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("RAG_RERANKER_ENABLED", "true" if reranker_on else "false")
    # The operating machine's .env may still carry the ad-hoc extractor tag; "" is
    # "unset" (the before-validator), so every role follows the registry pointer.
    monkeypatch.setenv("DISCORD_MEMORY_EXTRACTOR_MODEL", "")
    monkeypatch.setenv("DISCORD_MEMORY_VERIFIER_MODEL", "")
    # conftest pins the extractor/verifier flags but not this one; a machine with
    # the condenser and a Gemini key on would otherwise resolve it `active`.
    monkeypatch.setenv("DISCORD_CONDENSATION_ENABLED", "false")
    fake_probes(monkeypatch)
    monkeypatch.setattr(RerankerService, "_load_cross_encoder", staticmethod(loader))
    # /health.status must read "ok": Postgres, Redis and Qdrant answer for real; Ollama is faked as mock_ollama does.
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.healthcheck", lambda self: True)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        marker_path().unlink(missing_ok=True)
        # Undo the env FIRST (the monkeypatch fixture would only do it later), so the
        # cache the next test fills holds the suite default — probes off — not ours.
        monkeypatch.undo()
        get_settings.cache_clear()
        assert get_settings().model_startup_probes is False


@pytest.fixture
def registry_app(monkeypatch, tmp_path, registry_events):
    """Acceptance D: the active reranker's weights are absent and the API boots anyway."""
    loader = Loader()
    for client in _boot(monkeypatch, registry=broken_active_registry(tmp_path), reranker_on=True, loader=loader):
        client.loader = loader
        yield client


@pytest.fixture
def pinned_app(monkeypatch, registry_events):
    """A shell pin on the shipped candidate whose weights are absent: the shipped file is
    untouched (`active` stays reranker-v0), so the pin — not the file — is what re-triggers
    the fallback on every restart, and the marker has to say so."""
    loader = Loader()
    for client in _boot(monkeypatch, registry=None, reranker_on=True, loader=loader, pins={"MODEL_VERSION_RERANKER": "reranker-d2-v1"}):
        client.loader = loader
        yield client


@pytest.fixture
def shipped_app(monkeypatch, registry_events):
    """Acceptance C: the shipped registry with every probe answering."""
    # A marker left by an earlier deviating boot must not outlive the state it described.
    marker_path().parent.mkdir(parents=True, exist_ok=True)
    marker_path().write_text("stale marker\n", encoding="utf-8")
    yield from _boot(monkeypatch, registry=None, reranker_on=False, loader=Loader())


def events_named(records: list[dict], event: str) -> list[dict]:
    return [record for record in records if record["extra"].get("event") == event]


# ── the suite default: probes off ─────────────────────────────────────────────


def test_suite_default_boot_serves_every_pointer_unverified_and_reports_ok(mock_ollama, client):
    # mock_ollama comes first: /health.status folds in the Ollama healthcheck, and CI has no
    # Ollama. What this test asserts about the top-level status is that the registry leaves
    # it alone, so the environment must not be what decides it (CI run #78 went red on this).
    models = client.get("/models").json()
    health = client.get("/health").json()

    registry = models["registry"]
    assert set(registry) == set(ROLES) and len(registry) == 8
    for role, row in registry.items():
        assert row["status"] in DELIBERATE, (role, row)
        assert row["fallback"] is False and row["verified"] is False, (role, row)
        assert row["active"] == SHIPPED["roles"][role]["active"], role
    # The extractor/verifier pointer may be an ad-hoc tag pin from this machine's .env;
    # every other role can only come from the file.
    assert all(registry[role]["source"] == "registry" for role in ("general", "condenser", "embedding", "vision", "ocr", "reranker"))
    assert registry["reranker"]["status"] == "off", "RAG_RERANKER_ENABLED=false in the suite is a decision, not a deviation"
    assert registry["vision"]["status"] == "unconfigured" and registry["vision"]["loaded"] is None
    assert registry["embedding"]["collections"] == {"documents": "documents_test", "memories": "memories_test"}
    assert "vision" not in models["models"] and models["models"]["embedding"]["name"] == "qwen3-embedding:0.6b"
    assert models["rag"]["contextual_retrieval"] is False and models["rag"]["reranker"] is False
    assert models["rag"]["retrieval_mode"] in {"dense", "bm25", "hybrid"}
    assert health["status"] == "ok" and health["model_fallback"] == "ok"
    assert not marker_path().exists()
    # One dict: the router serves exactly what /models reports.
    assert client.app.state.models is client.app.state.memory_service.router.models


# ── acceptance D: a broken active reranker ────────────────────────────────────


def test_broken_active_reranker_falls_back_and_every_signal_says_so(mock_ollama, registry_app, registry_events):
    client = registry_app
    models = client.get("/models").json()
    health = client.get("/health").json()
    row = models["registry"]["reranker"]

    # /models.registry keeps the pointer as `requested`, names what serves, and says why.
    assert (row["active"], row["requested"], row["loaded"], row["source"], row["status"]) == (BROKEN_ID, BROKEN_ID, "reranker-v0", "registry", "fallback")
    assert row["fallback"] is True and row["verified"] is True and isinstance(row["latency_ms"], int)
    assert row["reason"].startswith(f"{BROKEN_ID} ") and row["reason"].endswith("serving reranker-v0")
    assert row["name"] == V0["hub"]
    # The broken one was tried first; the fallback loaded from the disk cache with the record's kwargs, never the hub.
    assert client.loader.calls == [
        (str(BROKEN_DIR), {"local_files_only": True, "activation": "identity"}),
        (V0["hub"], {"revision": V0["revision"], "local_files_only": True}),
    ]
    # Every other role is a deliberate state; the flat flag is the one predicate.
    assert all(models["registry"][role]["status"] in DELIBERATE for role in ROLES if role != "reranker")
    assert models["rag"]["reranker"] is True
    assert health["status"] == "ok", "a fallback is a serving state: control.py and the smoke test gate on status"
    assert health["model_fallback"] == "fallback"
    # The service really serves v0; the request-time contract is unchanged.
    reranker = client.app.state.rag_service.retrieval_service.reranker_service
    assert reranker.enabled is True and reranker.loaded.id == "reranker-v0"
    # The marker names the role and the one-step revert.
    text = marker_path().read_text(encoding="utf-8")
    assert f"reranker: requested={BROKEN_ID} loaded=reranker-v0 status=fallback" in text
    assert "MODEL_VERSION_RERANKER=reranker-v0" in text and "restart run-local-ai-core.bat" in text
    # The durable log carries the deviation, the rejection and the survivor.
    fallback = events_named(registry_events, "model_version_fallback")
    assert [(r["extra"]["role"], r["extra"]["requested"], r["extra"]["loaded"], r["extra"]["status"], r["level"].name) for r in fallback] == [
        ("reranker", BROKEN_ID, "reranker-v0", "fallback", "WARNING"),
    ]
    assert [r["extra"]["version_id"] for r in events_named(registry_events, "reranker_version_rejected")] == [BROKEN_ID]
    assert [r["extra"]["source"] for r in events_named(registry_events, "reranker_version_loaded")] == ["fallback"]


def test_a_pinned_candidate_that_falls_back_tells_the_operator_to_unset_the_pin(pinned_app):
    """operator-ux review: the marker said `edit roles.reranker.active` while `active` already
    WAS reranker-v0 — the shell pin was the thing to undo, and the file never said so."""
    row = pinned_app.get("/models").json()["registry"]["reranker"]
    assert (row["active"], row["requested"], row["loaded"], row["source"], row["status"]) == ("reranker-v0", "reranker-d2-v1", "reranker-v0", "env", "fallback")
    assert pinned_app.get("/health").json()["model_fallback"] == "fallback"
    text = marker_path().read_text(encoding="utf-8")
    assert "reranker: requested=reranker-d2-v1 loaded=reranker-v0 status=fallback" in text
    assert "revert: unset MODEL_VERSION_RERANKER in this shell (or set it to reranker-v0), then restart run-local-ai-core.bat" in text
    assert "edit roles.reranker.active" not in text and "<a previous id>" not in text


def test_write_baseline_refuses_against_the_fallback_server(registry_app, tmp_path):
    """Acceptance D, last clause: the report writer reads /models.registry of THIS server
    and will not record a baseline while the reranker serves its fallback."""
    from scripts.evaluate_rag import run_multidoc_mode

    baseline = tmp_path / "baseline.json"
    code = run_multidoc_mode(registry_app, "", [], {}, True, tmp_path / "out", None, 0.02, baseline)
    assert code == 1 and not baseline.exists()
    # The run's own report still names what served, so the deviation is on record.
    (report,) = (tmp_path / "out").glob("rag-multidoc-*.json")
    assert '"reranker": "reranker-v0"' in report.read_text(encoding="utf-8")


# ── acceptance C: the shipped file with every probe answering ─────────────────


def test_shipped_registry_with_every_probe_answering_is_all_active_off_or_unconfigured(mock_ollama, shipped_app, registry_events):
    models = shipped_app.get("/models").json()
    health = shipped_app.get("/health").json()
    rows = models["registry"]

    assert set(rows) == set(ROLES) and len(rows) == 8
    assert {role: row["status"] for role, row in rows.items()} == {
        "general": "active", "condenser": "off", "embedding": "active", "vision": "unconfigured",
        "ocr": "active", "reranker": "off", "extractor": "off", "verifier": "off",
    }
    assert all(row["fallback"] is False and row["source"] == "registry" for row in rows.values())
    assert [role for role, row in rows.items() if row["verified"]] == ["general", "embedding", "ocr"]
    assert {role: row["loaded"] for role, row in rows.items() if row["loaded"]} == {"general": "general-v0", "embedding": "embedding-v0", "ocr": "ocr-v0"}
    assert health["status"] == "ok" and health["model_fallback"] == "ok"
    assert not marker_path().exists(), "a stale marker is removed by a boot in which nothing deviates"
    assert events_named(registry_events, "model_version_fallback") == []
