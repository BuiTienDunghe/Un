"""Model registry: RerankerService.warmup() walks the version chain and NEVER raises.

Every check the design lists — pre-load export.json / digest, the load itself, the
post-load head and window, probe-pair parity, the timed predict — is exercised with
fake loaders that record their kwargs, so nothing is downloaded. The one test that
loads real weights uses the reranker-v0 snapshot already in the HF disk cache under
HF_HUB_OFFLINE (never a download) and is skipped when the cache does not hold it.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from loguru import logger

from app.config.model_registry import (
    DEFAULT_REGISTRY_PATH,
    Overrides,
    RerankerProbeSpec,
    VersionRecord,
    load_registry,
    resolve,
)
from app.services.reranker_service import HUB_DEFAULT_MODEL, RerankerService, RerankerUnavailableError

PAIRS = (("q1", "p1"), ("q2", "p2"), ("q3", "p3"))
SCORES = (1.0, -2.0, 3.0)
FLAGS_OFF = frozenset({"condenser", "extractor", "verifier"})


def record(
    version_id: str, *, path: Path | None = None, revision: str | None = "rev", activation: str | None = None,
    num_labels: int | None = 1, max_length: int | None = 512, scores=SCORES, pairs=PAIRS, max_ms: int | None = 500,
    digest: str | None = None, tolerance: float = 0.05,
) -> VersionRecord:
    return VersionRecord(
        role="reranker", id=version_id, provider="sentence-transformers", config={},
        hub=None if path is not None else f"hub/{version_id}", path=path, revision=None if path is not None else revision,
        activation=activation, num_labels=num_labels, max_length=max_length,
        digest=digest, digest_file="model.safetensors" if path is not None else None,
        probe=RerankerProbeSpec(pairs=pairs, scores=scores, tolerance=tolerance, max_ms=max_ms),
    )


class FakeModel:
    """A loaded cross-encoder whose head size, window and probe scores the test chooses.
    max_length=None with a tokenizer limit is the shape a real 3.4.1 CrossEncoder has."""

    def __init__(self, scores=SCORES, *, num_labels: int = 1, max_length: int | None = None, tokenizer_limit: int = 512, delay: float = 0.0):
        self.model = SimpleNamespace(config=SimpleNamespace(num_labels=num_labels))
        self.max_length = max_length
        self.tokenizer = SimpleNamespace(model_max_length=tokenizer_limit)
        self._scores = list(scores)
        self.delay = delay
        self.predicted: list[int] = []

    def predict(self, pairs):
        self.predicted.append(len(pairs))
        if self.delay:
            time.sleep(self.delay)
        return [self._scores[index % len(self._scores)] for index in range(len(pairs))]


class Loader:
    """Records every (name, kwargs) call; `outcomes` maps a model name to a model or an exception."""

    def __init__(self, outcomes: dict):
        self.outcomes = outcomes
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name, **kwargs):
        self.calls.append((name, dict(kwargs)))
        outcome = self.outcomes[name]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def service(loader, *versions: VersionRecord, enabled: bool = True) -> RerankerService:
    return RerankerService(enabled, versions[0].name if versions else "", 15, model_loader=loader, versions=versions)


@pytest.fixture
def events():
    sink: list[dict] = []
    handle = logger.add(lambda message: sink.append(message.record), level="INFO")
    yield sink
    logger.remove(handle)


def named(events, event):
    return [item for item in events if item["extra"].get("event") == event]


def shipped_resolved():
    return resolve(load_registry(DEFAULT_REGISTRY_PATH), Overrides(disabled_roles=FLAGS_OFF), probes=None)


# ── the chain ────────────────────────────────────────────────────────────────


def test_active_version_loads_with_its_records_kwargs_and_reports_active(events):
    v1 = record("reranker-v1", revision="r1", activation="identity")
    loader = Loader({v1.name: FakeModel()})
    reranker = service(loader, v1, record("reranker-v0"))

    outcome = reranker.warmup()

    assert loader.calls == [(v1.name, {"revision": "r1", "activation": "identity"})], "index 0 may reach the hub: no local_files_only"
    assert (outcome.status, outcome.loaded_id, outcome.source, outcome.reason) == ("loaded", "reranker-v1", "active", None)
    assert outcome.parity_ok is True and outcome.digest_ok is None and isinstance(outcome.latency_ms, int)
    assert reranker.loaded is v1 and reranker.model_name == v1.name and reranker.enabled is True
    loaded = named(events, "reranker_version_loaded")
    assert len(loaded) == 1 and loaded[0]["extra"]["source"] == "active" and loaded[0]["level"].name == "INFO"
    assert named(events, "reranker_version_rejected") == []


def test_fallbacks_load_with_local_files_only_and_the_outcome_says_which_was_rejected(events):
    v1, v0 = record("reranker-v1", revision="r1"), record("reranker-v0", revision="r0")
    loader = Loader({v1.name: RuntimeError("weights corrupt"), v0.name: FakeModel()})
    reranker = service(loader, v1, v0)

    outcome = reranker.warmup()

    assert loader.calls == [(v1.name, {"revision": "r1"}), (v0.name, {"revision": "r0", "local_files_only": True})]
    assert (outcome.status, outcome.loaded_id, outcome.source) == ("loaded", "reranker-v0", "fallback")
    assert outcome.reason == "reranker-v1 load: RuntimeError: weights corrupt; serving reranker-v0"
    assert reranker.loaded is v0 and reranker.model_name == v0.name, "the lazy path must reload the SERVING record"
    rejected = named(events, "reranker_version_rejected")
    assert [(item["extra"]["version_id"], item["extra"]["reason"]) for item in rejected] == [("reranker-v1", "load")]
    assert rejected[0]["level"].name == "WARNING"
    assert named(events, "reranker_version_loaded")[0]["extra"]["source"] == "fallback"


def test_every_version_rejected_disables_the_service_and_boot_goes_on(events):
    """Decision 2: the chain ends in `disabled, source=fallback`, never a refused boot."""
    v1, v0 = record("reranker-v1"), record("reranker-v0")
    loader = Loader({v1.name: RerankerUnavailableError("Reranker cần gói tùy chọn: pip install -e .[rerank]"), v0.name: ImportError("No module named 'torch'")})
    reranker = service(loader, v1, v0)

    outcome = reranker.warmup()  # must not raise

    assert (outcome.status, outcome.loaded_id, outcome.source) == ("rejected_all", None, "fallback")
    assert outcome.reason == "reranker-v1 import: Reranker cần gói tùy chọn: pip install -e .[rerank]; reranker-v0 import: No module named 'torch'"
    assert reranker.enabled is False and reranker.loaded is None and reranker.outcome is outcome
    assert reranker.rerank("q", [{"content": "a"}, {"content": "b"}], 1) == [{"content": "a"}], "disabled = pass-through"
    assert [item["extra"]["reason"] for item in named(events, "reranker_version_rejected")] == ["import", "import"]
    # What main.py records upstream: `disabled` deviates, so /health says fallback.
    resolved = shipped_resolved()
    resolved.record_reranker(loaded_id=None, status="disabled", reason=outcome.reason)
    assert resolved.roles["reranker"].deviates and resolved.fallback_flag() == "fallback"


def test_parity_rejects_a_loadable_checkpoint_whose_scores_moved(events):
    """A random head or a Sigmoid-vs-Identity mismatch passes the constructor; only the
    recorded probe scores catch it (measured: forcing Sigmoid moves 2.998 to 0.95)."""
    v1, v0 = record("reranker-v1"), record("reranker-v0")
    loader = Loader({v1.name: FakeModel(scores=(0.95, 0.0001, 0.9995)), v0.name: FakeModel()})

    outcome = service(loader, v1, v0).warmup()

    assert (outcome.loaded_id, outcome.source, outcome.parity_ok) == ("reranker-v0", "fallback", True)
    rejected = named(events, "reranker_version_rejected")
    assert rejected[0]["extra"]["reason"] == "parity" and "pair 0: 0.9500 vs recorded 1.0000" in rejected[0]["extra"]["detail"]


def test_parity_within_tolerance_passes_and_is_disarmed_without_recorded_scores():
    within = record("reranker-v1", tolerance=0.05)
    assert service(Loader({within.name: FakeModel(scores=(1.04, -2.04, 3.04))}), within).warmup().parity_ok is True
    disarmed = record("reranker-v1", scores=None)
    outcome = service(Loader({disarmed.name: FakeModel(scores=(9.0, 9.0, 9.0))}), disarmed).warmup()
    assert outcome.status == "loaded" and outcome.parity_ok is None, "null scores = parity disarmed, not a rejection"


def test_export_json_activation_mismatch_rejects_before_the_load(tmp_path, events):
    """Contract with the exporter: the record's activation is a copy of export.json's."""
    checkpoint = tmp_path / "reranker-d2-v1"
    checkpoint.mkdir()
    (checkpoint / "export.json").write_text(json.dumps({"activation_fn": "sigmoid"}), encoding="utf-8")
    d2, v0 = record("reranker-d2-v1", path=checkpoint, activation="identity"), record("reranker-v0")
    loader = Loader({d2.name: FakeModel(), v0.name: FakeModel()})

    outcome = service(loader, d2, v0).warmup()

    assert [name for name, _ in loader.calls] == [v0.name], "a rejected export is never loaded"
    assert outcome.loaded_id == "reranker-v0"
    rejected = named(events, "reranker_version_rejected")[0]["extra"]
    assert rejected["reason"] == "activation" and "activation_fn='sigmoid'" in rejected["detail"] and "'identity'" in rejected["detail"]


def test_export_json_that_agrees_lets_the_record_activation_reach_the_loader(tmp_path):
    checkpoint = tmp_path / "reranker-d2-v1"
    checkpoint.mkdir()
    (checkpoint / "export.json").write_text(json.dumps({"activation_fn": "identity"}), encoding="utf-8")
    d2 = record("reranker-d2-v1", path=checkpoint, activation="identity")
    loader = Loader({d2.name: FakeModel()})

    outcome = service(loader, d2).warmup()

    assert outcome.status == "loaded"
    # A `path` version implies local_files_only through loader_kwargs(), and the
    # activation string travels with it: the loader turns it into torch.nn.Identity().
    assert loader.calls == [(str(checkpoint), {"local_files_only": True, "activation": "identity"})]


def test_digest_mismatch_rejects_before_the_load_and_a_null_digest_skips_the_check(tmp_path, events):
    checkpoint = tmp_path / "reranker-d2-v1"
    checkpoint.mkdir()
    (checkpoint / "model.safetensors").write_bytes(b"weights as written")
    actual = hashlib.sha256(b"weights as written").hexdigest()
    v0 = record("reranker-v0")

    wrong = record("reranker-d2-v1", path=checkpoint, digest="0" * 64)
    loader = Loader({wrong.name: FakeModel(), v0.name: FakeModel()})
    outcome = service(loader, wrong, v0).warmup()
    assert outcome.loaded_id == "reranker-v0" and [name for name, _ in loader.calls] == [v0.name]
    assert named(events, "reranker_version_rejected")[0]["extra"]["reason"] == "digest"

    right = record("reranker-d2-v1", path=checkpoint, digest=actual)
    outcome = service(Loader({right.name: FakeModel()}), right).warmup()
    assert (outcome.loaded_id, outcome.digest_ok) == ("reranker-d2-v1", True)

    unpinned = record("reranker-d2-v1", path=checkpoint, digest=None)
    outcome = service(Loader({unpinned.name: FakeModel()}), unpinned).warmup()
    assert (outcome.loaded_id, outcome.digest_ok) == ("reranker-d2-v1", None), "null digest on a candidate = check skipped, never a rejection"

    missing = record("reranker-d2-v1", path=tmp_path / "nowhere", digest=actual)
    outcome = service(Loader({missing.name: FakeModel()}), missing).warmup()
    assert outcome.status == "rejected_all" and "missing" in outcome.reason


def test_another_head_or_window_is_rejected_after_the_load(events):
    v1, v0 = record("reranker-v1", num_labels=1, max_length=512), record("reranker-v0")
    outcome = service(Loader({v1.name: FakeModel(num_labels=2), v0.name: FakeModel()}), v1, v0).warmup()
    assert outcome.loaded_id == "reranker-v0" and named(events, "reranker_version_rejected")[-1]["extra"]["reason"] == "num_labels"

    outcome = service(Loader({v1.name: FakeModel(tokenizer_limit=8192), v0.name: FakeModel()}), v1, v0).warmup()
    assert outcome.loaded_id == "reranker-v0" and named(events, "reranker_version_rejected")[-1]["extra"]["reason"] == "max_length"

    # The real 3.4.1 shape: CrossEncoder.max_length is None, the tokenizer says 512.
    outcome = service(Loader({v1.name: FakeModel(max_length=None, tokenizer_limit=512)}), v1).warmup()
    assert outcome.loaded_id == "reranker-v1"
    # An explicit model.max_length wins over the tokenizer, as in _model_window.
    outcome = service(Loader({v1.name: FakeModel(max_length=512, tokenizer_limit=100_000_000)}), v1).warmup()
    assert outcome.loaded_id == "reranker-v1"
    # Records without the two fields do not check them.
    loose = record("reranker-v1", num_labels=None, max_length=None)
    assert service(Loader({loose.name: FakeModel(num_labels=3, tokenizer_limit=8192)}), loose).warmup().status == "loaded"


def test_a_fallback_snapshot_missing_from_the_disk_cache_is_named_not_cached(events):
    """transformers wraps huggingface_hub's LocalEntryNotFoundError in an OSError; the
    reason must say `not_cached` (a download was refused) rather than `load`."""

    class LocalEntryNotFoundError(FileNotFoundError):
        pass

    def offline_miss():
        error = OSError("We couldn't connect to 'https://huggingface.co' to load the files, and couldn't find them in the cached files.")
        error.__cause__ = LocalEntryNotFoundError("Cannot find the requested files in the disk cache and outgoing traffic has been disabled.")
        return error

    v1, v0 = record("reranker-v1"), record("reranker-v0")
    outcome = service(Loader({v1.name: RuntimeError("bad active"), v0.name: offline_miss()}), v1, v0).warmup()

    assert outcome.status == "rejected_all"
    assert [item["extra"]["reason"] for item in named(events, "reranker_version_rejected")] == ["load", "not_cached"]
    # The same error on the ACTIVE hub version (no local_files_only) is a plain load failure.
    outcome = service(Loader({v1.name: offline_miss()}), v1).warmup()
    assert named(events, "reranker_version_rejected")[-1]["extra"]["reason"] == "load"


def test_over_cap_latency_is_a_warning_that_keeps_serving(events):
    slow = record("reranker-v1", max_ms=1)
    outcome = service(Loader({slow.name: FakeModel(delay=0.02)}), slow).warmup()

    assert outcome.status == "loaded" and outcome.latency_ms is not None and outcome.latency_ms > 1
    loaded = named(events, "reranker_version_loaded")[0]
    assert loaded["level"].name == "WARNING" and loaded["extra"]["over_cap"] is True and loaded["extra"]["max_ms"] == 1


def test_timed_predict_cycles_the_probe_pairs_to_fifteen_and_no_pairs_means_no_timing():
    model = FakeModel()
    outcome = service(Loader({"hub/reranker-v1": model}), record("reranker-v1")).warmup()
    assert model.predicted == [3, 15], "parity on the 3 pairs, then the timed batch of 15"
    assert outcome.latency_ms is not None
    bare = record("reranker-v1", pairs=(), scores=None)
    outcome = service(Loader({bare.name: FakeModel()}), bare).warmup()
    assert outcome.status == "loaded" and outcome.latency_ms is None and outcome.parity_ok is None


# ── flag off / empty chain / legacy ──────────────────────────────────────────


def test_empty_chain_is_no_versions_and_never_indexed():
    reranker = RerankerService.from_config({"reranker": {"enabled": True, "candidate_limit": 7}}, enabled_override=True, versions=())
    assert reranker.enabled is False and reranker.model_name == "" and reranker.candidate_limit == 7

    outcome = reranker.warmup()  # must not raise, must not load

    assert (outcome.status, outcome.loaded_id, outcome.source) == ("no_versions", None, None)
    assert reranker.rerank("q", [{"content": "a"}, {"content": "b"}], 5) == [{"content": "a"}, {"content": "b"}]
    resolved = shipped_resolved()
    resolved.record_reranker(loaded_id=None, status="unconfigured", reason=None)
    assert not resolved.roles["reranker"].deviates and resolved.fallback_flag() == "ok"


def test_flag_off_is_off_and_not_a_deviation():
    loader = Loader({})  # any call would KeyError
    reranker = RerankerService.from_config({"reranker": {"enabled": True}}, enabled_override=False, model_loader=loader, versions=(record("reranker-v0"),))

    outcome = reranker.warmup()

    assert outcome.status == "flag_off" and loader.calls == []
    resolved = shipped_resolved()
    resolved.record_reranker(loaded_id=None, status="off", reason="RAG_RERANKER_ENABLED=false")
    assert not resolved.roles["reranker"].deviates and resolved.fallback_flag() == "ok"
    assert resolved.registry_view()["reranker"]["status"] == "off"


def test_from_config_takes_the_model_name_from_the_chain_head_and_legacy_from_the_yaml():
    v1, v0 = record("reranker-v1"), record("reranker-v0")
    assert RerankerService.from_config({"reranker": {"enabled": True}}, versions=(v1, v0)).model_name == v1.name
    assert RerankerService.from_config({"reranker": {"enabled": True, "model": "m"}}).model_name == "m"
    assert RerankerService.from_config({}).model_name == HUB_DEFAULT_MODEL
    assert RerankerService.from_config({}).versions is None


def test_legacy_single_name_service_calls_the_loader_without_kwargs_and_disables_on_failure():
    calls: list = []

    def loader(name):  # a `lambda _:` loader of the existing tests: kwargs would TypeError
        calls.append(name)
        return FakeModel()

    reranker = RerankerService(True, "fake", 15, model_loader=loader)
    outcome = reranker.warmup()
    assert calls == ["fake"] and (outcome.status, outcome.loaded_id, outcome.source) == ("loaded", "fake", "legacy")

    broken = RerankerService(True, "fake", 15, model_loader=lambda _: (_ for _ in ()).throw(RuntimeError("no weights")))
    outcome = broken.warmup()  # must not raise
    assert (outcome.status, outcome.source) == ("rejected_all", "legacy") and broken.enabled is False


# ── lazy reload and the real loader ──────────────────────────────────────────


def test_lazy_reload_goes_through_the_loaded_records_kwargs():
    v1, v0 = record("reranker-v1", revision="r1"), record("reranker-v0", revision="r0", activation="identity")
    loader = Loader({v1.name: RuntimeError("bad"), v0.name: FakeModel()})
    reranker = service(loader, v1, v0)
    reranker.warmup()
    reranker._model = None  # e.g. a later process that never warmed up

    reranker.rerank("q", [{"content": "a"}, {"content": "b"}], 1)

    assert loader.calls[-1] == (v0.name, v0.loader_kwargs()) == (v0.name, {"revision": "r0", "activation": "identity"})


def test_load_cross_encoder_passes_the_three_kwargs_and_builds_the_activation_module(monkeypatch):
    sentence_transformers = pytest.importorskip("sentence_transformers")
    torch = pytest.importorskip("torch")
    seen: dict = {}

    class FakeCrossEncoder:
        def __init__(self, name, **kwargs):
            seen.clear()
            seen.update(name=name, **kwargs)

    monkeypatch.setattr(sentence_transformers, "CrossEncoder", FakeCrossEncoder)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)

    RerankerService._load_cross_encoder("m", revision="r", local_files_only=False, activation="identity")
    assert seen["name"] == "m" and seen["revision"] == "r" and seen["local_files_only"] is False
    assert isinstance(seen["default_activation_function"], torch.nn.Identity)

    RerankerService._load_cross_encoder("m", activation="sigmoid")
    assert isinstance(seen["default_activation_function"], torch.nn.Sigmoid)

    RerankerService._load_cross_encoder("m")  # the legacy call: 3.4.1 defaults, no activation override
    assert seen == {"name": "m", "revision": None, "local_files_only": False}

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    RerankerService._load_cross_encoder("m")
    assert seen["local_files_only"] is True


def test_missing_extra_rejects_every_version_with_the_pip_hint(monkeypatch, events):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # `import` raises ImportError
    v1, v0 = record("reranker-v1"), record("reranker-v0")
    reranker = RerankerService(True, v1.name, 15, versions=(v1, v0))  # the real loader

    outcome = reranker.warmup()

    assert outcome.status == "rejected_all" and "pip install -e .[rerank]" in outcome.reason
    assert [item["extra"]["reason"] for item in named(events, "reranker_version_rejected")] == ["import", "import"]


def test_real_reranker_v0_from_the_disk_cache_passes_every_check(monkeypatch):
    """The shipped registry against the real weights, offline: acceptance C on this
    machine (reranker active with parity on the recorded scores). Skipped when the HF
    cache does not hold the pinned snapshot — the test never downloads."""
    pytest.importorskip("sentence_transformers")
    huggingface_hub = pytest.importorskip("huggingface_hub")
    chain = load_registry(DEFAULT_REGISTRY_PATH).chain("reranker")
    assert [item.id for item in chain] == ["reranker-v0"], "the candidate after `active` is never in the chain"
    v0 = chain[0]
    cached = huggingface_hub.try_to_load_from_cache(v0.hub, "config.json", revision=v0.revision)
    if not isinstance(cached, str):
        pytest.skip(f"{v0.hub}@{v0.revision} is not in the HF disk cache")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")  # loader_kwargs() -> local_files_only=True: no network

    reranker = RerankerService(True, v0.name, 15, versions=chain)
    outcome = reranker.warmup()

    assert (outcome.status, outcome.loaded_id, outcome.source, outcome.reason) == ("loaded", "reranker-v0", "active", None), outcome
    assert outcome.parity_ok is True and outcome.digest_ok is None and isinstance(outcome.latency_ms, int)
    assert reranker.loaded is v0
    ranked = reranker.rerank("thủ tục cấp lại căn cước công dân", [{"content": pair[1]} for pair in v0.probe.pairs], 3)
    assert [row["content"] for row in ranked][0] == v0.probe.pairs[0][1], "the relevant passage ranks first"
