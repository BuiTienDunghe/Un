"""Model version registry: load/validate, chain, collections, resolve() statuses.

Fixtures are built in memory from one minimal valid document so each test bends
only the field it is about; the shipped file is loaded once to lock acceptance A
(nothing changes on landing) against a LITERAL of the models.yaml blocks that the
registry replaced (git show 54bdbf7:backend/app/config/models.yaml).
"""
from __future__ import annotations

import copy
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from loguru import logger

from app.config.model_registry import (
    DEFAULT_REGISTRY_PATH,
    DEVIATING,
    MODEL_ROLES,
    QDRANT_UNREACHABLE,
    ROLES,
    ModelRegistryError,
    Overrides,
    PostgresCounts,
    ProbeOutcome,
    RoleResolution,
    derive_collections,
    load_registry,
    ollama_create_list,
    ollama_pull_list,
    overrides_from_settings,
    resolve,
    write_attention_marker,
)
from app.config.settings import PROJECT_ROOT, Settings

BACKEND = Path(__file__).resolve().parents[1]
DATABASE_URL = "postgresql+psycopg://user:password@localhost/test"

# The five `models:` blocks of models.yaml on the commit before the registry landed,
# key order included: acceptance A says the dict every router receives is these.
TODAY = {
    "general": {"provider": "ollama", "name": "qwen3.5:9b", "context": 16384, "temperature": 0.4, "top_p": 0.9, "think": False, "keep_alive": "5m"},
    "condenser": {"provider": "gemini", "name": "gemini-2.5-flash", "temperature": 0.2, "max_tokens": 4096},
    "embedding": {"provider": "ollama", "name": "qwen3-embedding:0.6b", "context": 32768, "revision": "qwen3-embedding-0.6b-r1", "normalization": "raw", "dimensions": 1024},
    "vision": {"provider": "ollama", "name": "qwen3.5:9b", "context": 16384, "temperature": 0.3, "keep_alive": "5m"},
    "ocr": {"provider": "ollama", "name": "glm-ocr:latest", "enabled": True, "context": 16384, "temperature": 0.1, "keep_alive": "5m",
            "prompt": "Text Recognition:", "dpi": 200, "min_text_characters": 80, "min_alphanumeric_ratio": 0.45},
}

ALL_TAGS = {"qwen3.5:9b": "sha256:a", "qwen3-embedding:0.6b": "sha256:b", "glm-ocr:latest": "sha256:c"}
# The default flags of a fresh checkout: condenser, extractor and verifier are off.
FLAGS_OFF = frozenset({"condenser", "extractor", "verifier"})


def _settings(**overrides) -> Settings:
    return Settings(database_url=DATABASE_URL, _env_file=None, **overrides)


def base_document() -> dict:
    return {
        "schema_version": 1,
        "budget": {"vram_mib": 16311},
        "roles": {
            "general": {"active": "general-v0", "versions": [
                {"id": "general-v0", "provider": "ollama", "vram_mib": 6407,
                 "config": {"provider": "ollama", "name": "qwen3.5:9b", "context": 16384}}]},
            "condenser": {"active": "condenser-v0", "versions": [
                {"id": "condenser-v0", "provider": "gemini", "config": {"provider": "gemini", "name": "gemini-2.5-flash"}}]},
            "embedding": {"active": "embedding-v0", "versions": [
                {"id": "embedding-v0", "provider": "ollama", "collection_suffix": "", "vram_mib": 2870,
                 "config": {"provider": "ollama", "name": "qwen3-embedding:0.6b", "revision": "r1", "normalization": "raw", "dimensions": 1024}}]},
            "vision": {"active": None, "versions": [
                {"id": "vision-v0", "provider": "ollama", "config": {"provider": "ollama", "name": "qwen3.5:9b"}}]},
            "ocr": {"active": "ocr-v0", "versions": [
                {"id": "ocr-v0", "provider": "ollama", "config": {"provider": "ollama", "name": "glm-ocr:latest", "enabled": True}}]},
            "reranker": {"active": "reranker-v0", "versions": [
                {"id": "reranker-v0", "provider": "sentence-transformers", "hub": "cross-encoder/x", "revision": "abc",
                 "vram_mib": 643, "probe": {"pairs": [["q", "p"]], "scores": None}}]},
            "extractor": {"active": "extractor-v0", "versions": [
                {"id": "extractor-v0", "provider": "ollama", "vram_mib": 0, "config": {"provider": "ollama", "name": "qwen3.5:9b"}}]},
            "verifier": {"active": "verifier-v0", "versions": [
                {"id": "verifier-v0", "provider": "ollama", "vram_mib": 0, "config": {"provider": "ollama", "name": "qwen3.5:9b"}}]},
        },
    }


def add_version(document: dict, role: str, record: dict, *, active: bool = True) -> dict:
    document["roles"][role]["versions"].append(record)
    if active:
        document["roles"][role]["active"] = record["id"]
    return document


def general_v1(name: str = "qwen4:9b", **extra) -> dict:
    return {"id": "general-v1", "provider": "ollama", "vram_mib": 6000, "config": {"provider": "ollama", "name": name}, **extra}


def embedding_e5l(**extra) -> dict:
    return {"id": "embedding-e5l-v1", "provider": "ollama", "collection_suffix": "e5l", "vram_mib": 1200,
            "config": {"provider": "ollama", "name": "e5:large", "revision": "e5-r1", "normalization": "raw", "dimensions": 1024}, **extra}


