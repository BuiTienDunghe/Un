# Model version registry — FINAL design

Owner decisions (scope = every role; versioned file + one `active` per role, restart to switch; automatic fallback only on startup load/probe failure; defaults 1–5 for the open questions) are taken as fixed and are not re-argued below.

---

## 1. Registry YAML example

```yaml
# backend/app/config/model_versions.yaml
#
# One version record per model, one `active` pointer per role. Read ONCE per
# process at start (Settings.registry()/resolve_models()); restart to switch.
#
# PER-MACHINE PIN (shell only, never .env): MODEL_VERSION_<ROLE>=<id listed here>.
# MODEL_REGISTRY_PATH points a test at a fixture. MODEL_STARTUP_PROBES=false skips
# every probe (the test suite pins it).
#
# FALLBACK — automatic, startup only. If the active version fails its probe the
# resolver walks the versions listed BEFORE it (nearest first, skipping
# `fallback: false`) and serves the first that probes. Versions listed AFTER
# the active one are candidates and are never served automatically.
# `embedding` never falls back (a different model must never write into the
# active collection). Any role serving something other than what its pointer
# names => /health model_fallback: "fallback", data/logs/ATTENTION_model_fallback.txt,
# and the nightly eval refuses to grade. "Ineffective" is a human decision
# from eval numbers, never this file's.
#
# CHECKED BY  cd backend && python -m app.config.model_registry --check
# (CI static job, stdlib + PyYAML only, no network) — rules in docs/model_registry.md.
schema_version: 1
budget:
  vram_mib: 16311                      # data/vram_budget.md, measured 04/09/2026

roles:
  # ── general: the answer path. A cloud fallback would send user text to a
  # third party automatically, and a second local 9b tag is a download plus
  # ~6.4 GB residency (vram_budget.md), so v0 is deliberately alone.
  general:
    active: general-v0
    versions:
      - id: general-v0
        provider: ollama
        vram_mib: 6407                 # at num_ctx 4096
        eval:
          reports:
            d1_multidoc: data/evaluation/rag_multidoc_baseline.json
        config:                        # == models.yaml models.general as shipped, verbatim
          provider: ollama
          name: qwen3.5:9b
          context: 16384
          temperature: 0.4
          top_p: 0.9
          think: false
          keep_alive: 5m

  # ── condenser: read only by scripts/condensation_worker.py; needs
  # DISCORD_CONDENSATION_ENABLED + GEMINI_API_KEY. Probe = "provider registered".
  condenser:
    active: condenser-v0
    versions:
      - id: condenser-v0
        provider: gemini
        config:
          provider: gemini
          name: gemini-2.5-flash
          temperature: 0.2
          max_tokens: 4096

  # ── embedding: one version == one pair of Qdrant collections
  # (<base>_<suffix>). The version that embeds the query is the version whose
  # collections are searched — same pointer. Promotion AND demotion:
  #   1. python -m scripts.rebuild_qdrant  and  python -m scripts.rebuild_memories
  #      with MODEL_VERSION_EMBEDDING=<target> in the SHELL (--missing-only for a
  #      collection that already exists);
  #   2. point counts == active chunks / memories rows (printed by both scripts);
  #   3. move `active`; restart every launcher process.
  # Nothing ever deletes a collection. An inactive collection is FROZEN at the
  # moment it was last built — it is not a mirror (writes go to one collection).
  embedding:
    active: embedding-v0
    versions:
      - id: embedding-v0
        provider: ollama
        collection_suffix: ""          # documents / memories (documents_lab, documents_test via env base)
        vram_mib: 2870
        eval:
          reports:
            d1_multidoc: data/evaluation/rag_multidoc_baseline.json
        config:                        # BYTE-IDENTICAL to models.yaml models.embedding — the cache
          provider: ollama             # fingerprint must not move when this file lands
          name: qwen3-embedding:0.6b
          context: 32768
          revision: qwen3-embedding-0.6b-r1
          normalization: raw
          dimensions: 1024
      - id: embedding-e5l-v1           # CANDIDATE (after active): never served automatically
        provider: ollama
        ollama:
          source: modelfile            # built with `ollama create`, no hub tag exists
          modelfile: data/models/embedding/embedding-e5l-v1/Modelfile   # tracked; FROM names the gguf beside it (gitignored)
          gguf_sha256: null            # filled when the GGUF is exported; --check requires it once active or in a chain
        collection_suffix: e5l         # -> documents_e5l / memories_e5l (documents_lab_e5l on the lab stack)
        vram_mib: null                 # measure before promotion (vram_budget.md rule; --check refuses a null on the ACTIVE version)
        eval:
          reports:
            d1_multidoc: null
            heldout: null
            mteb: null
        config:
          provider: ollama
          name: local-ai/multilingual-e5-large:q8
          context: 512
          revision: multilingual-e5-large-q8-r1
          normalization: raw
          dimensions: 1024             # same width as v0 — exactly the silent-swap case the suffix guards
          query_prefix: "query: "      # inside config ON PURPOSE: a prefix change re-keys the cache
          passage_prefix: "passage: "

  # ── vision: no consumer (/vision/chat is 501). active: null = not served,
  # absent from /models.models (the app.js Vision row disappears; decision 5).
  vision:
    active: null
    versions:
      - id: vision-v0
        provider: ollama
        config:
          provider: ollama
          name: qwen3.5:9b
          context: 16384
          temperature: 0.3
          keep_alive: 5m

  # ── ocr: a missing tag turns the role OFF (config.enabled false on the served
  # copy) instead of today's per-page silent warnings. `glm-ocr:latest` is a
  # mutable tag: fill `digest` from GET /api/tags to pin it (the probe verifies it).
  ocr:
    active: ocr-v0
    versions:
      - id: ocr-v0
        provider: ollama
        digest: null
        config:                        # == models.yaml models.ocr as shipped
          provider: ollama
          name: glm-ocr:latest
          enabled: true
          context: 16384
          temperature: 0.1
          keep_alive: 5m
          prompt: "Text Recognition:"
          dpi: 200
          min_text_characters: 80
          min_alphanumeric_ratio: 0.45

  # ── reranker: in-process cross-encoder. `enabled` and `candidate_limit` stay
  # in models.yaml rag.reranker (policy); RAG_RERANKER_ENABLED=false still
  # short-circuits everything here. Chain: active -> previous ... -> disabled
  # (source=fallback). Never refuses boot (decision 2). Fallback entries load
  # with local_files_only=True: a rejection may never start a download.
  reranker:
    active: reranker-v0
    versions:
      - id: reranker-v0
        provider: sentence-transformers
        hub: cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
        revision: 1427fd652930e4ba29e8149678df786c240d8825
        activation: null               # hub config carries Identity; null = let it decide (P4-3 baseline scale)
        num_labels: 1
        max_length: 512
        vram_mib: 643
        probe:
          pairs:                       # scored ONCE on the production runtime (ST 3.4.1):
            - ["thủ tục cấp lại căn cước công dân",          #   python -m app.config.model_registry --record-probe reranker-v0
               "Điều 24. Trình tự, thủ tục cấp lại thẻ căn cước công dân khi bị mất, hư hỏng"]
            - ["thủ tục cấp lại căn cước công dân",
               "Bảng giá dịch vụ in ảnh khổ 10x15 và 13x18 tại xưởng"]
            - ["lịch nghỉ tết âm lịch 2026 của công ty",
               "Thông báo: công ty nghỉ Tết Nguyên đán từ 14/02 đến 22/02/2026"]
          scores: null                 # null = parity disarmed; --check WARNS while the ACTIVE version has none
          tolerance: 0.05
          max_ms: 500                  # timed predict on 15 pairs; measured and reported, over-cap is a WARNING
        eval:
          reports:
            d1_multidoc: data/evaluation/rag_multidoc_baseline.json
      - id: reranker-d2-v1             # CANDIDATE — export from training/reranker
        provider: sentence-transformers
        path: data/models/reranker/reranker-d2-v1    # repo-relative; weights gitignored, export.json + Modelfile-class files tracked
        activation: identity           # ST 5.x export lacks sbert_ce_default_activation_function; 3.4.1 would
        num_labels: 1                  #   default to Sigmoid and saturate at logit >= 17 — the loader forces this value
        max_length: 512
        vram_mib: null
        digest:
          file: model.safetensors      # hash of the file AS WRITTEN (re-saving changes bytes with identical tensors)
          sha256: null                 # copied from export.json by hand; --check requires equality and non-null when ACTIVE
        probe:
          pairs: []                    # exporter copies reranker-v0's pairs into export.json with the 5.7.0 scores;
          scores: null                 #   record copies them; 3.4.1 must reproduce within tolerance or the version is rejected
          tolerance: 0.05
          max_ms: 500
        eval:
          reports:
            d1_multidoc: null
            heldout: null
        provenance:
          base: cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
          base_revision: 1427fd652930e4ba29e8149678df786c240d8825
          git_sha: null
          train_data_sha256: null      # training.common.split_manifest.digest() of the split
          exported_with: sentence-transformers==5.7.0

  # ── extractor / verifier: env-only today. DISCORD_MEMORY_EXTRACTOR_MODEL=<tag>
  # stays as the ad-hoc per-machine pin (D2 ship path; source=env_tag, no fallback,
  # no provenance); MODEL_VERSION_EXTRACTOR=<id> is the provenance-carrying pin;
  # both set = Settings error. A missing tag disables the role (worker runs the
  # rule filter only). Generation knobs (num_ctx, temperature, seed) stay in Settings.
  extractor:
    active: extractor-v0
    versions:
      - id: extractor-v0
        provider: ollama
        vram_mib: 0                    # same tag as general-v0: no extra residency
        eval:
          reports:
            extractor_benchmark: data/benchmarks/discord_memory_extractor_20260904_qwen9b_full150.json
        config:
          provider: ollama
          name: qwen3.5:9b
      - id: extractor-d2-student-v1    # CANDIDATE — D2 distillation (.scratch/d2-distillation/spec.md)
        provider: ollama
        ollama:
          source: modelfile
          modelfile: data/models/extractor/extractor-d2-student-v1/Modelfile
          gguf_sha256: null
        vram_mib: null
        eval:
          reports:
            extractor_benchmark: null
        config:
          provider: ollama
          name: local-ai/extractor-student:d2
  verifier:
    active: verifier-v0
    versions:
      - id: verifier-v0
        provider: ollama
        vram_mib: 0
        config:
          provider: ollama
          name: qwen3.5:9b
```

---

## 2. Record fields

### Document

| Field | Type | Required | Read by | Why |
|---|---|---|---|---|
| `schema_version` | int, must be `1` | yes | `load_registry` | refuse a file written for a future resolver |
| `budget.vram_mib` | int | yes | `--check` | invariant #7 in bytes; lives in the data file, not in code |
| `roles.<role>` | mapping | exactly the eight names in `ROLES` | resolver | unknown or missing role = `ModelRegistryError` |
| `roles.<role>.active` | str \| null | yes; **non-null for `general` and `embedding`** | resolver, `--check`, nightly | the pointer; null = not served (vision) |
| `roles.<role>.versions` | list, oldest → newest | yes, ≥ 1 | `chain()`, launcher lists | order IS the fallback rule |

### Fields common to every version record

| Field | Type | Required | Read by | Why |
|---|---|---|---|---|
| `id` | str `[A-Za-z0-9._-]+`, unique within the role | yes | everything: env pins, `/models.registry`, report stamps, `document_versions.embedding_model`, log lines | the one name a report, a pin and a log share |
| `provider` | `ollama` \| `gemini` \| `deepseek` \| `sentence-transformers` | yes | resolver (which probe), launcher lists | must equal `config.provider` when `config` exists |
| `config` | mapping | required for `MODEL_ROLES` (all but reranker); **forbidden** for reranker | verbatim → `ModelRouter.models[role]`, `app.state.models`, `/models.models`, `SmartParser.ocr_config`, `OCRService`, `_cache_identity`, condensation_worker, app.js, dashboard.js, evaluate_rag | constraint 10/11: today's flat keys, nothing added, nothing stripped. `config.provider` and `config.revision` are legitimate members (fixes the draft's self-rejecting reserved set) |
| `fallback` | bool, default `true` | no | `chain()` | `false` = never chosen automatically |
| `vram_mib` | int \| null | no; **non-null on the ACTIVE version of general/embedding/reranker/extractor** | `--check` budget | invariant #7; `0` = shares a resident tag; null = "measure before promotion" |
| `digest` | str \| mapping \| null | no | ollama probe (string = `digest` from `/api/tags`); reranker `{file, sha256}` | "loadable" must mean "these bytes" |
| `ollama` | `{source: hub\|modelfile, modelfile: str\|null, gguf_sha256: str\|null}`; default `{source: hub}` | no; `modelfile` required with `source: modelfile` | `--ollama-pull-list` (hub only), `--ollama-create-list` (modelfile only), `--check` | a create-built tag can never be pulled; invariant #5 |
| `eval` | `{reports: {<gate>: path\|null}, split_sha256?: str}`; gate ∈ `d1_multidoc`, `heldout`, `mteb`, `extractor_benchmark` | required with ≥ 1 non-null existing path on the ACTIVE version of general/embedding/reranker/extractor | `--check`, docs | invariant #4 forcing function; one path per gate (the draft's positional list was unverifiable) |
| `provenance` | mapping, opaque | no | humans, report summaries | base, base_revision, git_sha, train_data_sha256, exported_with, promoted_at |
| `notes` | str | no | humans | — |

### Per-role additions

| Role | Field | Type | Required | Read by | Why |
|---|---|---|---|---|---|
| embedding | `collection_suffix` | str `[a-z0-9_]*`, unique within the role, `""` at most once | yes | `derive_collections` → `QdrantCollections`; sweep lists; rebuild scripts | constraint 13; OUTSIDE `config` so it never touches the cache fingerprint |
| embedding | `config.name/revision/normalization/dimensions/context` | as today | yes | ModelRouter, `_cache_identity`, width probe | today's cache contract |
| embedding | `config.query_prefix`, `config.passage_prefix` | str | no (absent = `""`) | `ModelRouter.embed(side=)` | inside `config` so a prefix change re-keys the cache |
| ocr | `config.enabled` | bool | yes | `ModelRouter.ocr`, `SmartParser`, app.js "(tắt)" | `false` in the file → status `off` (deliberate, no probe); resolver flips the served COPY to `false` only on status `disabled` |
| reranker | `hub` xor `path` | str / repo-relative dir | exactly one | loader; `--check` | `path` resolves against `PROJECT_ROOT` in `load_registry`; implies `local_files_only=True` |
| reranker | `revision` | str | required with `hub` | `CrossEncoder(revision=)` | pin the snapshot |
| reranker | `activation` | `identity` \| `sigmoid` \| null | no | loader `default_activation_function`; warmup cross-checks `export.json.activation_fn` / `config_sentence_transformers.json` when present | decision 4 |
| reranker | `num_labels`, `max_length` | int | no | post-load verify | reject another head or window |
| reranker | `digest.file`, `digest.sha256` | str | `sha256` non-null when a `path` version is ACTIVE; null on a candidate = check skipped, `digest_ok: null` logged, never a rejection | pre-load verify; `--check` equality with `export.json` | file as written |
| reranker | `probe.pairs/scores/tolerance/max_ms` | list[[q,p]], list[float]\|null, float, int\|null | `pairs` yes; `scores` non-null when a `path` version is ACTIVE; null allowed for `hub` (`--check` warns) | parity; timed predict | catches Sigmoid/Identity mismatch and a random head |
| extractor / verifier | `config.name` only | str | yes | `workers/memory_tasks.py` | knobs stay in Settings (strict-mode validators) |
| vision | — | | | nothing | id space only |

### Tracked beside a checkpoint (contract with the exporter, `data/models/<role>/<id>/`)

- `export.json` (tracked): `{"activation_fn": "identity"|"sigmoid", "probe_pairs": [[q,p],...], "scores": [...], "model_safetensors_sha256": "...", "exported_with": "sentence-transformers==5.7.0", "base": ..., "base_revision": ..., "git_sha": ..., "train_data_sha256": ...}`. The record's `activation`, `probe.pairs/scores`, `digest.sha256` are copies of it; `--check` requires equality (file present in CI), warmup re-verifies the weights against `model_safetensors_sha256`.
- `Modelfile` (tracked) for Ollama create-built versions; `FROM` names the GGUF beside it.
- `.gitignore` rule (lands with this PR, before any export): `data/models/**`, `!data/models/**/`, `!data/models/**/Modelfile`, `!data/models/**/export.json`.

### Not in the registry (on purpose)

`rag.reranker.enabled` / `candidate_limit`, `rag.*`, `agent.*`, `storage.*` stay in models.yaml. `rag.reranker.model` and the whole `models:` block are **deleted** from models.yaml in the same PR (header rewritten to point at model_versions.yaml); `load_config()`/`load_storage_config()` unchanged.

---

## 3. Resolver interface