def write_registry(tmp_path: Path, document: dict, name: str = "registry.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def load(tmp_path: Path, document: dict):
    return load_registry(write_registry(tmp_path, document))


class FakeProbes:
    """Recording fake: every answer is a constructor argument, every call is logged."""

    def __init__(self, *, tags=ALL_TAGS, width=1024, dims=None, points=None, counts=PostgresCounts(0, 0), qdrant_down=False):
        self.tags, self.width, self.counts, self.qdrant_down = tags, width, counts, qdrant_down
        self.dims = {} if dims is None else dims
        self.points = {} if points is None else points
        self.calls: list[object] = []

    def ollama_tags(self):
        self.calls.append("tags")
        return self.tags

    def ollama_embed_dimension(self, model):
        self.calls.append(("embed", model))
        return self.width

    def qdrant_dimension(self, collection):
        self.calls.append(("dim", collection))
        return QDRANT_UNREACHABLE if self.qdrant_down else self.dims.get(collection)

    def qdrant_point_count(self, collection):
        self.calls.append(("count", collection))
        return QDRANT_UNREACHABLE if self.qdrant_down else self.points.get(collection, 0)

    def postgres_counts(self):
        self.calls.append("counts")
        return self.counts


def ready_probes(**overrides) -> FakeProbes:
    """Everything present and consistent: the state acceptance C describes."""
    defaults = dict(dims={"documents": 1024, "memories": 1024}, points={"documents": 10, "memories": 3}, counts=PostgresCounts(10, 3))
    defaults.update(overrides)
    return FakeProbes(**defaults)


# ── the shipped file (acceptance A) ─────────────────────────────────────────────

def test_shipped_registry_loads_every_role_with_todays_pointers():
    registry = load_registry()
    assert registry.path == DEFAULT_REGISTRY_PATH
    assert tuple(registry.roles) == ROLES
    assert {role: entry.active for role, entry in registry.roles.items()} == {
        "general": "general-v0", "condenser": "condenser-v0", "embedding": "embedding-v0", "vision": None,
        "ocr": "ocr-v0", "reranker": "reranker-v0", "extractor": "extractor-v0", "verifier": "verifier-v0",
    }
    assert registry.get("embedding", "embedding-v0").collection_suffix == ""
    assert registry.get("embedding", "embedding-e5l-v1").collection_suffix == "e5l"
    reranker = registry.get("reranker", "reranker-v0")
    assert reranker.hub == "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1" and reranker.revision
    assert reranker.probe is not None and len(reranker.probe.scores) == len(reranker.probe.pairs) == 3


def test_flat_models_equals_the_models_yaml_blocks_the_registry_replaced():
    resolved = resolve(load_registry(), Overrides(disabled_roles=FLAGS_OFF))
    flat = resolved.flat_models()
    # Four blocks are served verbatim, key order included (the embedding cache
    # fingerprints every key, so order-insensitive equality would not be enough).
    for role in ("general", "condenser", "embedding", "ocr"):
        assert list(flat[role].items()) == list(TODAY[role].items()), role
    # vision: active null = not served, so the block is absent from the served dict
    # but still recorded verbatim under its version id.
    assert "vision" not in flat
    assert list(resolved.registry.get("vision", "vision-v0").config.items()) == list(TODAY["vision"].items())
    # extractor / verifier carry config too (MODEL_ROLES); they were env-only before.
    assert flat["extractor"] == {"provider": "ollama", "name": "qwen3.5:9b"}
    assert flat["verifier"] == {"provider": "ollama", "name": "qwen3.5:9b"}
    assert set(flat) == set(MODEL_ROLES) - {"vision"}
    assert resolved.flat_models() is flat, "flat_models() must hand every caller the same object"


def test_load_models_is_identical_across_settings_instances():
    first, second = _settings(), _settings()
    assert first.load_models() == second.load_models()
    assert first.load_models() is first.load_models()
    assert first.qdrant_collections() == first.resolve_models().collections


def test_shipped_pull_list_is_exactly_what_the_launcher_pulled_by_hand():
    registry = load_registry()
    overrides = Overrides(disabled_roles=FLAGS_OFF)
    assert ollama_pull_list(registry, overrides) == ["qwen3.5:9b", "qwen3-embedding:0.6b", "glm-ocr:latest"]
    assert ollama_create_list(registry, overrides) == []


def test_import_leaves_pydantic_out_of_sys_modules():
    """The CI static job runs --check with stdlib + PyYAML only."""
    code = "import sys, app.config.model_registry; print(sorted(m for m in sys.modules if m.split('.')[0] in {'pydantic', 'pydantic_settings', 'httpx', 'sqlalchemy', 'qdrant_client'}))"
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True,
                            env={**os.environ, "PYTHONUTF8": "1"}, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


# ── load_registry validation ────────────────────────────────────────────────────

def _reserved_in_config(document):
    document["roles"]["embedding"]["versions"][0]["config"]["collection_suffix"] = "x"


def _two_suffixes(document, first, second):
    document["roles"]["embedding"]["versions"][0]["collection_suffix"] = first
    add_version(document, "embedding", embedding_e5l(collection_suffix=second), active=False)


@pytest.mark.parametrize(
    ("label", "mutate", "fragment"),
    [
        ("schema_version", lambda d: d.update(schema_version=2), "schema_version must be 1"),
        ("budget", lambda d: d.pop("budget"), "budget.vram_mib"),
        ("unknown role", lambda d: d["roles"].update(painter={"active": None, "versions": []}), "unknown role(s) painter"),
        ("missing role", lambda d: d["roles"].pop("verifier"), "missing role(s) verifier"),
        ("embedding active null", lambda d: d["roles"]["embedding"].update(active=None), "roles.embedding: active must not be null"),
        ("duplicate id", lambda d: add_version(d, "general", general_v1() | {"id": "general-v0"}), "duplicate version id(s) general-v0"),
        ("active unknown", lambda d: d["roles"]["general"].update(active="general-v9"), "active='general-v9' is not among the ids"),
        ("empty versions", lambda d: d["roles"]["vision"].update(versions=[]), "versions must be a non-empty list"),
        ("config missing", lambda d: d["roles"]["general"]["versions"][0].pop("config"), "id=general-v0: config must be a mapping"),
        ("reranker with config", lambda d: d["roles"]["reranker"]["versions"][0].update(config={"provider": "sentence-transformers", "name": "x"}), "no config block"),
        ("reserved key inside config", _reserved_in_config, "config carries registry key(s) collection_suffix"),
        ("config.provider mismatch", lambda d: d["roles"]["general"]["versions"][0]["config"].update(provider="gemini"), "config.provider 'gemini' != provider 'ollama'"),
        ("provider unknown", lambda d: d["roles"]["general"]["versions"][0].update(provider="openai"), "provider must be one of"),
        ("suffix charset", lambda d: d["roles"]["embedding"]["versions"][0].update(collection_suffix="E5L"), "collection_suffix must match [a-z0-9_]*"),
        ("suffix duplicated", lambda d: _two_suffixes(d, "e5l", "e5l"), "collection_suffix e5l is shared by two versions"),
        ("empty suffix twice", lambda d: _two_suffixes(d, "", ""), "collection_suffix '' is shared by two versions"),
        ("suffix missing", lambda d: d["roles"]["embedding"]["versions"][0].pop("collection_suffix"), "must declare collection_suffix"),
        ("hub and path", lambda d: d["roles"]["reranker"]["versions"][0].update(path="data/models/reranker/x"), "exactly one of hub | path"),
        ("neither hub nor path", lambda d: d["roles"]["reranker"]["versions"][0].pop("hub"), "exactly one of hub | path"),
        ("hub without revision", lambda d: d["roles"]["reranker"]["versions"][0].pop("revision"), "must pin a revision"),
        ("activation", lambda d: d["roles"]["reranker"]["versions"][0].update(activation="relu"), "activation must be identity, sigmoid or null"),
        ("scores length", lambda d: d["roles"]["reranker"]["versions"][0]["probe"].update(scores=[1.0, 2.0]), "probe.scores has 2 entries for 1 pairs"),
        ("ollama.source", lambda d: d["roles"]["general"]["versions"][0].update(ollama={"source": "docker"}), "ollama.source must be hub or modelfile"),
        ("modelfile missing", lambda d: d["roles"]["general"]["versions"][0].update(ollama={"source": "modelfile"}), "needs ollama.modelfile"),
        ("eval gate", lambda d: d["roles"]["general"]["versions"][0].update(eval={"reports": {"vibes": None}}), "gate 'vibes' is not one of"),
        ("id charset", lambda d: d["roles"]["general"]["versions"][0].update(id="general v0"), "id must match"),
    ],
)
def test_load_registry_refuses_and_names_file_role_id(tmp_path, label, mutate, fragment):
    document = base_document()
    mutate(document)
    with pytest.raises(ModelRegistryError) as caught:
        load(tmp_path, document)
    assert fragment in str(caught.value), label
    assert "registry.yaml" in str(caught.value), "the message must name the file"


def test_load_registry_names_a_missing_file(tmp_path):
    with pytest.raises(ModelRegistryError, match="cannot read the model registry"):
        load_registry(tmp_path / "absent.yaml")


def test_provider_and_revision_are_legitimate_config_members(tmp_path):
    """The draft's reserved set rejected the shipped file; both keys belong to the cache identity."""
    registry = load(tmp_path, base_document())
    assert registry.get("embedding", "embedding-v0").config["revision"] == "r1"
    assert registry.get("embedding", "embedding-v0").config["provider"] == "ollama"


def test_relative_paths_resolve_against_project_root(tmp_path):
    document = base_document()
    add_version(document, "extractor", {
        "id": "extractor-d2", "provider": "ollama", "vram_mib": None,
        "ollama": {"source": "modelfile", "modelfile": "data/models/extractor/extractor-d2/Modelfile", "gguf_sha256": None},
        "eval": {"reports": {"extractor_benchmark": "data/benchmarks/x.json"}},
        "config": {"provider": "ollama", "name": "local-ai/student:d2"}}, active=False)
    record = load(tmp_path, document).get("extractor", "extractor-d2")
    assert record.ollama.modelfile == PROJECT_ROOT / "data/models/extractor/extractor-d2/Modelfile"
    assert record.eval_reports["extractor_benchmark"] == PROJECT_ROOT / "data/benchmarks/x.json"


# ── chain() ─────────────────────────────────────────────────────────────────────

def test_chain_walks_earlier_versions_nearest_first_and_skips_fallback_false(tmp_path):
    document = base_document()
    add_version(document, "general", general_v1(fallback=False))
    add_version(document, "general", general_v1() | {"id": "general-v2"})
    registry = load(tmp_path, document)
    assert [record.id for record in registry.chain("general")] == ["general-v2", "general-v0"]
    assert [record.id for record in registry.chain("general", "general-v1")] == ["general-v1", "general-v0"]
    with pytest.raises(ModelRegistryError, match="roles.general: no version with id='general-v9'"):
        registry.get("general", "general-v9")


def test_chain_never_includes_candidates_listed_after_the_active_version(tmp_path):
    document = base_document()
    add_version(document, "general", general_v1(), active=False)
    assert [record.id for record in load(tmp_path, document).chain("general")] == ["general-v0"]


def test_chain_is_one_for_embedding_and_empty_when_active_is_null(tmp_path):
    document = base_document()
    add_version(document, "embedding", embedding_e5l())
    registry = load(tmp_path, document)
    assert [record.id for record in registry.chain("embedding")] == ["embedding-e5l-v1"]
    assert registry.chain("vision") == ()


# ── derive_collections ──────────────────────────────────────────────────────────

def test_collections_compose_base_and_suffix_active_first(tmp_path):
    document = base_document()
    add_version(document, "embedding", embedding_e5l(), active=False)
    registry = load(tmp_path, document)
    lab = derive_collections(registry, Overrides(documents_collection="documents_lab", memories_collection="memories_lab"))
    assert (lab.documents, lab.memories) == ("documents_lab", "memories_lab")
    assert lab.all_documents == ("documents_lab", "documents_lab_e5l")
    assert lab.all_memories == ("memories_lab", "memories_lab_e5l")
    pinned = derive_collections(registry, Overrides(pins={"embedding": "embedding-e5l-v1"}))
    assert pinned.documents == "documents_e5l"
    assert pinned.all_documents == ("documents_e5l", "documents"), "the pointer's collection leads the sweep"


def test_env_base_that_aliases_a_versions_collection_refuses(tmp_path):
    document = base_document()
    add_version(document, "embedding", embedding_e5l(), active=False)
    registry = load(tmp_path, document)
    with pytest.raises(ModelRegistryError, match="QDRANT_DOCUMENTS_COLLECTION='documents_e5l' ends with _e5l"):
        derive_collections(registry, Overrides(documents_collection="documents_e5l"))


def test_unknown_embedding_pin_names_the_variable(tmp_path):
    registry = load(tmp_path, base_document())
    with pytest.raises(ModelRegistryError, match="MODEL_VERSION_EMBEDDING='embedding-v9' names no version"):
        derive_collections(registry, Overrides(pins={"embedding": "embedding-v9"}))


def test_resolve_and_derive_collections_agree(tmp_path):
    document = base_document()
    add_version(document, "embedding", embedding_e5l())
    registry = load(tmp_path, document)
    overrides = Overrides(documents_collection="documents_lab", disabled_roles=FLAGS_OFF)
    assert resolve(registry, overrides).collections == derive_collections(registry, overrides)
    probed = resolve(registry, overrides, ready_probes(tags=ALL_TAGS | {"e5:large": "sha256:e"}, dims={"documents_lab_e5l": 1024, "memories_e5l": 1024}, counts=PostgresCounts(0, 0)))
    assert probed.collections == derive_collections(registry, overrides)
    assert probed.roles["embedding"].status == "active"


# ── resolve(): pointer, flags, no probes ────────────────────────────────────────

def test_without_probes_every_pointer_is_active_and_unverified(tmp_path):
    resolved = resolve(load(tmp_path, base_document()), Overrides(disabled_roles=FLAGS_OFF))
    statuses = {role: resolution.status for role, resolution in resolved.roles.items()}
    assert statuses == {"general": "active", "condenser": "off", "embedding": "active", "vision": "unconfigured",
                        "ocr": "active", "reranker": "active", "extractor": "off", "verifier": "off"}
    assert all(not resolution.verified for resolution in resolved.roles.values())
    assert resolved.roles["general"].loaded_id == "general-v0"
    assert resolved.roles["general"].probe.kind == "skipped"
    assert resolved.probed is False
    assert resolved.fallback_flag() == "ok" and resolved.attention_text() is None
    assert resolved.embedding_refusal() is None
    assert resolved.embedding_version_id() == "embedding-v0"
    assert resolved.model_name("general") == "qwen3.5:9b" and resolved.model_name("reranker") is None and resolved.model_name("vision") is None


def test_flag_off_roles_are_off_not_deviating_and_keep_their_config(tmp_path):
    resolved = resolve(load(tmp_path, base_document()), Overrides(disabled_roles=FLAGS_OFF), ready_probes())
    extractor = resolved.roles["extractor"]
    assert extractor.status == "off" and not extractor.deviates and not extractor.serving
    assert extractor.reason == "DISCORD_MEMORY_EXTRACTOR_ENABLED=false"
    assert extractor.loaded_id is None and extractor.record.id == "extractor-v0"
    assert resolved.flat_models()["extractor"]["name"] == "qwen3.5:9b"
    assert resolved.roles["condenser"].reason == "DISCORD_CONDENSATION_ENABLED=false"


def test_ocr_disabled_in_the_file_is_off_without_a_probe(tmp_path):
    document = base_document()
    document["roles"]["ocr"]["versions"][0]["config"]["enabled"] = False
    probes = ready_probes(tags={"qwen3.5:9b": "a", "qwen3-embedding:0.6b": "b"})   # ocr tag absent too
    ocr = resolve(load(tmp_path, document), Overrides(disabled_roles=FLAGS_OFF), probes).roles["ocr"]
    assert ocr.status == "off" and ocr.reason == "config.enabled=false" and not ocr.deviates
    assert ocr.flat_config["enabled"] is False


def test_unconfigured_role_has_no_record_and_no_probe(tmp_path):
    vision = resolve(load(tmp_path, base_document()), Overrides(disabled_roles=FLAGS_OFF), ready_probes()).roles["vision"]
    assert vision.status == "unconfigured" and vision.record is None and vision.chain == () and vision.probe is None
    assert vision.requested_id is None and vision.flat_config is None and not vision.deviates


def test_env_pin_selects_source_env_and_unknown_pin_names_the_variable(tmp_path):
    document = base_document()
    add_version(document, "general", general_v1(), active=False)
    registry = load(tmp_path, document)
    general = resolve(registry, Overrides(pins={"general": "general-v1"}, disabled_roles=FLAGS_OFF)).roles["general"]
    assert (general.requested_id, general.source, general.loaded_id) == ("general-v1", "env", "general-v1")
    assert [record.id for record in general.chain] == ["general-v1", "general-v0"]
    with pytest.raises(ModelRegistryError, match="MODEL_VERSION_GENERAL='general-v9' names no version of roles.general"):
        resolve(registry, Overrides(pins={"general": "general-v9"}))


def test_raw_tag_is_a_synthetic_record_with_a_chain_of_one(tmp_path):
    registry = load(tmp_path, base_document())
    tag = "local-ai/student:d2"
    overrides = Overrides(raw_tags={"extractor": tag}, disabled_roles=frozenset({"condenser", "verifier"}))
    extractor = resolve(registry, overrides, ready_probes(tags=ALL_TAGS | {tag: "sha256:s"})).roles["extractor"]
    assert (extractor.requested_id, extractor.source, extractor.status, extractor.loaded_id) == (f"env:{tag}", "env_tag", "active", f"env:{tag}")
    assert len(extractor.chain) == 1 and extractor.record.config == {"provider": "ollama", "name": tag}
    assert resolve(registry, overrides).flat_models()["extractor"]["name"] == tag
    # Tag absent: no fallback for an ad-hoc pin, the role is disabled.
    disabled = resolve(registry, overrides, ready_probes()).roles["extractor"]
    assert disabled.status == "disabled" and disabled.deviates and not disabled.serving
    # A registry pin outranks the tag pin (Settings refuses both anyway).
    pinned = resolve(registry, replace(overrides, pins={"extractor": "extractor-v0"}), ready_probes()).roles["extractor"]
    assert pinned.source == "env" and pinned.requested_id == "extractor-v0"


# ── resolve(): Ollama roles with probes ─────────────────────────────────────────

def test_ollama_down_keeps_every_pointer_unverified_with_one_tags_call(tmp_path):
    probes = FakeProbes(tags=None)
    resolved = resolve(load(tmp_path, base_document()), Overrides(disabled_roles=FLAGS_OFF), probes)
    for role in ("general", "embedding", "ocr"):
        resolution = resolved.roles[role]
        assert resolution.status == "unverified" and resolution.loaded_id == resolution.requested_id, role
        assert resolution.serving and not resolution.deviates and not resolution.verified
    assert probes.calls.count("tags") == 1
    assert resolved.fallback_flag() == "ok"


def test_absent_tag_falls_back_to_the_previous_version_and_says_so(tmp_path):
    document = base_document()
    add_version(document, "general", general_v1())
    resolved = resolve(load(tmp_path, document), Overrides(disabled_roles=FLAGS_OFF), ready_probes())
    general = resolved.roles["general"]
    assert general.status == "fallback" and general.loaded_id == "general-v0" and general.requested_id == "general-v1"
    assert general.reason == "general-v1 tag qwen4:9b absent from /api/tags; serving general-v0"
    assert general.deviates and general.serving and general.verified
    assert resolved.flat_models()["general"]["name"] == "qwen3.5:9b", "the served config is the loaded version's"
    assert resolved.fallback_flag() == "fallback"
    assert resolved.registry_view()["general"] == {
        "active": "general-v1", "requested": "general-v1", "loaded": "general-v0", "source": "registry", "status": "fallback",
        "reason": general.reason, "verified": True, "name": "qwen3.5:9b", "digest": None, "fallback": True,
    }
    text = resolved.attention_text()
    assert "general: requested=general-v1 loaded=general-v0 status=fallback" in text
    assert "MODEL_VERSION_GENERAL=general-v0" in text and "run-local-ai-core.bat" in text


def test_fallback_walk_skips_fallback_false_and_stops_at_the_first_present_tag(tmp_path):
    document = base_document()
    document["roles"]["general"]["versions"][0]["fallback"] = False
    add_version(document, "general", general_v1("qwen-b:1b"))
    add_version(document, "general", general_v1("qwen-c:1b") | {"id": "general-v2"})
    tags = ALL_TAGS | {"qwen-b:1b": "sha256:bb"}
    general = resolve(load(tmp_path, document), Overrides(disabled_roles=FLAGS_OFF), ready_probes(tags=tags)).roles["general"]
    assert general.loaded_id == "general-v1" and general.status == "fallback"


def test_exhausted_chain_is_missing_for_general_and_keeps_the_pointer(tmp_path):
    document = base_document()
    add_version(document, "general", general_v1())
    tags = {"qwen3-embedding:0.6b": "sha256:b", "glm-ocr:latest": "sha256:c"}
    resolved = resolve(load(tmp_path, document), Overrides(disabled_roles=FLAGS_OFF), ready_probes(tags=tags))
    general = resolved.roles["general"]
    assert general.status == "missing" and general.loaded_id is None and general.deviates and not general.serving
    assert general.record.id == "general-v1" and "absent from /api/tags" in general.reason and "general-v0" in general.reason
    assert resolved.flat_models()["general"]["name"] == "qwen4:9b", "first use must still 502 MODEL_NOT_LOADED with the pointer's tag"


def test_digest_mismatch_treats_the_version_as_absent(tmp_path):
    document = base_document()
    document["roles"]["general"]["versions"][0]["digest"] = "sha256:not-what-the-server-has"
    registry = load(tmp_path, document)
    general = resolve(registry, Overrides(disabled_roles=FLAGS_OFF), ready_probes()).roles["general"]
    assert general.status == "missing" and "digest_mismatch" in general.reason
    matching = resolve(registry, Overrides(disabled_roles=FLAGS_OFF), ready_probes(tags=ALL_TAGS | {"qwen3.5:9b": "sha256:not-what-the-server-has"})).roles["general"]
    assert matching.status == "active" and matching.probe.kind == "tags+digest"


def test_ocr_without_its_tag_is_disabled_and_its_served_copy_says_enabled_false(tmp_path):
    tags = {"qwen3.5:9b": "sha256:a", "qwen3-embedding:0.6b": "sha256:b"}
    resolved = resolve(load(tmp_path, base_document()), Overrides(disabled_roles=FLAGS_OFF), ready_probes(tags=tags))
    ocr = resolved.roles["ocr"]
    assert ocr.status == "disabled" and ocr.deviates and not ocr.serving
    assert ocr.flat_config["enabled"] is False and resolved.flat_models()["ocr"]["enabled"] is False
    assert resolved.registry.get("ocr", "ocr-v0").config["enabled"] is True, "the record itself is never edited"


def test_enabled_extractor_without_its_tag_is_disabled(tmp_path):
    tags = {"qwen3-embedding:0.6b": "sha256:b", "glm-ocr:latest": "sha256:c"}
    extractor = resolve(load(tmp_path, base_document()), Overrides(disabled_roles=frozenset({"condenser", "verifier"})), ready_probes(tags=tags)).roles["extractor"]
    assert extractor.status == "disabled" and extractor.record.id == "extractor-v0" and extractor.deviates


def test_cloud_provider_passes_only_when_registered(tmp_path):
    registry = load(tmp_path, base_document())
    on = Overrides(disabled_roles=frozenset({"extractor", "verifier"}))
    disabled = resolve(registry, on, ready_probes()).roles["condenser"]
    assert disabled.status == "disabled" and "not registered" in disabled.reason and disabled.probe.kind == "provider"
    active = resolve(registry, replace(on, registered_providers=frozenset({"ollama", "gemini"})), ready_probes()).roles["condenser"]
    assert active.status == "active" and active.verified


def test_general_on_an_unregistered_cloud_provider_falls_back_to_the_local_version(tmp_path):
    document = base_document()
    add_version(document, "general", {"id": "general-v1", "provider": "gemini", "vram_mib": 0, "config": {"provider": "gemini", "name": "gemini-2.5-pro"}})
    general = resolve(load(tmp_path, document), Overrides(disabled_roles=FLAGS_OFF), ready_probes()).roles["general"]
    assert general.status == "fallback" and general.loaded_id == "general-v0" and "gemini not registered" in general.reason


# ── resolve(): embedding (acceptance G) ─────────────────────────────────────────

@pytest.mark.parametrize(
    ("label", "probe_kwargs", "overrides_kwargs", "status", "fragment"),
    [
        ("probe width != dimensions", dict(width=768), {}, "degraded", "width 768, config.dimensions is 1024"),
        ("collection width != dimensions", dict(dims={"documents": 768, "memories": 1024}), {}, "degraded", "collection documents has width 768"),
        ("documents absent, corpus non-empty", dict(dims={"memories": 1024}), {}, "degraded", "documents does not exist while active chunks = 10; run python -m scripts.rebuild_qdrant --missing-only"),
        ("memories absent, rows non-empty", dict(dims={"documents": 1024}), {}, "degraded", "memories does not exist while memories rows = 3; run python -m scripts.rebuild_memories --missing-only"),
        ("both absent, fresh install", dict(dims={}, points={}, counts=PostgresCounts(0, 0)), {}, "active", None),
        ("absent, Postgres silent", dict(dims={}, counts=None), {}, "unverified", "Postgres did not answer"),
        ("Qdrant silent", dict(qdrant_down=True), {}, "unverified", "Qdrant did not answer"),
        ("probe embed silent", dict(width=None), {}, "unverified", "probe embed did not answer"),
        ("documents short", dict(points={"documents": 5, "memories": 3}), {}, "incomplete", "documents holds 5 points for 10 active chunks; run python -m scripts.rebuild_qdrant --missing-only with MODEL_VERSION_EMBEDDING=embedding-v0"),
        ("memories short", dict(points={"documents": 10, "memories": 1}), {}, "incomplete", "memories holds 1 points for 3 memories rows; run python -m scripts.rebuild_memories --missing-only with MODEL_VERSION_EMBEDDING=embedding-v0"),
        ("degraded wins over incomplete", dict(points={"documents": 5, "memories": 3}, dims={"documents": 1024, "memories": 512}), {}, "degraded", "memories has width 512"),
        ("rebuild: absent is fine", dict(dims={}), dict(allow_missing_collections=True), "active", None),
        ("rebuild: completeness skipped", dict(points={"documents": 0, "memories": 0}), dict(allow_missing_collections=True), "active", None),
        ("rebuild: width still checked", dict(width=768), dict(allow_missing_collections=True), "degraded", "width 768"),
    ],
)
def test_embedding_probe_table(tmp_path, label, probe_kwargs, overrides_kwargs, status, fragment):
    probes = ready_probes(**probe_kwargs)
    resolved = resolve(load(tmp_path, base_document()), Overrides(disabled_roles=FLAGS_OFF, **overrides_kwargs), probes)
    embedding = resolved.roles["embedding"]
    assert embedding.status == status, (label, embedding.reason)
    assert embedding.requested_id == embedding.record.id == "embedding-v0", "the pointer is always kept"
    if fragment:
        assert fragment in embedding.reason, (label, embedding.reason)
    if status == "degraded":
        assert embedding.loaded_id is None and not embedding.serving and embedding.deviates
        assert resolved.embedding_refusal() == embedding.reason
    elif status == "incomplete":
        assert embedding.loaded_id == "embedding-v0" and embedding.serving and embedding.deviates and embedding.verified
    elif status == "unverified":
        assert embedding.loaded_id == "embedding-v0" and embedding.serving and not embedding.deviates and not embedding.verified
    else:
        assert embedding.loaded_id == "embedding-v0" and embedding.verified and not embedding.deviates
    if status != "degraded":
        assert resolved.embedding_refusal() is None
    assert probes.calls.count(("embed", "qwen3-embedding:0.6b")) == (1 if probes.tags else 0)


def test_embedding_never_falls_back(tmp_path):
    document = base_document()
    add_version(document, "embedding", embedding_e5l())
    probes = ready_probes(dims={"documents_e5l": 1024, "memories_e5l": 1024})   # e5:large is NOT in ALL_TAGS; v0's tag is
    resolved = resolve(load(tmp_path, document), Overrides(disabled_roles=FLAGS_OFF), probes)
    embedding = resolved.roles["embedding"]
    assert embedding.status == "missing" and embedding.loaded_id is None and embedding.record.id == "embedding-e5l-v1"
    assert len(embedding.chain) == 1 and embedding.deviates
    assert resolved.collections.documents == "documents_e5l", "collections still follow the pointer"
    assert not any(call == ("embed", "qwen3-embedding:0.6b") for call in probes.calls), "v0 was never probed"


# ── reranker + record_reranker ──────────────────────────────────────────────────

def test_reranker_is_pending_until_warmup_reports_back(tmp_path):
    document = base_document()
    add_version(document, "reranker", {"id": "reranker-v1", "provider": "sentence-transformers", "path": "data/models/reranker/reranker-v1",
                                       "activation": "identity", "vram_mib": 700, "probe": {"pairs": [["q", "p"]], "scores": [1.0]}})
    resolved = resolve(load(tmp_path, document), Overrides(disabled_roles=FLAGS_OFF), ready_probes())
    reranker = resolved.roles["reranker"]
    assert reranker.status == "pending" and reranker.loaded_id is None and not reranker.deviates and not reranker.serving
    assert [record.id for record in resolved.reranker_chain()] == ["reranker-v1", "reranker-v0"]
    assert resolved.fallback_flag() == "ok"

    resolved.record_reranker(loaded_id="reranker-v0", status="fallback", reason="reranker-v1 not_cached; serving reranker-v0", latency_ms=42)
    resolved.record_reranker(loaded_id="reranker-v0", status="fallback", reason="reranker-v1 not_cached; serving reranker-v0", latency_ms=42)
    reranker = resolved.roles["reranker"]
    assert reranker.status == "fallback" and reranker.loaded_id == "reranker-v0" and reranker.record.id == "reranker-v0"
    assert reranker.verified and reranker.deviates and reranker.serving
    view = resolved.registry_view()["reranker"]
    assert view["loaded"] == "reranker-v0" and view["fallback"] is True and view["latency_ms"] == 42 and view["name"] == "cross-encoder/x"
    assert resolved.fallback_flag() == "fallback" and "reranker: requested=reranker-v1 loaded=reranker-v0" in resolved.attention_text()
    assert resolved.flat_models().get("reranker") is None, "the reranker carries no flat block"

    resolved.record_reranker(loaded_id=None, status="off", reason=None)
    assert resolved.roles["reranker"].status == "off" and not resolved.roles["reranker"].verified and resolved.fallback_flag() == "ok"


def test_reranker_active_null_is_unconfigured_with_an_empty_chain(tmp_path):
    document = base_document()
    document["roles"]["reranker"]["active"] = None
    resolved = resolve(load(tmp_path, document), Overrides(disabled_roles=FLAGS_OFF), ready_probes())
    assert resolved.roles["reranker"].status == "unconfigured" and resolved.reranker_chain() == ()


def test_loader_kwargs_carry_only_what_the_record_sets(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    document = base_document()
    add_version(document, "reranker", {"id": "reranker-v1", "provider": "sentence-transformers", "path": "data/models/reranker/reranker-v1",
                                       "activation": "identity", "digest": {"file": "model.safetensors", "sha256": "abc"},
                                       "probe": {"pairs": [], "scores": None}}, active=False)
    registry = load(tmp_path, document)
    hub, local = registry.get("reranker", "reranker-v0"), registry.get("reranker", "reranker-v1")
    assert hub.loader_kwargs() == {"revision": "abc"} and hub.name == "cross-encoder/x"
    assert local.loader_kwargs() == {"local_files_only": True, "activation": "identity"}
    assert local.path == PROJECT_ROOT / "data/models/reranker/reranker-v1" and local.name == str(local.path)
    assert local.digest == "abc" and local.digest_file == "model.safetensors"
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    assert hub.loader_kwargs() == {"revision": "abc", "local_files_only": True}
    assert registry.get("ocr", "ocr-v0").ollama_tag == "glm-ocr:latest"
    assert registry.get("general", "general-v0").ollama_tag == "qwen3.5:9b"


# ── predicates, view, marker, logging ───────────────────────────────────────────

@pytest.mark.parametrize("status", ["active", "fallback", "unverified", "missing", "degraded", "incomplete", "disabled", "off", "unconfigured", "pending"])
def test_deviates_and_serving_are_the_two_fixed_sets(status):
    resolution = RoleResolution("general", "x", "registry", None, status, None, None, (), None, False)
    assert resolution.deviates is (status in {"fallback", "missing", "degraded", "incomplete", "disabled"})
    assert resolution.serving is (status in {"active", "fallback", "unverified", "incomplete"})
    assert DEVIATING == frozenset({"fallback", "missing", "degraded", "incomplete", "disabled"})


def test_registry_view_lists_eight_roles_with_collections_and_latency(tmp_path):
    view = resolve(load(tmp_path, base_document()), Overrides(disabled_roles=FLAGS_OFF)).registry_view()
    assert tuple(view) == ROLES
    assert view["embedding"]["collections"] == {"documents": "documents", "memories": "memories"}
    assert "collections" not in view["general"] and "latency_ms" not in view["general"]
    assert view["reranker"]["latency_ms"] is None
    assert view["vision"] == {"active": None, "requested": None, "loaded": None, "source": "registry", "status": "unconfigured",
                              "reason": None, "verified": False, "name": None, "digest": None, "fallback": False}
    assert all(row["fallback"] is False for row in view.values())


def test_attention_marker_is_written_on_deviation_and_removed_otherwise(tmp_path):
    document = base_document()
    add_version(document, "general", general_v1())
    registry = load(tmp_path, document)
    logs = tmp_path / "logs"
    fallen = resolve(registry, Overrides(disabled_roles=FLAGS_OFF), ready_probes())
    marker = write_attention_marker(fallen, logs)
    assert marker == logs / "ATTENTION_model_fallback.txt" and marker.is_file()
    assert "MODEL_VERSION_GENERAL=general-v0" in marker.read_text(encoding="utf-8")
    healthy = resolve(registry, Overrides(disabled_roles=FLAGS_OFF), ready_probes(tags=ALL_TAGS | {"qwen4:9b": "sha256:d"}))
    assert write_attention_marker(healthy, logs) is None and not marker.exists()


def test_attention_revert_line_follows_the_pointer_source_and_the_file_order(tmp_path):
    """operator-ux review: the marker printed one fixed sentence (edit `active` / set
    MODEL_VERSION_<ROLE>=<previous>) whatever the pointer's source, and `<a previous id>` for
    every status but `fallback` — chain() is one entry long for embedding and for a tag pin.
    Each block below is one deviating state and the line the operator must read."""
    document = base_document()
    add_version(document, "general", general_v1(), active=False)          # v0 listed before v1
    add_version(document, "embedding", embedding_e5l(), active=False)     # v0 listed before e5l
    registry = load(tmp_path, document)
    extractor_on = frozenset({"condenser", "verifier"})

    def text(overrides, probes):
        return resolve(registry, overrides, probes).attention_text()

    # env_tag: the tag pin is what to unset; MODEL_VERSION_EXTRACTOR beside it would refuse boot.
    tag = text(Overrides(raw_tags={"extractor": "local-ai/student:d2"}, disabled_roles=extractor_on), ready_probes())
    assert "extractor: requested=env:local-ai/student:d2 loaded=None status=disabled" in tag
    assert ("revert: unset DISCORD_MEMORY_EXTRACTOR_MODEL (the ad-hoc tag pin, in .env or this shell), "
            "then restart run-local-ai-core.bat; the role then follows roles.extractor.active=extractor-v0") in tag
    assert "MODEL_VERSION_EXTRACTOR" not in tag and "<a previous id>" not in tag

    # env pin that fell back: `active` already names v0; the pin is what re-triggers the fallback.
    pinned = text(Overrides(pins={"general": "general-v1"}, disabled_roles=FLAGS_OFF), ready_probes())
    assert "general: requested=general-v1 loaded=general-v0 status=fallback" in pinned
    assert "revert: unset MODEL_VERSION_GENERAL in this shell (or set it to general-v0), then restart run-local-ai-core.bat" in pinned
    assert "edit roles.general.active" not in pinned

    # env pin on a candidate embedding whose collections were never built: unset the pin, or
    # run the remedy that makes the candidate serve — pinned to the candidate, not to v0.
    e5l = text(Overrides(pins={"embedding": "embedding-e5l-v1"}, disabled_roles=FLAGS_OFF),
               ready_probes(tags=ALL_TAGS | {"e5:large": "sha256:e"}, dims={}))
    assert "embedding: requested=embedding-e5l-v1 loaded=None status=degraded" in e5l
    assert "revert: unset MODEL_VERSION_EMBEDDING in this shell (or set it to embedding-v0), then restart run-local-ai-core.bat" in e5l
    assert ("remedy: python -m scripts.rebuild_qdrant --missing-only with MODEL_VERSION_EMBEDDING=embedding-e5l-v1 "
            "in the shell, then restart run-local-ai-core.bat") in e5l

    # registry pointer, unmoved, collection behind the corpus: there is nothing to revert
    # to — the rebuild IS the line, and it names the version to pin.
    short = text(Overrides(disabled_roles=FLAGS_OFF), ready_probes(points={"documents": 5, "memories": 3}))
    assert "embedding: requested=embedding-v0 loaded=embedding-v0 status=incomplete" in short
    assert "revert:" not in short and "<a previous id>" not in short
    assert ("remedy: python -m scripts.rebuild_qdrant --missing-only with MODEL_VERSION_EMBEDDING=embedding-v0 "
            "in the shell, then restart run-local-ai-core.bat") in short

    # registry pointer on a role with nothing listed before it and its tag gone: say so, with the reason.
    gone = text(Overrides(disabled_roles=FLAGS_OFF), ready_probes(tags={"qwen3-embedding:0.6b": "sha256:b", "glm-ocr:latest": "sha256:c"}))
    assert "general: requested=general-v0 loaded=None status=missing" in gone
    assert "revert: no earlier version of roles.general is registered — remedy: general-v0 tag qwen3.5:9b absent" in gone
    assert "<a previous id>" not in gone

    # registry pointer moved to the candidate without the rebuild: revert to v0 (listed before
    # it, its collections frozen but present) or run the remedy for the candidate.
    document["roles"]["embedding"]["active"] = "embedding-e5l-v1"
    moved = resolve(load(tmp_path, document), Overrides(disabled_roles=FLAGS_OFF),
                    ready_probes(tags=ALL_TAGS | {"e5:large": "sha256:e"}, dims={})).attention_text()
    assert ("revert: edit roles.embedding.active in backend/app/config/model_versions.yaml to embedding-v0 "
            "or set MODEL_VERSION_EMBEDDING=embedding-v0 in the shell, then restart run-local-ai-core.bat") in moved
    assert "remedy: python -m scripts.rebuild_qdrant --missing-only with MODEL_VERSION_EMBEDDING=embedding-e5l-v1" in moved


def test_every_deviation_logs_model_version_fallback(tmp_path):
    events: list[dict] = []
    handle = logger.add(lambda message: events.append(dict(message.record["extra"])), level="WARNING")
    try:
        document = base_document()
        add_version(document, "general", general_v1())
        resolve(load(tmp_path, document), Overrides(disabled_roles=FLAGS_OFF), ready_probes(tags={"qwen3-embedding:0.6b": "b"}))
    finally:
        logger.remove(handle)
    fallbacks = {event["role"]: event for event in events if event.get("event") == "model_version_fallback"}
    assert set(fallbacks) == {"general", "ocr"}
    assert fallbacks["general"]["requested"] == "general-v1" and fallbacks["general"]["status"] == "missing"
    assert fallbacks["ocr"]["status"] == "disabled"


# ── launcher lists ──────────────────────────────────────────────────────────────

def test_pull_list_covers_active_and_fallback_tags_and_create_list_the_modelfile_ones(tmp_path):
    document = base_document()
    add_version(document, "general", general_v1())
    add_version(document, "extractor", {
        "id": "extractor-d2", "provider": "ollama", "vram_mib": None,
        "ollama": {"source": "modelfile", "modelfile": "data/models/extractor/extractor-d2/Modelfile", "gguf_sha256": None},
        "config": {"provider": "ollama", "name": "local-ai/student:d2"}}, active=False)
    registry = load(tmp_path, document)
    everything_on = Overrides(pins={"extractor": "extractor-d2"})
    assert ollama_pull_list(registry, everything_on) == ["qwen4:9b", "qwen3.5:9b", "qwen3-embedding:0.6b", "glm-ocr:latest"]
    assert ollama_create_list(registry, everything_on) == [("local-ai/student:d2", PROJECT_ROOT / "data/models/extractor/extractor-d2/Modelfile")]
    assert ollama_pull_list(registry, Overrides(raw_tags={"extractor": "ad-hoc:tag"})) == ["qwen4:9b", "qwen3.5:9b", "qwen3-embedding:0.6b", "glm-ocr:latest", "ad-hoc:tag"]
    with pytest.raises(ModelRegistryError, match="MODEL_VERSION_EXTRACTOR"):
        ollama_pull_list(registry, Overrides(pins={"extractor": "nope"}))


# ── Settings ────────────────────────────────────────────────────────────────────

def test_overrides_from_settings_reads_flags_keys_pins_and_tags():
    # Both bases are passed explicitly: conftest pins QDRANT_MEMORIES_COLLECTION=memories_test in the environment.
    settings = _settings(discord_memory_extractor_enabled=True, gemini_api_key="k", model_version_general="general-v0",
                         discord_memory_verifier_model="verifier:tag", qdrant_documents_collection="documents_lab", qdrant_memories_collection="memories")
    overrides = overrides_from_settings(settings)
    assert overrides.disabled_roles == frozenset({"condenser", "verifier"})
    assert overrides.registered_providers == frozenset({"ollama", "gemini"})
    assert overrides.pins == {"general": "general-v0"} and overrides.raw_tags == {"verifier": "verifier:tag"}
    assert overrides.documents_collection == "documents_lab" and overrides.memories_collection == "memories"
    assert overrides.allow_missing_collections is False
    assert overrides_from_settings(_settings(discord_memory_extractor_enabled=True, discord_memory_verifier_enabled=True)).disabled_roles == frozenset({"condenser"})


def test_settings_refuses_both_pins_for_one_role():
    with pytest.raises(ValueError, match="DISCORD_MEMORY_EXTRACTOR_MODEL and MODEL_VERSION_EXTRACTOR are both set: set one, not both"):
        _settings(discord_memory_extractor_model="qwen3.5:9b", model_version_extractor="extractor-v0")
    with pytest.raises(ValueError, match="DISCORD_MEMORY_VERIFIER_MODEL and MODEL_VERSION_VERIFIER are both set"):
        _settings(discord_memory_verifier_model="qwen3.5:9b", model_version_verifier="verifier-v0")
    with pytest.raises(ValueError, match="must not be blank when set"):
        _settings(discord_memory_extractor_model="   ")


def test_settings_maps_empty_env_to_unset_and_registry_path_to_project_root(tmp_path):
    settings = _settings(model_version_general="", discord_memory_extractor_model="", model_registry_path="")
    assert settings.model_version_general is None and settings.discord_memory_extractor_model is None
    assert settings.model_registry_file == DEFAULT_REGISTRY_PATH
    assert _settings(model_registry_path="backend/tests/x.yaml").model_registry_file == PROJECT_ROOT / "backend/tests/x.yaml"
    assert _settings(model_registry_path=str(tmp_path / "r.yaml")).model_registry_file == tmp_path / "r.yaml"


def test_settings_serves_a_fixture_registry_and_refuses_an_unknown_pin(tmp_path):
    document = base_document()
    add_version(document, "general", general_v1(), active=False)
    path = write_registry(tmp_path, document)
    settings = _settings(model_registry_path=str(path), model_version_general="general-v1")
    assert settings.load_models()["general"]["name"] == "qwen4:9b"
    assert settings.resolve_models().roles["general"].source == "env"
    with pytest.raises(ModelRegistryError, match="MODEL_VERSION_OCR='ocr-v9'"):
        _settings(model_registry_path=str(path), model_version_ocr="ocr-v9").load_models()