```python
"""backend/app/config/model_registry.py

Import-light: module level imports stdlib + yaml ONLY (the CI static job has
no pydantic; a test asserts `import app.config.model_registry` leaves
pydantic out of sys.modules). Settings, OllamaClient, QdrantStore and the
Postgres models are imported lazily inside ProductionProbes / the CLI.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[3]          # settings.py may import it from here
DEFAULT_REGISTRY_PATH = Path(__file__).with_name("model_versions.yaml")

ROLES = ("general", "condenser", "embedding", "vision", "ocr", "reranker", "extractor", "verifier")
MODEL_ROLES = ("general", "condenser", "embedding", "vision", "ocr", "extractor", "verifier")   # carry `config:`
NEVER_NULL_ROLES = ("general", "embedding")
NO_FALLBACK_ROLES = ("embedding",)                                  # constraint 13
DISABLE_ON_MISS_ROLES = ("ocr", "extractor", "verifier", "condenser")
RESERVED_RECORD_KEYS = frozenset({                                   # a key from this set INSIDE `config:` is a load error
    "id", "config", "fallback", "vram_mib", "digest", "ollama", "eval", "provenance", "notes",
    "collection_suffix", "hub", "path", "activation", "num_labels", "max_length", "probe",
})                                                                   # `provider` and `revision` are NOT reserved (they belong in config)
GATES = ("d1_multidoc", "heldout", "mteb", "extractor_benchmark")
GRANDFATHERED_UNSTAMPED = frozenset({"general-v0", "embedding-v0", "reranker-v0", "extractor-v0"})  # reports without a `versions` stamp: WARNING, not error

Status = Literal["active", "fallback", "unverified", "missing", "degraded", "incomplete",
                 "disabled", "off", "unconfigured", "pending"]
DEVIATING = frozenset({"fallback", "missing", "degraded", "incomplete", "disabled"})
Source = Literal["registry", "env", "env_tag"]


class ModelRegistryError(ValueError):
    """Registry file or env pin invalid. Raised from load_registry()/resolve()/derive_collections();
    refuses boot in every process (a CI-checked file being corrupt is not an environment
    problem — invariant #5 is about missing optional packages). Message names file, role,
    id and, for a pin, the env variable."""


class QdrantUnreachable:
    """Sentinel type: 'could not decide', distinct from None = 'no such collection'."""
QDRANT_UNREACHABLE = QdrantUnreachable()


@dataclass(frozen=True)
class RerankerProbeSpec:
    pairs: tuple[tuple[str, str], ...]
    scores: tuple[float, ...] | None = None
    tolerance: float = 0.05
    max_ms: int | None = None


@dataclass(frozen=True)
class OllamaSource:
    source: Literal["hub", "modelfile"] = "hub"
    modelfile: Path | None = None              # ABSOLUTE (resolved against PROJECT_ROOT)
    gguf_sha256: str | None = None


@dataclass(frozen=True)
class VersionRecord:
    role: str
    id: str
    provider: str
    config: Mapping[str, Any]                  # MODEL_ROLES: verbatim runtime block; reranker: {}
    fallback: bool = True
    vram_mib: int | None = None
    digest: str | None = None                  # ollama: /api/tags digest; reranker: sha256 of digest_file
    digest_file: str | None = None             # reranker `path` versions, default "model.safetensors"
    ollama: OllamaSource = OllamaSource()
    collection_suffix: str = ""
    hub: str | None = None
    path: Path | None = None                   # ABSOLUTE
    revision: str | None = None
    activation: Literal["identity", "sigmoid"] | None = None
    num_labels: int | None = None
    max_length: int | None = None
    probe: RerankerProbeSpec | None = None
    eval_reports: Mapping[str, Path | None] = field(default_factory=dict)   # gate -> absolute path
    split_sha256: str | None = None
    provenance: Mapping[str, Any] | None = None

    @property
    def name(self) -> str:
        """config['name'] for MODEL_ROLES; hub id or str(path) for the reranker."""

    @property
    def ollama_tag(self) -> str:
        """config['name'] as /api/tags reports it: no ':' -> 'name:latest'."""

    def loader_kwargs(self) -> dict[str, Any]:
        """Reranker only. {revision?, local_files_only?, activation?} — only the set ones;
        local_files_only=True when `path` is set or HF_HUB_OFFLINE is set. {} for a
        legacy single-name service, so `lambda _:` loaders keep working. `activation`
        is the STRING; RerankerService._load_cross_encoder builds the torch module."""


@dataclass(frozen=True)
class RoleEntry:
    active: str | None
    versions: tuple[VersionRecord, ...]        # file order


@dataclass(frozen=True)
class Registry:
    path: Path
    schema_version: int
    vram_budget_mib: int
    roles: Mapping[str, RoleEntry]

    def get(self, role: str, version_id: str) -> VersionRecord: ...       # ModelRegistryError when unknown
    def chain(self, role: str, start: str | None = None) -> tuple[VersionRecord, ...]:
        """[start or active] then the versions BEFORE it, nearest first, skipping fallback: false.
        Length <= 1 for NO_FALLBACK_ROLES. Empty when active is None."""


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> Registry:
    """Parse + validate. No network; the only filesystem access is the file itself.
    ModelRegistryError on: missing/unreadable file; schema_version != 1; budget.vram_mib
    missing; a role outside ROLES or a missing role; NEVER_NULL_ROLES with active null;
    duplicate id; `active` not among the ids; empty versions; MODEL_ROLES record without
    a mapping `config`; reranker record WITH `config`; RESERVED_RECORD_KEYS inside `config`;
    config.provider != provider; provider outside the four; embedding collection_suffix
    duplicated / outside [a-z0-9_]* / "" more than once; reranker without exactly one of
    hub|path; hub without revision; activation outside {identity, sigmoid}; probe.scores
    length != pairs length; ollama.source outside {hub, modelfile}; source modelfile
    without modelfile; eval.reports key outside GATES. Relative `path`, `ollama.modelfile`
    and `eval.reports` values are resolved against PROJECT_ROOT here."""


@dataclass(frozen=True)
class Overrides:
    """Everything the resolver needs from Settings; built by overrides_from_settings()."""
    pins: Mapping[str, str] = field(default_factory=dict)            # role -> id (MODEL_VERSION_<ROLE>)
    raw_tags: Mapping[str, str] = field(default_factory=dict)        # extractor/verifier -> Ollama tag (DISCORD_MEMORY_*_MODEL)
    disabled_roles: frozenset[str] = frozenset()                     # condenser / extractor / verifier whose flag is off
    registered_providers: frozenset[str] = frozenset({"ollama"})     # + gemini / deepseek when the key is set
    documents_collection: str = "documents"                          # settings.qdrant_documents_collection = the BASE
    memories_collection: str = "memories"
    allow_missing_collections: bool = False                          # rebuild scripts only: absent collection is fine, completeness skipped


@dataclass(frozen=True)
class QdrantCollections:
    documents: str                    # base + ("_" + suffix if suffix else "")
    memories: str
    all_documents: tuple[str, ...]    # one per registered embedding version, active first — the delete sweep
    all_memories: tuple[str, ...]


def derive_collections(registry: Registry, overrides: Overrides) -> QdrantCollections:
    """PURE function of the pointer (pin or active) — no probe, no resolve. Used by
    Settings.qdrant_collections() (collection-only consumers: cleanup_worker, forget_member,
    migrate_document_storage) and by resolve(); a test asserts both agree.
    ModelRegistryError when the env base ends with "_<suffix>" of any registered version
    with a non-empty suffix, or when two versions derive the same name under this base
    (the alias hole: QDRANT_DOCUMENTS_COLLECTION=documents_e5l with v0 active)."""


@dataclass(frozen=True)
class PostgresCounts:
    active_chunks: int                # the operational_service/check_operational_alerts predicate
    memories: int                     # select count(*) from memories (app.postgres.models.Memory)


class Probes(Protocol):
    """Bounded, single-attempt, never download, never raise. 'Could not decide' is always
    a distinct value from 'decided no'."""
    def ollama_tags(self) -> Mapping[str, str] | None: ...                        # {tag: digest}; None = unreachable/timeout; called once per resolve()
    def ollama_embed_dimension(self, model: str) -> int | None: ...              # one POST /api/embed of "local-ai-core probe"; None = failed/timeout, NOT wrong size
    def qdrant_dimension(self, collection: str) -> int | None | QdrantUnreachable: ...
    def qdrant_point_count(self, collection: str) -> int | QdrantUnreachable: ...  # 0 when absent
    def postgres_counts(self) -> PostgresCounts | None: ...                       # None = DB did not answer (connect timeout 5 s)


class ProductionProbes:
    """Lazy imports of OllamaClient / QdrantStore / sqlalchemy. Timeouts: ollama_health_timeout_seconds,
    qdrant_timeout_seconds, Postgres connect_timeout 5 s."""
    def __init__(self, settings: "Settings") -> None: ...


@dataclass
class ProbeOutcome:
    kind: Literal["skipped", "tags", "tags+digest", "embed_dimension", "collection_dimension",
                  "collection_count", "provider", "reranker_load"]
    ok: bool | None                   # None = could not decide
    detail: str | None = None
    ms: int | None = None


@dataclass
class RoleResolution:
    role: str
    requested_id: str | None          # env pin, "env:<tag>" for a raw tag, or registry active
    source: Source
    loaded_id: str | None             # the version verified to serve; None = nothing serves what was asked
    status: Status
    reason: str | None
    record: VersionRecord | None      # whose config is EXPOSED: the loaded one, or the requested one on keep-pointer statuses
    chain: tuple[VersionRecord, ...]
    probe: ProbeOutcome | None
    verified: bool                    # False when probes were skipped
    latency_ms: int | None = None     # reranker

    @property
    def deviates(self) -> bool:
        """status in DEVIATING. Deliberate states never deviate: off (feature flag / ocr enabled:false),
        unconfigured (active null), unverified (pointer kept, nothing contradicted), pending.
        This ONE predicate drives /health.model_fallback, the ATTENTION marker, nightly_eval's
        refusal and every report writer's refusal, so they can never disagree."""

    @property
    def serving(self) -> bool:
        """status in {active, fallback, unverified, incomplete} — the role may be called."""

    @property
    def flat_config(self) -> dict[str, Any] | None:
        """Deep copy of record.config for MODEL_ROLES; None for reranker and unconfigured roles.
        The ONLY edit ever applied: ocr with status `disabled` gets enabled: False."""


@dataclass
class Resolved:
    registry: Registry
    roles: dict[str, RoleResolution]
    collections: QdrantCollections
    probed: bool

    def flat_models(self) -> dict[str, dict[str, Any]]:
        """{role: flat_config} for every MODEL_ROLES role whose flat_config is not None
        (vision absent). Built once; the SAME object on every call."""
    def reranker_chain(self) -> tuple[VersionRecord, ...]: ...       # () when active is null
    def embedding_refusal(self) -> str | None: ...                    # reason when embedding.status == "degraded", else None
    def embedding_version_id(self) -> str | None: ...                 # roles["embedding"].record.id — written by activate()
    def model_name(self, role: str) -> str | None: ...                # record.config["name"] or None
    def record_reranker(self, *, loaded_id: str | None, status: Status, reason: str | None,
                        latency_ms: int | None = None) -> None:
        """Reranker only: the torch model cannot be loaded in every process, so RerankerService.warmup()
        reports back (status is `pending` until then). Emits model_version_fallback when it deviates. Idempotent."""
    def registry_view(self) -> dict[str, dict[str, Any]]:
        """/models.registry: {role: {active, requested, loaded, source, status, reason, verified, name,
        digest, collections: {documents, memories} (embedding only), latency_ms (reranker only), fallback: bool}}
        where fallback == deviates."""
    def fallback_flag(self) -> Literal["ok", "fallback"]: ...        # "fallback" iff any role deviates
    def attention_text(self) -> str | None: ...                       # ATTENTION file body, None when nothing deviates


def resolve(registry: Registry, overrides: Overrides, probes: Probes | None = None) -> Resolved:
    """Pure function of its inputs. Per role, in ROLES order:
    1. Pointer: pins[role] (source=env) > raw_tags[role] (source=env_tag; synthetic VersionRecord
       id "env:<tag>", config {provider: ollama, name: tag}, chain of one) > registry active
       (source=registry). Unknown pin -> ModelRegistryError naming the env var.
    2. active is None and no pin -> unconfigured; no record; no probe.
    3. role in disabled_roles -> off, reason names the flag ("DISCORD_MEMORY_EXTRACTOR_ENABLED=false");
       record = requested (so /models still shows the name); no probe.
       ocr whose record.config.enabled is False -> off, reason "config.enabled=false"; no probe.
    4. probes is None -> active, loaded_id = requested_id, verified False.
    5. chain = registry.chain(role, requested) (length 1 for embedding / env_tag); walk it,
       first candidate that passes serves:
       - provider ollama: tags None -> stop: unverified, pointer kept (Ollama down is not a
         reason to switch models). Tag absent -> next. Tag present and record.digest set and
         != tags digest -> next (detail "digest_mismatch"). Else passes.
         embedding additionally (allow_missing_collections False unless stated):
           a. ollama_embed_dimension(tag): None -> unverified; != config.dimensions -> degraded.
           b. for documents then memories: qdrant_dimension -> QDRANT_UNREACHABLE -> unverified;
              size != dimensions -> degraded; None (absent) -> degraded when postgres_counts()
              says the corresponding corpus is non-empty (active_chunks > 0 / memories > 0),
              fine when it is empty (fresh install), unverified when counts is None;
              allow_missing_collections True -> absent is always fine.
           c. present and sized right: qdrant_point_count < corpus count -> incomplete
              (reason names both numbers and the remedy "rebuild_qdrant --missing-only" /
              "rebuild_memories --missing-only"); skipped when allow_missing_collections.
           degraded wins over incomplete; the first contradiction stops the walk.
       - provider gemini / deepseek: registered -> passes; else next.
       - reranker: no probe here; status pending; chain handed to RerankerService.
    6. Chain exhausted: general / embedding -> missing (record = requested; first use 502
       MODEL_NOT_LOADED as today; collections still derived); DISABLE_ON_MISS_ROLES -> disabled
       (ocr flat_config.enabled False; extractor/verifier/condenser record kept, serving False),
       reason names the probe.
    7. loaded_id != requested_id and passes -> fallback, reason "<requested> <detail>; serving <loaded>".
    collections = derive_collections(registry, overrides) (asserted == the embedding record's suffix).
    Every deviation logs model_version_fallback (WARNING). No I/O besides probes."""


def write_attention_marker(resolved: Resolved, logs_path: Path) -> Path | None:
    """API process only, after record_reranker(). Writes <logs_path>/ATTENTION_model_fallback.txt when
    any role deviates — one line per deviating role (requested, loaded, status, reason) plus the
    one-step revert ("edit roles.<role>.active or set MODEL_VERSION_<ROLE>=<previous id> in the shell,
    then restart run-local-ai-core.bat"); deletes it otherwise. Workers only log."""


def overrides_from_settings(settings: "Settings") -> Overrides:
    """pins from model_version_<role>; raw_tags from discord_memory_extractor_model / _verifier_model;
    disabled_roles: condenser unless discord_condensation_enabled, extractor unless
    discord_memory_extractor_enabled, verifier unless both verifier and extractor flags;
    registered_providers from gemini_api_key / deepseek_api_key; collections from
    qdrant_documents_collection / qdrant_memories_collection."""


def ollama_pull_list(registry: Registry, overrides: Overrides) -> list[str]:
    """Hub-sourced tags the launcher must pull: for every ollama role not off/unconfigured, the requested
    tag plus every tag in its chain, de-duplicated, file order. Honours pins. No probes."""

def ollama_create_list(registry: Registry, overrides: Overrides) -> list[tuple[str, Path]]:
    """(tag, modelfile) for every modelfile-sourced tag in the same set."""


# CLI:  cd backend && python -m app.config.model_registry <mode> [--registry PATH]
#   --check              load_registry + static rules (stdlib+yaml only; exit 1 with every violation listed):
#                          - ACTIVE general/embedding/reranker/extractor: >= 1 eval.reports path exists;
#                            every non-null report path exists; unless id in GRANDFATHERED_UNSTAMPED the
#                            report's `versions.<role>` == id (WARNING for grandfathered files without a stamp);
#                            extractor_benchmark: report.model == config.name; mteb: report.model == config.name
#                          - ACTIVE version vram_mib non-null; sum over active general+embedding+reranker
#                            (+extractor when its tag differs from general's) <= budget.vram_mib
#                          - ACTIVE `path` reranker: digest.sha256 and probe.scores non-null; export.json exists and
#                            equals the record (activation_fn, scores, model_safetensors_sha256); hub ACTIVE without
#                            scores -> WARNING
#                          - ACTIVE or in-chain ollama.source=modelfile: Modelfile exists; gguf_sha256 non-null
#                          - ci.yml Ollama cache key == "ollama-" + embedding active config.revision
#   --show [--no-probe]  resolve as this machine would; print registry_view() JSON (+ counts)
#   --ollama-pull-list   one tag per line            (launcher `for /f`)
#   --ollama-create-list "tag<TAB>modelfile" per line (launcher `for /f`)
#   --record-probe <id>  HUB versions only (a `path` version's scores come from export.json): load on THIS runtime,
#                        score probe.pairs, print the `scores:` block. Needs the [rerank] extra.


# ── Log events (loguru logger.bind, idiom of reranker_config) ─────────────────────
#   model_registry_loaded     INFO   path, schema_version, roles
#   model_version_config      INFO   role, requested, source
#   model_version_probe       INFO   role, version_id, kind, ok, detail, ms
#   model_version_resolved    INFO   role, loaded, status, verified, collections (embedding)
#   model_version_fallback    WARN   role, requested, loaded, status, reason        (every deviation)
#   qdrant_collections        INFO   documents, memories, suffix, base
#   reranker_version_loaded   INFO   version_id, source=active|fallback, ms, digest_ok, parity_ok, latency_ms
#   reranker_version_rejected WARN   version_id, reason=import|not_cached|load|digest|activation|num_labels|max_length|parity
#   reranker_config           INFO   unchanged


# ── settings.py additions (idiom of :108-124) ──────────────────────────────────────
#   model_registry_path: str | None = None            # MODEL_REGISTRY_PATH; None -> DEFAULT_REGISTRY_PATH; relative -> PROJECT_ROOT
#   model_startup_probes: bool = True                 # MODEL_STARTUP_PROBES; conftest pins "false"
#   model_version_general / _condenser / _embedding / _ocr / _reranker / _extractor / _verifier: str | None = None
#   discord_memory_extractor_model: str | None = None # WAS "qwen3.5:9b": None = follow registry; a tag = ad-hoc pin (env_tag)
#   discord_memory_verifier_model: str | None = None
#   _registry: Registry | None = PrivateAttr(None);  _resolved: Resolved | None = PrivateAttr(None)
#   before-validator: "" -> None for every field above (same as _auto_apply_off_words)
#   model validator: DISCORD_MEMORY_EXTRACTOR_MODEL and MODEL_VERSION_EXTRACTOR both set -> ValueError("set one, not both");
#     same for the verifier pair; the existing "must not be empty" check becomes "if set, must not be blank"
#   @property model_registry_file -> Path
#   def registry(self) -> Registry                     # load_registry(self.model_registry_file), cached
#   def resolve_models(self, *, allow_missing_collections: bool = False) -> Resolved
#       # probes = ProductionProbes(self) if self.model_startup_probes else None; cached (first call wins)
#   def load_models(self) -> dict[str, dict[str, Any]]:  return self.resolve_models().flat_models()   # signature unchanged
#   def qdrant_collections(self) -> QdrantCollections:   return derive_collections(self.registry(), overrides_from_settings(self))
#   load_config()/load_storage_config() unchanged


# ── OllamaClient (app/llm_clients/ollama_client.py) ───────────────────────────────
class OllamaClient:
    def list_models(self) -> dict[str, str] | None:
        """GET /api/tags within health_timeout -> {name: digest}; None on any httpx error/timeout. Never pulls."""
    def probe_embed_dimension(self, model: str, text: str = "local-ai-core probe") -> int | None:
        """ONE POST /api/embed, timeout=health_timeout, no retry loop; len(embeddings[0]); None on 404/error/timeout."""


# ── QdrantStore (app/stores/qdrant_store.py) ──────────────────────────────────────
class QdrantStore:
    def __init__(self, url: str, timeout: float, memories_collection: str | None = None,
                 documents_collection: str | None = None, *,
                 documents_sweep: Sequence[str] | None = None,     # default (documents_collection,)
                 memories_sweep: Sequence[str] | None = None) -> None: ...
    # delete_document_version / delete_document / delete_memory iterate the SWEEP, active collection first:
    # collection_exists(name) (via _retry) -> skip absent; delete (via _retry) -> raise QdrantUnavailableError on the
    # first failure of an existing collection. Callers see one call, one exception, before any Postgres write.
    def collection_dimension(self, name: str) -> int | None | QdrantUnreachable: ...   # single attempt, no _retry
    def point_count(self, name: str) -> int | QdrantUnreachable: ...                    # client.count(exact=True); 0 when absent
    def existing_point_ids(self, point_ids: Sequence[str]) -> set[str]: ...            # client.retrieve in batches of 256, no payload/vectors
    def upsert_chunks(self, ..., chunk_ids: list[str] | None = None, replace: bool = True) -> None: ...  # replace=False skips the delete-by-filter


# ── ModelRouter (app/services/model_router.py) ────────────────────────────────────
class EmbeddingRefusedError(OllamaModelNotLoadedError):
    """Embedding role is `degraded`: a verified contradiction between the version and its
    collections. Subclass so every existing except-branch (rag/chat/memory/documents routers,
    the SSE error event, job_errors -> non-retryable) maps it to 502 MODEL_NOT_LOADED with a
    message naming the reason and /models.registry — no new router branch, no new code."""

class ModelRouter:
    def __init__(self, clients: dict[str, LLMClient], models: dict[str, dict[str, Any]], *,
                 embedding_refusal: str | None = None) -> None: ...
    def embed(self, text: str, *, side: Literal["query", "passage"]) -> tuple[list[float], str]:
        """side is keyword-REQUIRED (a missed caller fails in tests, not by embedding with the wrong prefix).
        Raises EmbeddingRefusedError(embedding_refusal) first when set. Prepends config.get(f"{side}_prefix", "")
        (absent on v0: byte-identical vectors). Returned model name unchanged (cache identity compares it).
        Callers — query: postgres_retrieval_service.py:41, memory_service.py:62 (search);
        passage: postgres_document_service.py:594, memory_service.py:24, :42, :67, :72, :84 (both rollbacks),
        rebuild_qdrant.py:41, rebuild_memories.py, benchmark_documents.py:23.
        Test fakes gaining `*, side=None` (or **kwargs): test_postgres_auxiliary_store.py:129,
        test_postgres_cleanup_lifecycle.py:29, test_postgres_retrieval_preparation.py:24,
        test_postgres_embedding_cache.py:103, test_rq_reindex_integration.py:41,
        test_versioned_ingestion.py:27, worker_integration_support.py:44."""


# ── RerankerService (app/services/reranker_service.py) ────────────────────────────
@dataclass
class WarmupOutcome:
    status: Literal["loaded", "rejected_all", "flag_off", "no_versions"]
    loaded_id: str | None
    source: Literal["active", "fallback", "legacy"] | None
    reason: str | None
    latency_ms: int | None
    digest_ok: bool | None
    parity_ok: bool | None


class RerankerService:
    def __init__(self, enabled: bool, model_name: str, candidate_limit: int,
                 model_loader: Callable[..., Any] | None = None, window_stride_ratio: float = 0.5,
                 *, versions: Sequence[VersionRecord] | None = None) -> None:
        """versions None = legacy single-name behaviour (test_reranker_service.py untouched: the loader is
        called as loader(name) with no kwargs). versions given = loader(name, **record.loader_kwargs()).
        self.loaded: VersionRecord | None; self.outcome: WarmupOutcome | None."""

    @classmethod
    def from_config(cls, rag_config: dict, *, enabled_override: bool | None = None,
                    model_loader: Callable[..., Any] | None = None,
                    versions: Sequence[VersionRecord] | None = None) -> "RerankerService":
        """enabled/source logic and log line unchanged. model_name = versions[0].name when versions is a
        non-empty sequence; rag_config.reranker.model / the hub default when versions is None;
        versions == () -> enabled=False, model_name "" (warmup reports no_versions). Never indexes an empty chain."""

    def warmup(self) -> WarmupOutcome:
        """NEVER raises. enabled False -> flag_off. versions == () -> no_versions. versions None -> legacy:
        today's load, but an exception yields rejected_all (source legacy) instead of raising.
        For index, record in enumerate(versions):
          kwargs = record.loader_kwargs(); if index > 0: kwargs["local_files_only"] = True   # a rejection may never download
          [pre-load]  path versions: export.json present -> activation_fn must equal record.activation (reject `activation`);
                      record.digest set -> sha256(path/digest_file) must equal it (reject `digest`); digest None -> digest_ok None
          [load]      model_loader(record.name, **kwargs); ImportError/RerankerUnavailableError -> reject `import`;
                      HF "not found locally" under local_files_only -> reject `not_cached`; any other Exception -> `load`
          [post-load] model.model.config.num_labels (fallback getattr(model, "config")) == record.num_labels; model.max_length == record.max_length (reject)
          [parity]    scores set: predict(pairs); every |score - expected| <= tolerance else reject `parity`
          [timing]    predict on 15 pairs (pairs cycled): latency_ms; > max_ms -> WARNING, keeps serving
          survivor: self._model, self.loaded = record, self.model_name = record.name (the lazy path reloads THIS record),
                    source "active" if index == 0 else "fallback"; log reranker_version_loaded.
        All rejected: self.enabled = False, rejected_all, source "fallback" (pass-through at rerank(); deviates upstream).
        Request-time contract unchanged: a model that breaks later still raises RerankerUnavailableError -> 503."""

    def rerank(self, ...):   # unchanged except the lazy path:
        # model = self._model or self._model_loader(self.model_name, **(self.loaded.loader_kwargs() if self.loaded else {}))

    @staticmethod
    def _load_cross_encoder(model_name: str, *, revision: str | None = None,
                            local_files_only: bool = False, activation: str | None = None) -> Any:
        """CrossEncoder(model_name, revision=revision, local_files_only=local_files_only or bool(os.getenv("HF_HUB_OFFLINE")),
        default_activation_function={"identity": torch.nn.Identity(), "sigmoid": torch.nn.Sigmoid()}[activation] when set).
        All three kwargs exist in 3.4.1. ImportError -> RerankerUnavailableError with the pip hint, as today."""


# ── OperationalService / routers / schema ─────────────────────────────────────────
#   OperationalService.__init__(..., *, model_registry: Resolved | None = None)
#   health(): components["model_fallback"] = model_registry.fallback_flag() if model_registry else "ok"; top-level status untouched
#   ModelsResponse: + registry: dict[str, dict[str, Any]] = {}  + rag: dict[str, Any] = {}     (additive)
#   routers/models.py: ModelsResponse(models=app.state.models, registry=app.state.model_registry.registry_view(), rag=app.state.rag_flags)
#     app.state.rag_flags = {"contextual_retrieval": chunk_context_service.enabled, "reranker": reranker_service.enabled,
#                            "retrieval_mode": retrieval_mode}   — set AFTER warmup so a rejected chain reports reranker: false


# ── PostgresDocumentService / repository ──────────────────────────────────────────
#   PostgresDocumentService.__init__(..., embedding_version: str | None = None)   # resolved.embedding_version_id()
#   PostgresDocumentRepository.activate(run_id, job_id=None, worker_id=None, system_context=False, *, embedding_version: str | None = None)
#     -> version.embedding_model = embedding_version when not None. Both activation sites (:460, :527) pass it.
#     The column means "embedding version whose vectors were written at activation". Nothing else writes it.
```

---

## 4. Startup flow

### API — `backend/app/main.py` lifespan

| Step | Where (today's lines) | What |
|---|---|---|
| 1 | :52 | `settings = get_settings()`; Settings validation (incl. the new both-pins check) still runs before any I/O |
| 2 | :55-78 | Ollama + cloud clients, unchanged |
| 3 | :81-84 | sessions, auxiliary store, `LoggingService` — already before the router, so resolver events reach the durable sink |
| 4 | :85 | `resolved = settings.resolve_models()` → `load_registry` → `resolve(registry, overrides_from_settings(settings), probes=ProductionProbes(settings) if settings.model_startup_probes else None)`. I/O: one GET `/api/tags`, one probe embed for the embedding pointer, one `get_collection` + one `count` per embedding collection, one Postgres count pair — each single-attempt and bounded. `router = ModelRouter(llm_clients, settings.load_models(), embedding_refusal=resolved.embedding_refusal())` |
| 5 | :86-88 | `config = settings.load_config()` for `rag`/`storage`, unchanged |
| 6 | :89 | `c = settings.qdrant_collections()`; `QdrantStore(url, timeout, c.memories, c.documents, documents_sweep=c.all_documents, memories_sweep=c.all_memories)` |
| 7 | :92 | `app.state.models = router.models` (same object; the second `load_models()` call goes away); `app.state.model_registry = resolved` |
| 8 | :157-162 | `PostgresDocumentService(..., embedding_version=resolved.embedding_version_id())` |
| 9 | :163-175 | `OperationalService(..., model_registry=resolved)` |
| 10 | :178-181 | `reranker_service = RerankerService.from_config(rag_config, enabled_override=settings.rag_reranker_enabled, versions=resolved.reranker_chain())`; `outcome = reranker_service.warmup()`; `resolved.record_reranker(loaded_id=outcome.loaded_id, status={"loaded": "active" if outcome.source == "active" else "fallback", "rejected_all": "disabled", "flag_off": "off", "no_versions": "unconfigured"}[outcome.status], reason=outcome.reason, latency_ms=outcome.latency_ms)`; `write_attention_marker(resolved, settings.logs_path)` |
| 11 | :182-190 | `app.state.rag_flags = {...}` after `retrieval_mode` is known |
| 12 | rest | unchanged. `/health` and `/models` answer only after lifespan, so "200 ⇒ lifespan finished" still holds |

Cached per API process: Settings (lru), `Registry` + `Resolved` (PrivateAttr), the `/api/tags` answer (inside one `resolve()`), `flat_models()` dict (one object), `RerankerService._model`.

### Index/OCR worker — `backend/app/workers/tasks.py:_service()`

1. `settings = get_settings()`; the first job of the process pays the probes, later jobs reuse `settings._resolved`.
2. Move `LoggingService(auxiliary_store, settings.logs_path)` above the `ModelRouter(...)` (one reorder).
3. `ModelRouter(OllamaClient(...), settings.load_models(), embedding_refusal=settings.resolve_models().embedding_refusal())`.
4. `QdrantStore(..., documents_collection=c.documents, documents_sweep=c.all_documents)` with `c = settings.qdrant_collections()`; `PostgresDocumentService(..., embedding_version=settings.resolve_models().embedding_version_id())`.
5. Failure semantics: embedding `degraded` → `router.embed` raises `EmbeddingRefusedError` before Ollama → `index_for_worker` fails the run `DOCUMENT_INDEX_FAILED`, previous active version stays; RQ classifies it non-retryable (`UNEXPECTED_ERROR`). `missing` general: contextual retrieval 404 → `OllamaModelNotLoadedError`, as today.

### Memory worker — `backend/app/workers/memory_tasks.py:discord_memory_ingest()`

1. `settings = get_settings()`; `resolved = settings.resolve_models()`.
2. `ext = resolved.roles["extractor"]`; `extractor_model = ext.record.config["name"] if ext.record else ""`; `extractor_enabled = settings.discord_memory_extractor_enabled and ext.serving`. Same for the verifier (`ver.serving`). These replace the three `settings.discord_memory_*_model` reads (:39, :86, :99): `DiscordMemoryExtractorAdapter(model=extractor_model, ...)` built only when `extractor_enabled`; `DiscordMemoryVerifierAdapter(model=verifier_model)` only when the verifier is serving and enabled; `DiscordMemoryWorkerService(extractor_enabled=extractor_enabled, extractor_model=extractor_model, ...)`.
3. `QdrantStore(url, timeout, c.memories, memories_sweep=c.all_memories)`; `ModelRouter({...}, settings.load_models(), embedding_refusal=resolved.embedding_refusal())`; `LoggingService` built before the router.
4. `DISCORD_MEMORY_EXTRACTOR_MODEL=<tag>` → `requested_id="env:<tag>"`, `source="env_tag"`, chain of one; tag absent → `disabled` (worker logs; the API's marker is unaffected because the API resolves the same registry against the same Ollama and reaches the same state).

### `scripts/condensation_worker.py`

Flag checks (:24-37) stay first. `settings.load_models().get("condenser", {})` (:41) textually unchanged; now returns the resolved version's config. `GeminiClient` stays hard-wired.

### `scripts/rebuild_qdrant.py` (rewritten), new `scripts/rebuild_memories.py`

- Both: `resolved = settings.resolve_models(allow_missing_collections=True)` first (so an absent target collection is fine and completeness is skipped; a width mismatch still `degrades` and the script refuses); `ModelRouter(..., embedding_refusal=resolved.embedding_refusal())`; `c = settings.qdrant_collections()`; the target version comes from `MODEL_VERSION_EMBEDDING=<id>` in the shell.
- `rebuild_qdrant`: args `--dry-run`, `--document-id`, `--missing-only` (embed only chunks whose uuid5 point id is absent per `existing_point_ids`; upsert with `replace=False`), `--confirm` (required when the target collection already holds points and `--missing-only` is not given). Embeds with `side="passage"`. **Never writes `document_versions.embedding_model`.** Prints `{"embedding_version", "collection", "documents", "chunks", "embedded", "skipped_existing", "points_after", "active_chunks", "dry_run"}` — `points_after == active_chunks` is the completeness signal.
- `rebuild_memories`: iterates the `memories` table via the auxiliary store; `router.embed(content, side="passage")`; `qdrant.upsert_memory(...)`; no Postgres writes; same `--missing-only`/`--dry-run`; prints `points_after` vs `memories_rows`.

### `scripts/cleanup_worker.py`, `forget_member.py`, `migrate_document_storage.py`

`c = settings.qdrant_collections()` (probe-free, pure). cleanup: `QdrantStore(..., documents_collection=c.documents, documents_sweep=c.all_documents)`; forget_member: `QdrantStore(url, timeout, c.memories, c.documents, memories_sweep=c.all_memories, documents_sweep=c.all_documents)`; migrate: `c.documents`. Every `settings.qdrant_documents_collection` / `qdrant_memories_collection` read in backend/ becomes `c.documents` / `c.memories` (the Settings fields stay: they are the BASE).

### Launcher — `run-local-ai-core.bat`

- The pull block moves **above** the worker starts (:116). Replace :131-136 and :143-148 with:
  ```bat
  pushd backend
  for /f "usebackq delims=" %%T in (`..\.venv\Scripts\python.exe -m app.config.model_registry --ollama-pull-list`) do (
      call :ensure_model "%%T"
      if errorlevel 1 ( popd & goto :error )
  )
  for /f "usebackq tokens=1,2 delims=	" %%T in (`..\.venv\Scripts\python.exe -m app.config.model_registry --ollama-create-list`) do call :ensure_created "%%T" "%%U"
  popd
  ```
  (`pushd backend` because the launcher never runs `pip install -e .`; the tab delimiter is literal.) The extractor's flag-conditional pull disappears: the list already omits off roles.
- New label `:ensure_created tag modelfile`: `ollama list | findstr` → present → `exit /b 0`; Modelfile missing → `echo [SETUP] %~1 must be built by hand (%~2 not found); the role resolves missing until then` → `exit /b 0`; else `ollama create %~1 -f %~2`; on error print a warning and `exit /b 0`. A create-built tag never halts the boot (invariant #5); the resolver marks the role `missing`/`disabled` and BM25 keeps serving.

### Docker workers

`docker-compose.yml`: `DISCORD_MEMORY_EXTRACTOR_MODEL: ${DISCORD_MEMORY_EXTRACTOR_MODEL:-}`; add `MODEL_VERSION_EXTRACTOR: ${MODEL_VERSION_EXTRACTOR:-}`, `MODEL_VERSION_VERIFIER: ${MODEL_VERSION_VERIFIER:-}`, `MODEL_VERSION_EMBEDDING: ${MODEL_VERSION_EMBEDDING:-}` on the three workers (the before-validator maps `""` → None). The image bakes `backend/` (registry included): a registry edit reaches compose workers only after `docker compose build` — stated in `docs/model_registry.md`; the launcher's host workers read the checkout. Test `backend/tests/test_compose_defaults.py`: no `*_MODEL` or `MODEL_VERSION_*` line carries a non-empty default.

### CI — `.github/workflows/ci.yml`

- static: parse list gains `backend/app/config/model_versions.yaml`; new step `working-directory: backend`, `run: python -m app.config.model_registry --check`.
- retrieval-eval: the regex step (:272-291) is **deleted**; the job `env` gains `RAG_CONTEXTUAL_RETRIEVAL_ENABLED: "false"`, `RAG_RERANKER_ENABLED: "false"` (same idiom as conftest). Probes run for real there: general → `missing`, ocr → `disabled`, embedding → active with an absent collection on an empty DB (fine). `/health.model_fallback` reads `"fallback"` in that job; nothing in CI reads it.
- `:252` cache key stays hard-coded; `backend/tests/test_model_registry_check.py` asserts it equals `"ollama-" + registry embedding active `config.revision``.

### Tests — `backend/tests/conftest.py` and new files

- conftest: `os.environ["MODEL_STARTUP_PROBES"] = "false"` beside :26-37 (mocked 3-d embeds and `*_test` collections would contradict a real 1024-d probe). Every role resolves to its pointer with `verified: false`; `/health.model_fallback == "ok"` (reranker flag off → `off`, not a deviation).
- Fixture `registry_app(monkeypatch)`: `get_settings.cache_clear()`; set `MODEL_STARTUP_PROBES=true`, `MODEL_REGISTRY_PATH=<fixture>`; monkeypatch `ProductionProbes.*` and the reranker loader; `yield TestClient(app)`; teardown `get_settings.cache_clear()` and assert `get_settings().model_startup_probes is False`. Any test setting `MODEL_VERSION_*` uses this fixture.
- `test_model_registry.py`: shipped file loads; `flat_models()` equals a literal of today's five `models.yaml` blocks; reserved-key rejection; suffix rules; `chain()` order and `fallback: false`; `derive_collections` composition (`documents_lab` + `e5l` → `documents_lab_e5l`) and the alias error; `resolve()` table-driven statuses with fake probes (tags None → unverified; absent+corpus>0 → degraded; count short → incomplete; flag off → off; ocr enabled:false → off; exhausted chains); `deviates` set; `--check` on the shipped file; import leaves pydantic out of `sys.modules` (subprocess).
- `test_reranker_versions.py`: fallbacks loaded with `local_files_only=True`; parity rejection; activation forced from the record; `export.json` mismatch rejection; empty chain → `no_versions`, no raise; flag off → `off` and `fallback_flag() == "ok"`; all rejected → `disabled`, boot succeeds (the deliberate rewrite of test_reranker_service.py:84-89); lazy reload uses `self.loaded.loader_kwargs()`.
- `test_model_registry_app.py` (brief §4 row 1): broken active reranker loader → `/models.registry.reranker.loaded == previous`, `/health.model_fallback == "fallback"`, `/health.status == "ok"`, ATTENTION file exists, `model_version_fallback` logged; `evaluate_rag --write-baseline` against it exits 1.
- `test_qdrant_sweep.py`: two memories collections, one delete, both empty; cleanup with the second documents collection raising keeps `cleanup_pending`.
- `test_postgres_embedding_cache.py` gains the identity-equality test (§5); `test_memory_service.py` asserts every write path calls `embed(side="passage")`; `test_job_queue_routing.py:65` asserts `discord_memory_extractor_model is None` and that `resolve()` yields `extractor-v0`; `test_worker_extractor_model.py`: worker receives the resolver's name when the env var is unset; `git check-ignore data/models/x/model.safetensors` succeeds and `data/models/x/export.json` is not ignored.

### Report writers and the nightly (invariant #4 wiring)

| Script | Change |
|---|---|
| `scripts/evaluate_rag.py` | reads `/models` once: `registry`, `rag`. `--write-baseline` refuses (exit 1) when any `registry[*].fallback`; writes `versions: {general, embedding, reranker: loaded}` and `flags: {contextual_retrieval, reranker}`. Gate: when `baseline.versions` exists compare `registry[role].requested` for embedding always, reranker only if `baseline.flags.reranker`, general only if `baseline.flags.contextual_retrieval` (mismatch → exit 1, same shape as `embedding_model`); a baseline without `versions` prints the T16-style WARNING |
| `scripts/nightly_eval.py` | `env` drops every `MODEL_VERSION_*`; after healthy, GET `/models`; exit **94** (ATTENTION with the registry view) when any role with status ∉ {`off`, `unconfigured`} has `source != "registry"` or `fallback`, or `rag.reranker`/`rag.contextual_retrieval` is false |
| `training/common/eval_heldout.py` | GET `{base_url}/models`; summary gains `versions` (loaded ids of general/embedding/reranker), `rag`; refuses to write when any `fallback` (exit 1) |
| `training/common/run_mteb.py` | `--version-id` (optional); summary gains `versions: {"embedding": version_id}` (MTEB talks to Ollama directly, so the id is declared, and `--check` verifies `summary.model == config.name`) |
| `training/common/eval_stack.py` | `--model-version ROLE=ID` (repeatable) → `MODEL_VERSION_<ROLE>` injected into `stack_env` only |
| `.env.example` | `DISCORD_MEMORY_EXTRACTOR_MODEL` line commented with the new meaning; `MODEL_VERSION_*` documented as shell-only for measurement, never in `.env`; the operating machine's `.env` line is removed by hand (runbook + CHANGELOG line) |
| `scripts/memory_e2e_eval.py:432,:442` | `model=settings.resolve_models().model_name("extractor")` / `("verifier")` |
| `scripts/check_operational_alerts.py` | `model_fallback_alert=(settings.logs_path/"ATTENTION_model_fallback.txt").exists()` in the payload and in the `--fail-on-alert` condition; `check-alerts-once.bat:29` popup names both files |
| `dashboard.js` | `componentLabels.model_fallback = "Phiên bản mô hình"` (:160-165); after the three model rows (:186-190) one `kvRow` per `models.registry` role: `"${loaded ?? '—'} (${status})"`, `title = reason`, red when `fallback` |
| `app.js:1126-1145` | same rows (reranker included) under the existing three |
| `discord_bot/client.py:77-85` | `HEALTH_ROWS += (("model_fallback", "Model versions"),)` — `ok` ✅, `fallback` ⚠️ |
| `backfill_chunk_metadata.py:134` | `load_config().get("rag", {})` (fix in passing) |
| Docs | `docs/model_registry.md` (runbook: promotion/demotion order, `--check` rules, Docker note, revert), `docs/adr/0001-model-version-registry.md`, README/DEVELOPMENT_PLAN §3e/models.yaml header, `.scratch/model-registry/spec.md`, CHANGELOG |

### What happens on each failure kind (every row BOOTS unless marked)

| Failure | Detected by | Outcome | Surfaces as |
|---|---|---|---|
| registry missing / invalid / rule violation | `load_registry` | **boot refused** in every process (`ModelRegistryError` names file+role+id) | CI `--check` before merge |
| `MODEL_VERSION_<ROLE>` names an unknown id | `resolve` step 1 | **boot refused**, message names the env var | — |
| both extractor pins (or both verifier pins) set | Settings validator | **boot refused** before any I/O | — |
| env base aliases a version's collection | `derive_collections` | **boot refused** | — |
| Ollama unreachable / `/api/tags` past health timeout | `ollama_tags()` → None | every Ollama role `unverified`, pointer kept | `verified: false`; not a fallback; first use as today |
| tag absent, earlier version's tag present | tags | `fallback` | `model_version_fallback`; `model_fallback: "fallback"`; ATTENTION; nightly 94; dashboard/app/Discord rows |
| tag absent, no fallback | tags | general → `missing` (first use 502 as today); embedding → `missing` (dense 502 at first use); ocr → `disabled`, `enabled: false`; extractor/verifier/condenser → `disabled` | same signals |
| `digest` ≠ `/api/tags` digest | tags | that version treated as absent | same |
| probe embed timeout / error | `ollama_embed_dimension` → None | embedding `unverified` | first query surfaces the real error |
| probe width ≠ `dimensions`, or existing collection size ≠ width | embed / `collection_dimension` | embedding `degraded`; `router.embed` refuses up front | `/rag/search`, `/rag/chat`, `/chat` (memory search), `/memory/*` → 502 `MODEL_NOT_LOADED` with the reason; index runs fail `DOCUMENT_INDEX_FAILED`; ATTENTION; nightly 94 |
| pointer names a collection that does not exist while the corpus is non-empty (promotion/demotion without rebuild) | `collection_dimension` None + `postgres_counts` | embedding `degraded` (reason names the rebuild command) | same — and never the 2 s `_retry` sleep + `QDRANT_UNAVAILABLE` per query the naive path would give |
| collection exists but holds fewer points than active chunks / memories rows | `qdrant_point_count` | embedding `incomplete`; dense keeps serving (BM25 covers the gap in hybrid) | ATTENTION; nightly 94; `/models.registry.embedding.reason` names both counts and `--missing-only` |
| Qdrant or Postgres not answering at probe time | sentinel / None | embedding `unverified` | `/health.qdrant` / `postgres` already say so |
| cloud provider key absent | `registered_providers` | general → earlier version with a registered provider, else `missing`; condenser → `disabled` | fallback signals when a switch happened |
| `[rerank]` extra missing while enabled | warmup `import` | every version rejected → reranker `disabled`, source `fallback` | `reranker_version_rejected` ×n; signals; the launcher's `.env` pin still prevents this on clean machines (`off`, not a deviation) |
| fallback hub snapshot not in the HF cache | warmup `not_cached` | next version; never a download | `reranker_version_rejected reason=not_cached` |
| checkpoint load / digest / activation / `num_labels` / `max_length` / parity | warmup | next version; exhausted → `disabled` | reason in the log and `/models.registry.reranker.reason` |
| timed predict over `max_ms` | warmup | serves; `latency_ms` recorded | WARNING; `/models.registry.reranker.latency_ms` |
| reranker `active: null` | `reranker_chain() == ()` | `unconfigured`, pass-through; no raise | not a deviation |
| `RAG_RERANKER_ENABLED=false` / yaml off | `flag_off` | `off` | not a deviation (`model_fallback: "ok"` in the suite and on machines without the extra) |

---

## 5. Cache and index safety

### Embedding cache fingerprint (constraint 11)

What the cache keys on today, unchanged: `content_hash + config.name + revision + dimensions + fingerprint(config minus {revision, model_revision, normalization}) + fingerprint(normalization)` (`postgres_document_service.py:554-578`, unique tuple `postgres/models.py:1147`). Every key of the flat embedding dict is in the key.

Four layers keep registry metadata out of it:

1. **Structural.** The runtime block is the `config:` sub-mapping and `flat_config` is a deep copy of exactly that mapping; there is no merge step. `id`, `collection_suffix`, `eval`, `vram_mib`, `digest`, `ollama`, `provenance`, `probe` are siblings. The embedding refusal reason travels as a `ModelRouter` constructor argument, never as a key.
2. **Validation.** `load_registry` rejects any `RESERVED_RECORD_KEYS` name inside `config:` (CI `--check`), and the reserved set deliberately excludes `provider` and `revision`, which `config:` needs — so the shipped file passes its own check.
3. **Landing without invalidation.** `embedding-v0.config` is byte-identical to today's `models.embedding` block (five keys, no prefixes); the fingerprint before and after the registry lands is the same string. No re-embedding on deploy.
4. **Locked by tests.** `_cache_identity` on `resolved.flat_models()["embedding"]` equals the identity of a hand-written flat dict with the same name/revision/dimensions/normalization/prefixes; and `flat_models()` equals a literal of today's blocks on the landing commit.

Deliberate consequence: a prefix change IS a fingerprint change (vectors differ), so `query_prefix`/`passage_prefix` live inside `config:`; `collection_suffix` lives outside because it changes where vectors are stored, not what they are. Stated in the doc: because `:570` fingerprints `query_prefix` too, a query-only instruction change still forces a new version, a new suffix and a full re-embed.

The OCR fingerprint (`ocr_service.py:30-36`) is likewise fed from `config:` only; the resolver's single edit (`enabled: False` on a `disabled` copy) is not in that hash.

### One collection pair per embedding version (constraints 13/14)

- **Derivation** (`derive_collections`, pure): `documents = base + ("_" + suffix if suffix)`, `base = settings.qdrant_documents_collection`; same for memories. v0 keeps `documents` / `documents_lab` / `documents_test`; suffix `e5l` gives `documents_e5l` on production and `documents_lab_e5l` on the lab stack. The suffix comes from the **pointer** — the same pointer that picks the query model — so one decision names both. The env base may not alias another version's derived name (boot refused).
- **Validation at load** (`--check`): suffix unique, `[a-z0-9_]*`, `""` at most once. Two registered versions can therefore never share a collection — the only thing that makes a same-width swap (qwen3-embedding 1024 → e5-large 1024) detectable, since `qdrant_store.py:156-165` checks size only and search checks nothing.
- **Validation at start** (probe): one real embed → width must equal `config.dimensions` and, if the collection exists, its size; an absent collection with a non-empty corpus is itself a contradiction (the pointer moved without a rebuild). Any **verified** contradiction → `degraded`: `router.embed` refuses before Ollama, so nothing ever writes foreign vectors into a collection and nothing 503s per query after a 2 s retry. "Could not decide" is `unverified`, never `degraded`.
- **Completeness at start** (probe): `point_count(collection) < active chunks` (or `< memories rows`) → `incomplete`: served, but audited (ATTENTION, nightly refusal) with the exact remedy in the reason. Limitation stated in the doc: the check is one-directional (legacy `index_version` points and not-yet-cleaned superseded versions can only make the count larger), so it catches a frozen collection, not a single missing chunk.
- **An inactive collection is frozen, not mirrored.** Writes go to one collection (`postgres_document_service.py:453/:522`, `memory_service.py:25/:43/:68`); the cleanup worker only deletes. Therefore **demotion follows the promotion order**: rebuild the target's two collections with `MODEL_VERSION_EMBEDDING=<target>` (`--missing-only` when they exist), verify counts, then move `active`. The registry header and the runbook say so; the `incomplete` probe catches the operator who skips it.
- **Deletes fan out.** `QdrantStore` carries the sweep (`all_documents` / `all_memories`, active first); `delete_memory`, `delete_document_version`, `delete_document` delete from every existing registered collection and raise on the first failure of an existing one — before `PostgresCleanupService` (`:161`, `:200`) flips the row, so a half-swept version stays `cleanup_pending` and the retry is idempotent. `forget_member` and `MemoryService.delete/remove_with_id` get the same sweep through the store. Revoked memories cannot resurrect on demotion.
- **No automatic fallback for embedding.** A fallback would let an index run write v0 vectors under a v1 pointer and make `document_versions.embedding_model` lie. Keep-pointer-and-refuse is the only truthful state.
- **Provenance in Postgres** (invariant #1, #8): `document_versions.embedding_model` (existing, unwritten) is written **only by `activate()`** with the index process's resolved embedding version id — "the version whose vectors were produced at activation". Rebuild never writes it (a rebuild into a candidate collection would otherwise stamp every serving row with an id production does not serve). What is served now is the registry pointer (git history) and `/models.registry`; per-collection point counts are the completeness signal. No new table.
- **CI**: the Ollama cache key is asserted equal to `embedding-v0.config.revision` by a static test.

---

## Changes from draft

Blockers and majors (all applied):

1. **Reserved keys** (invariants blocker, ux major): `provider` and `revision` removed from `RESERVED_RECORD_KEYS`; the shipped file now passes its own `--check`; a test loads the shipped file and compares `flat_models()` to today's blocks.
2. **Inactive collection "faithful mirror"** (index blocker, ux major): claim deleted; demotion = promotion order; new completeness probe (`qdrant_point_count` vs Postgres counts → `incomplete`, deviating but serving); `rebuild_qdrant --missing-only` (+ `existing_point_ids`, `upsert_chunks(replace=False)`) and `rebuild_memories.py --missing-only`.
3. **`ollama create` tags halt the launcher** (ux blocker, invariants major): `ollama: {source, modelfile, gguf_sha256}` record field; `--ollama-create-list`; `:ensure_created` never halts; `pushd backend`; pull block moved above the worker starts; Modelfile and `export.json` tracked under `data/models/` with an extension-agnostic ignore rule.
4. **`deviates` vs flag-off** (invariants major): `Status` gains `off` (feature flag / ocr `enabled: false`) and `unconfigured` for an empty reranker chain; `WarmupOutcome.status` is four-valued (`loaded | rejected_all | flag_off | no_versions`) and main.py maps it explicitly; the suite's `model_fallback` is `"ok"`.
5. **Fallback downloads** (invariants major): entries after `versions[0]` load with `local_files_only=True`; reject reason `not_cached`.
6. **Deletes reach only the active collection** (invariants major, index majors 3 and 4): sweep inside `QdrantStore` (constructor `documents_sweep`/`memories_sweep`), raise-before-Postgres semantics, tests with two collections.
7. **Rebuild stamps the candidate** (invariants major, index major 5): rebuild never writes `document_versions.embedding_model`; only `activate(..., embedding_version=)` does.
8. **`discord_memory_extractor_model → None` fallout** (invariants major): `test_job_queue_routing.py:65` updated; `memory_e2e_eval.py` reads `resolve_models().model_name(...)`; `.env.example` line commented; `docker-compose.yml` defaults emptied + `MODEL_VERSION_*` pass-throughs + a compose-defaults test (ux major 3).
9. **Absent collection passes the probe** (index major 2): absent + non-empty corpus → `degraded`; `Overrides.allow_missing_collections` for the rebuild scripts; `EmbeddingRefusedError(OllamaModelNotLoadedError)` refuses in `router.embed` before any Qdrant call, so no per-query retry sleep.
10. **#4 gate unverifiable for heldout/mteb** (ux major 4): `eval.reports: {gate: path}`; `eval_heldout` and `run_mteb` stamp `versions` and refuse on fallback; `--check` verifies the stamp per gate; `digest.sha256: null` on a candidate is a skipped check, never a rejection.
11. **Nowhere to look** (ux major 6): dashboard.js/app.js registry rows, `check_operational_alerts.py` + `check-alerts-once.bat`, Discord `HEALTH_ROWS`.

Minors, each decided:

12. Test fakes with `embed(self, text)` — **keyword-required `side`**, all seven fakes listed and all ten call sites (including the two rollback sites at memory_service.py:72/:84) enumerated; loud beats silent-wrong-prefix.
13. Stamped bare baseline fails CI on `general` — gate on `requested`, compare reranker/general only when the baseline's `flags` say they were on; `/models.rag` added (additive) so the flags are recorded from the server.
14. `--check` in the static job — `PROJECT_ROOT` defined in model_registry.py, stdlib+yaml at import, `working-directory: backend`, import-light test, pytest twin `test_model_registry_check.py`.
15. `from_config(versions=())` — empty chain is `no_versions` → `unconfigured`; never indexed.
16. Fallback app test leaking Settings — `registry_app` fixture clears the lru cache before and after and asserts probes are off again.
17. Env-base alias — checked in `derive_collections`, boot refused.
18. `MODEL_VERSION_*` inherited by the nightly — nightly strips them, checks `source == "registry"` and the shipped flags (exit 94); `eval_stack --model-version`; `.env.example` says shell-only.
19. Lazy reload bypassing the record — `self.model_name = loaded.name` and `loader_kwargs()` on the lazy path.
20. Parity by coincidence — `export.json` contract; warmup rejects an `activation_fn` mismatch; `--record-probe` refuses `path` versions.
21. Launcher ordering / embedding exhausted chain — pulls before workers; embedding step 6 = `missing`; collection-only consumers use the pure `derive_collections` (no probe, no resolve).
22. ci.yml regex — replaced by env flags in the retrieval-eval job (brief §3d.6 recommendation); one less shape dependency.
23. ci.yml:252 cache key — kept hard-coded, asserted by a static test.
24. `Settings.qdrant_collections()` no longer goes through `resolve()` at all (draft had it returning `resolve_models().collections`).
25. `vram` budget moved into the data file (`budget.vram_mib`); ACTIVE versions must carry a non-null `vram_mib`.
26. `ocr` with `config.enabled: false` in the file is `off` (deliberate), not probed — the draft would have reported a deliberate off as `disabled`/deviating when the tag was also absent.

Kept from the draft: restart-to-switch through `Settings.load_models()`; `config:` verbatim with no merge; positional fallback order plus `fallback: false`; no automatic embedding fallback; `/health` keeps `status: "ok"` with the flat `model_fallback` key; reranker chain ends in `disabled` with source `fallback`; loader forces the record's activation; `data/models/<role>/<id>/`; vision `active: null`; `MODEL_VERSION_<ROLE>` accepts ids only (no `off`); `max_ms` is a warning; ATTENTION marker written by the API only; grandfathered unstamped v0 reports warn; per-process cache on `Settings` PrivateAttrs; `models:` block deleted from models.yaml; OCR `revision` left out of v0.

## Deliberately not done

- **No `--stamp-only` for `document_versions.embedding_model`.** Rewriting a historical column to the current pointer is the exact lie the column exists to avoid; the pointer's history is the registry file in git, and `/models.registry` says what serves now.
- **`discord_memory_candidates.extractor_model` keeps the Ollama tag**, not `<version_id>@<tag>`: the tag is what actually ran (the column at `:952` is written from the adapter's result); a format change would touch the review dashboard and the benchmark readers for no additional truth. The worker's `model_version_resolved` log carries the id.
- **No third `/health.model_fallback` value** (`degraded`/`incomplete` show as `"fallback"` in the flat key); the owner fixed the two values, and `/models.registry.embedding.status` distinguishes them.
- **No `--hf-cache-list` / launcher pre-caching of hub snapshots.** `versions[0]` keeps today's behaviour (the operator-chosen active may download at warmup); fallbacks never download; the runbook names the one-line pre-cache command.
- **No `OCR_ENABLED` env switch**; turning OCR off per machine still means editing the registry (`config.enabled: false` → `off`).
- **`docker-compose.yml:72` `SCHEMA_VERSION:-v1` vs Settings default `v2`** is a pre-existing drift noticed in passing; out of scope, flagged for the owner.
- **Completeness probe is one-directional** (shortfall only); an exact set comparison per boot would cost a full id scroll and is what `--missing-only` does on demand.
- **No per-collection provenance table** (invariant #8): point counts and the version's `collection_suffix` are the evidence until a measured need appears.
- **`chat_service.py:121/:175` memory search is not wrapped**: on an embedding `degraded` state `/chat` returns 502 `MODEL_NOT_LOADED` like every other embed consumer — refusing loudly is the intended contract, and a silent "no memories" would be the failure mode the index-lens critique named.
- **Vision row in app.js disappears** (consequence of `active: null`); restoring it needs either a vision pointer or a UI change, both the owner's call.
- **`rag.reranker.model` is removed from models.yaml** rather than mirrored; `from_config`'s legacy read of it survives only for `versions=None` tests.