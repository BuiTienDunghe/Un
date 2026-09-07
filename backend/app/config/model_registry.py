"""Model version registry: one record per model version, one `active` pointer per role.

Read ONCE per process at start (Settings.registry() / resolve_models()); restart to
switch. The data file is backend/app/config/model_versions.yaml; the acceptance rules
are in .scratch/model-registry/spec.md and the contract in design.md.

Import-light: module level imports stdlib + yaml ONLY (the CI static job has no
pydantic; a test asserts `import app.config.model_registry` leaves pydantic out of
sys.modules). Settings, httpx, the Qdrant client and the Postgres models are imported
lazily inside ProductionProbes / the CLI. loguru is imported lazily for the same reason
(the static job installs PyYAML and nothing else).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal, Protocol

import yaml

if TYPE_CHECKING:  # settings.py imports THIS module; the reverse import stays lazy
    from app.config.settings import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]          # settings.py may import it from here
DEFAULT_REGISTRY_PATH = Path(__file__).with_name("model_versions.yaml")
CI_WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
ATTENTION_FILENAME = "ATTENTION_model_fallback.txt"
PROBE_TEXT = "local-ai-core probe"

ROLES = ("general", "condenser", "embedding", "vision", "ocr", "reranker", "extractor", "verifier")
MODEL_ROLES = ("general", "condenser", "embedding", "vision", "ocr", "extractor", "verifier")   # carry `config:`
NEVER_NULL_ROLES = ("general", "embedding")
NO_FALLBACK_ROLES = ("embedding",)                                  # constraint 13
DISABLE_ON_MISS_ROLES = ("ocr", "extractor", "verifier", "condenser")
PINNABLE_ROLES = ("general", "condenser", "embedding", "ocr", "reranker", "extractor", "verifier")  # MODEL_VERSION_<ROLE>
GATED_ROLES = ("general", "embedding", "reranker", "extractor")     # --check: the ACTIVE version needs an eval report
PROVIDERS = ("ollama", "gemini", "deepseek", "sentence-transformers")
RESERVED_RECORD_KEYS = frozenset({                                   # a key from this set INSIDE `config:` is a load error
    "id", "config", "fallback", "vram_mib", "digest", "ollama", "eval", "provenance", "notes",
    "collection_suffix", "hub", "path", "activation", "num_labels", "max_length", "probe",
})                                                                   # `provider` and `revision` are NOT reserved (they belong in config)
GATES = ("d1_multidoc", "heldout", "mteb", "extractor_benchmark")
GRANDFATHERED_UNSTAMPED = frozenset({"general-v0", "embedding-v0", "reranker-v0", "extractor-v0"})  # reports without a `versions` stamp: WARNING, not error

Status = Literal["active", "fallback", "unverified", "missing", "degraded", "incomplete",
                 "disabled", "off", "unconfigured", "pending"]
DEVIATING = frozenset({"fallback", "missing", "degraded", "incomplete", "disabled"})
SERVING = frozenset({"active", "fallback", "unverified", "incomplete"})
Source = Literal["registry", "env", "env_tag"]

_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_SUFFIX_PATTERN = re.compile(r"^[a-z0-9_]*$")
# Reason a role is `off` when its feature flag is down: names the flag, so the
# operator reads the remedy off /models.registry instead of grepping Settings.
_FLAG_REASON = {
    "condenser": "DISCORD_CONDENSATION_ENABLED=false",
    "extractor": "DISCORD_MEMORY_EXTRACTOR_ENABLED=false",
    "verifier": "DISCORD_MEMORY_VERIFIER_ENABLED=false (needs DISCORD_MEMORY_EXTRACTOR_ENABLED too)",
}


def _log(level: str, event: str, message: str, **fields: Any) -> None:
    """loguru.bind(event=...) is the idiom of reranker_config; the CI static job has no
    loguru, so a missing package degrades to stdlib logging instead of an ImportError."""
    try:
        from loguru import logger
    except ImportError:
        import logging

        logging.getLogger(__name__).log(getattr(logging, level.upper()), "%s %s", message, fields)
        return
    getattr(logger.bind(event=event, **fields), level)(message)


class ModelRegistryError(ValueError):
    """Registry file or env pin invalid. Raised from load_registry()/resolve()/derive_collections();
    refuses boot in every process (a CI-checked file being corrupt is not an environment
    problem — invariant #5 is about missing optional packages). Message names file, role,
    id and, for a pin, the env variable."""


class QdrantUnreachable:
    """Sentinel type: 'could not decide', distinct from None = 'no such collection'."""

    def __repr__(self) -> str:
        return "QDRANT_UNREACHABLE"


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
        if self.role == "reranker":
            return self.hub if self.hub is not None else str(self.path)
        return str(self.config.get("name", ""))

    @property
    def ollama_tag(self) -> str:
        """config['name'] as /api/tags reports it: no ':' -> 'name:latest'."""
        name = str(self.config.get("name", ""))
        return name if ":" in name else f"{name}:latest"

    def loader_kwargs(self) -> dict[str, Any]:
        """Reranker only. {revision?, local_files_only?, activation?} — only the set ones;
        local_files_only=True when `path` is set or HF_HUB_OFFLINE is set. {} for a
        legacy single-name service, so `lambda _:` loaders keep working. `activation`
        is the STRING; RerankerService._load_cross_encoder builds the torch module."""
        kwargs: dict[str, Any] = {}
        if self.revision is not None:
            kwargs["revision"] = self.revision
        if self.path is not None or os.getenv("HF_HUB_OFFLINE"):
            kwargs["local_files_only"] = True
        if self.activation is not None:
            kwargs["activation"] = self.activation
        return kwargs


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

    def get(self, role: str, version_id: str) -> VersionRecord:
        entry = self.roles.get(role)
        if entry is None:
            raise ModelRegistryError(f"{self.path}: unknown role {role!r}")
        for record in entry.versions:
            if record.id == version_id:
                return record
        raise ModelRegistryError(
            f"{self.path} roles.{role}: no version with id={version_id!r} "
            f"(known: {', '.join(record.id for record in entry.versions)})"
        )

    def chain(self, role: str, start: str | None = None) -> tuple[VersionRecord, ...]:
        """[start or active] then the versions BEFORE it, nearest first, skipping fallback: false.
        Length <= 1 for NO_FALLBACK_ROLES. Empty when active is None."""
        entry = self.roles.get(role)
        if entry is None:
            raise ModelRegistryError(f"{self.path}: unknown role {role!r}")
        start_id = start if start is not None else entry.active
        if start_id is None:
            return ()
        head = self.get(role, start_id)
        if role in NO_FALLBACK_ROLES:
            return (head,)
        index = [record.id for record in entry.versions].index(start_id)
        earlier = [record for record in reversed(entry.versions[:index]) if record.fallback]
        return (head, *earlier)


# ── load + validate ─────────────────────────────────────────────────────────────

def _fail(path: Path, message: str, *, role: str | None = None, version_id: str | None = None) -> ModelRegistryError:
    where = str(path)
    if role is not None:
        where += f" roles.{role}"
    if version_id is not None:
        where += f" id={version_id}"
    return ModelRegistryError(f"{where}: {message}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _parse_probe(path: Path, role: str, version_id: str, raw: Any) -> RerankerProbeSpec:
    fail = lambda message: _fail(path, message, role=role, version_id=version_id)  # noqa: E731
    if not isinstance(raw, Mapping):
        raise fail("probe must be a mapping {pairs, scores, tolerance, max_ms}")
    raw_pairs = raw.get("pairs")
    if not isinstance(raw_pairs, list):
        raise fail("probe.pairs must be a list of [question, passage] pairs")
    pairs: list[tuple[str, str]] = []
    for item in raw_pairs:
        if not (isinstance(item, list) and len(item) == 2 and all(isinstance(text, str) for text in item)):
            raise fail("every probe.pairs entry must be a [question, passage] pair of strings")
        pairs.append((item[0], item[1]))
    raw_scores = raw.get("scores")
    scores: tuple[float, ...] | None = None
    if raw_scores is not None:
        if not isinstance(raw_scores, list) or not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in raw_scores):
            raise fail("probe.scores must be null or a list of numbers")
        if len(raw_scores) != len(pairs):
            raise fail(f"probe.scores has {len(raw_scores)} entries for {len(pairs)} pairs")
        scores = tuple(float(value) for value in raw_scores)
    tolerance = raw.get("tolerance", 0.05)
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool):
        raise fail("probe.tolerance must be a number")
    max_ms = raw.get("max_ms")
    if max_ms is not None and not _is_int(max_ms):
        raise fail("probe.max_ms must be an integer or null")
    return RerankerProbeSpec(pairs=tuple(pairs), scores=scores, tolerance=float(tolerance), max_ms=max_ms)


def _parse_version(path: Path, role: str, raw: Any, position: int) -> VersionRecord:
    if not isinstance(raw, Mapping):
        raise _fail(path, f"versions[{position}] must be a mapping", role=role)
    version_id = raw.get("id")
    if not isinstance(version_id, str) or not _ID_PATTERN.match(version_id):
        raise _fail(path, f"versions[{position}].id must match [A-Za-z0-9._-]+ (got {version_id!r})", role=role)
    fail = lambda message: _fail(path, message, role=role, version_id=version_id)  # noqa: E731

    provider = raw.get("provider")
    if provider not in PROVIDERS:
        raise fail(f"provider must be one of {', '.join(PROVIDERS)} (got {provider!r})")

    if role in MODEL_ROLES:
        config = raw.get("config")
        if not isinstance(config, Mapping):
            raise fail("config must be a mapping (the verbatim runtime block)")
        reserved = sorted(RESERVED_RECORD_KEYS.intersection(config))
        if reserved:
            raise fail(f"config carries registry key(s) {', '.join(reserved)}; they belong beside config, not inside it "
                       "(every key of config reaches the embedding cache fingerprint)")
        if config.get("provider") != provider:
            raise fail(f"config.provider {config.get('provider')!r} != provider {provider!r}")
        if not isinstance(config.get("name"), str) or not config["name"]:
            raise fail("config.name must be a non-empty string")
        config = copy.deepcopy(dict(config))
    else:
        if "config" in raw:
            raise fail("a reranker record carries no config block (its loader reads hub/path/revision/activation)")
        config = {}

    fallback = raw.get("fallback", True)
    if not isinstance(fallback, bool):
        raise fail("fallback must be a boolean")
    vram_mib = raw.get("vram_mib")
    if vram_mib is not None and not _is_int(vram_mib):
        raise fail("vram_mib must be an integer or null")

    digest: str | None = None
    digest_file: str | None = "model.safetensors" if role == "reranker" else None
    raw_digest = raw.get("digest")
    if isinstance(raw_digest, str):
        digest = raw_digest
    elif isinstance(raw_digest, Mapping):
        sha = raw_digest.get("sha256")
        if sha is not None and not isinstance(sha, str):
            raise fail("digest.sha256 must be a string or null")
        digest = sha
        file_name = raw_digest.get("file")
        if file_name is not None:
            if not isinstance(file_name, str) or not file_name:
                raise fail("digest.file must be a non-empty string")
            digest_file = file_name
    elif raw_digest is not None:
        raise fail("digest must be a string, a {file, sha256} mapping or null")

    ollama = OllamaSource()
    raw_ollama = raw.get("ollama")
    if raw_ollama is not None:
        if not isinstance(raw_ollama, Mapping):
            raise fail("ollama must be a mapping {source, modelfile, gguf_sha256}")
        source = raw_ollama.get("source", "hub")
        if source not in ("hub", "modelfile"):
            raise fail(f"ollama.source must be hub or modelfile (got {source!r})")
        modelfile = raw_ollama.get("modelfile")
        if modelfile is not None and not isinstance(modelfile, str):
            raise fail("ollama.modelfile must be a path string or null")
        if source == "modelfile" and not modelfile:
            raise fail("ollama.source: modelfile needs ollama.modelfile (the file `ollama create` reads)")
        gguf = raw_ollama.get("gguf_sha256")
        if gguf is not None and not isinstance(gguf, str):
            raise fail("ollama.gguf_sha256 must be a string or null")
        ollama = OllamaSource(source=source, modelfile=_resolve_path(modelfile) if modelfile else None, gguf_sha256=gguf)

    collection_suffix = ""
    if role == "embedding":
        if "collection_suffix" not in raw:
            raise fail("embedding versions must declare collection_suffix ('' for the bare documents/memories pair)")
        suffix = raw.get("collection_suffix")
        suffix = "" if suffix is None else suffix
        if not isinstance(suffix, str) or not _SUFFIX_PATTERN.match(suffix):
            raise fail(f"collection_suffix must match [a-z0-9_]* (got {suffix!r})")
        collection_suffix = suffix

    hub: str | None = None
    version_path: Path | None = None
    revision: str | None = None
    activation: Literal["identity", "sigmoid"] | None = None
    num_labels: int | None = None
    max_length: int | None = None
    probe: RerankerProbeSpec | None = None
    if role == "reranker":
        hub = raw.get("hub")
        raw_path = raw.get("path")
        if (hub is None) == (raw_path is None):
            raise fail("exactly one of hub | path is required")
        if hub is not None and not isinstance(hub, str):
            raise fail("hub must be a string")
        if raw_path is not None:
            if not isinstance(raw_path, str):
                raise fail("path must be a repo-relative directory string")
            version_path = _resolve_path(raw_path)
        revision = raw.get("revision")
        if hub is not None and not isinstance(revision, str):
            raise fail("hub versions must pin a revision (the snapshot commit)")
        if revision is not None and not isinstance(revision, str):
            raise fail("revision must be a string")
        activation = raw.get("activation")
        if activation not in (None, "identity", "sigmoid"):
            raise fail(f"activation must be identity, sigmoid or null (got {activation!r})")
        num_labels = raw.get("num_labels")
        if num_labels is not None and not _is_int(num_labels):
            raise fail("num_labels must be an integer or null")
        max_length = raw.get("max_length")
        if max_length is not None and not _is_int(max_length):
            raise fail("max_length must be an integer or null")
        if raw.get("probe") is not None:
            probe = _parse_probe(path, role, version_id, raw.get("probe"))

    eval_reports: dict[str, Path | None] = {}
    split_sha256: str | None = None
    raw_eval = raw.get("eval")
    if raw_eval is not None:
        if not isinstance(raw_eval, Mapping):
            raise fail("eval must be a mapping {reports: {gate: path}, split_sha256?}")
        reports = raw_eval.get("reports", {}) or {}
        if not isinstance(reports, Mapping):
            raise fail("eval.reports must be a mapping gate -> path")
        for gate, report in reports.items():
            if gate not in GATES:
                raise fail(f"eval.reports gate {gate!r} is not one of {', '.join(GATES)}")
            if report is not None and not isinstance(report, str):
                raise fail(f"eval.reports.{gate} must be a path string or null")
            eval_reports[gate] = _resolve_path(report) if report else None
        split_sha256 = raw_eval.get("split_sha256")
        if split_sha256 is not None and not isinstance(split_sha256, str):
            raise fail("eval.split_sha256 must be a string or null")

    provenance = raw.get("provenance")
    if provenance is not None and not isinstance(provenance, Mapping):
        raise fail("provenance must be a mapping")

    return VersionRecord(
        role=role, id=version_id, provider=provider, config=config, fallback=fallback, vram_mib=vram_mib,
        digest=digest, digest_file=digest_file, ollama=ollama, collection_suffix=collection_suffix,
        hub=hub, path=version_path, revision=revision, activation=activation, num_labels=num_labels,
        max_length=max_length, probe=probe, eval_reports=eval_reports, split_sha256=split_sha256,
        provenance=dict(provenance) if provenance is not None else None,
    )


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
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ModelRegistryError(f"{path}: cannot read the model registry ({error})") from error
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ModelRegistryError(f"{path}: not valid YAML ({error})") from error
    if not isinstance(document, Mapping):
        raise _fail(path, "top level must be a mapping")

    schema_version = document.get("schema_version")
    if schema_version != 1 or not _is_int(schema_version):
        raise _fail(path, f"schema_version must be 1 (got {schema_version!r}); this resolver does not read a newer file")
    budget = document.get("budget")
    if not isinstance(budget, Mapping) or not _is_int(budget.get("vram_mib")):
        raise _fail(path, "budget.vram_mib (integer) is required — invariant #7 lives in the data file")

    raw_roles = document.get("roles")
    if not isinstance(raw_roles, Mapping):
        raise _fail(path, "roles must be a mapping")
    unknown = sorted(set(raw_roles) - set(ROLES))
    if unknown:
        raise _fail(path, f"unknown role(s) {', '.join(unknown)}; roles are {', '.join(ROLES)}")
    missing = [role for role in ROLES if role not in raw_roles]
    if missing:
        raise _fail(path, f"missing role(s) {', '.join(missing)}; every one of {', '.join(ROLES)} must be listed")

    roles: dict[str, RoleEntry] = {}
    for role in ROLES:
        raw_entry = raw_roles[role]
        if not isinstance(raw_entry, Mapping):
            raise _fail(path, "must be a mapping {active, versions}", role=role)
        if "active" not in raw_entry:
            raise _fail(path, "active is required (null = not served)", role=role)
        active = raw_entry.get("active")
        if active is not None and not isinstance(active, str):
            raise _fail(path, "active must be a version id or null", role=role)
        if active is None and role in NEVER_NULL_ROLES:
            raise _fail(path, "active must not be null (the answer path and the index need this role)", role=role)
        raw_versions = raw_entry.get("versions")
        if not isinstance(raw_versions, list) or not raw_versions:
            raise _fail(path, "versions must be a non-empty list, oldest first", role=role)
        versions = tuple(_parse_version(path, role, raw, position) for position, raw in enumerate(raw_versions))
        ids = [record.id for record in versions]
        duplicates = sorted({vid for vid in ids if ids.count(vid) > 1})
        if duplicates:
            raise _fail(path, f"duplicate version id(s) {', '.join(duplicates)}", role=role)
        if active is not None and active not in ids:
            raise _fail(path, f"active={active!r} is not among the ids ({', '.join(ids)})", role=role)
        if role == "embedding":
            suffixes = [record.collection_suffix for record in versions]
            for record in versions:
                if suffixes.count(record.collection_suffix) > 1:
                    label = "''" if record.collection_suffix == "" else record.collection_suffix
                    raise _fail(path, f"collection_suffix {label} is shared by two versions; two versions can never "
                                      "write into one collection (a same-width swap would be silent)", role=role, version_id=record.id)
        roles[role] = RoleEntry(active=active, versions=versions)

    registry = Registry(path=path, schema_version=1, vram_budget_mib=int(budget["vram_mib"]), roles=roles)
    _log("info", "model_registry_loaded", f"Model registry loaded from {path}", path=str(path), schema_version=1,
         roles={role: entry.active for role, entry in roles.items()})
    return registry


# ── overrides + collections ─────────────────────────────────────────────────────

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


def _env_name(role: str) -> str:
    return f"MODEL_VERSION_{role.upper()}"


_REMEDY_MARKER = "run python -m scripts."


def _remedy_command(reason: str | None) -> str | None:
    """The `python -m scripts.<rebuild> ... with MODEL_VERSION_EMBEDDING=<id>` tail of an
    embedding `degraded` / `incomplete` reason (_probe_embedding writes exactly one, after
    "run "), so the ATTENTION file can print it as its own line; None for every other reason."""
    if not reason or _REMEDY_MARKER not in reason:
        return None
    return reason[reason.index(_REMEDY_MARKER) + len("run "):]


def _pinned(registry: Registry, overrides: Overrides, role: str) -> VersionRecord | None:
    """The MODEL_VERSION_<ROLE> record, or None when the role is not pinned. An unknown
    id refuses boot naming the variable (acceptance E)."""
    pin = overrides.pins.get(role)
    if pin is None:
        return None
    try:
        return registry.get(role, pin)
    except ModelRegistryError as error:
        raise ModelRegistryError(f"{_env_name(role)}={pin!r} names no version of roles.{role} in {registry.path}") from error


def _collection_name(base: str, suffix: str) -> str:
    return f"{base}_{suffix}" if suffix else base


def derive_collections(registry: Registry, overrides: Overrides) -> QdrantCollections:
    """PURE function of the pointer (pin or active) — no probe, no resolve. Used by
    Settings.qdrant_collections() (collection-only consumers: cleanup_worker, forget_member,
    migrate_document_storage) and by resolve(); a test asserts both agree.
    ModelRegistryError when the env base ends with "_<suffix>" of any registered version
    with a non-empty suffix, or when two versions derive the same name under this base
    (the alias hole: QDRANT_DOCUMENTS_COLLECTION=documents_e5l with v0 active)."""
    entry = registry.roles["embedding"]
    pointer = _pinned(registry, overrides, "embedding") or registry.get("embedding", entry.active)  # active never null
    ordered = (pointer, *[record for record in entry.versions if record.id != pointer.id])
    names: dict[str, tuple[str, ...]] = {}
    for base, env_name in ((overrides.documents_collection, "QDRANT_DOCUMENTS_COLLECTION"),
                           (overrides.memories_collection, "QDRANT_MEMORIES_COLLECTION")):
        for record in entry.versions:
            if record.collection_suffix and base.endswith("_" + record.collection_suffix):
                raise ModelRegistryError(
                    f"{env_name}={base!r} ends with _{record.collection_suffix}, the collection_suffix of "
                    f"roles.embedding id={record.id}: the base would alias that version's collection"
                )
        derived = tuple(_collection_name(base, record.collection_suffix) for record in ordered)
        if len(set(derived)) != len(derived):
            raise ModelRegistryError(f"{env_name}={base!r}: two embedding versions derive the same collection name ({', '.join(derived)})")
        names[env_name] = derived
    documents, memories = names["QDRANT_DOCUMENTS_COLLECTION"], names["QDRANT_MEMORIES_COLLECTION"]
    return QdrantCollections(documents=documents[0], memories=memories[0], all_documents=documents, all_memories=memories)


# ── probes ──────────────────────────────────────────────────────────────────────

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
    """Lazy imports of httpx / the Qdrant client / sqlalchemy. Timeouts: ollama_health_timeout_seconds,
    qdrant_timeout_seconds, Postgres connect_timeout 5 s. Every call is one attempt: a
    startup probe that retried would turn "Ollama is slow" into a minute-long boot, and one
    that pulled would violate invariant #5 (a rejected version never downloads)."""

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        self._qdrant_client: Any | None = None
        self.last_counts: PostgresCounts | None = None   # --show prints them beside the registry view

    def ollama_tags(self) -> Mapping[str, str] | None:
        import httpx

        try:
            response = httpx.get(f"{self._settings.ollama_base_url.rstrip('/')}/api/tags", timeout=self._settings.ollama_health_timeout_seconds)
            if not response.is_success:
                return None
            models = response.json().get("models") or []
        except Exception:
            return None
        return {str(item["name"]): str(item.get("digest") or "") for item in models if isinstance(item, Mapping) and item.get("name")}

    def ollama_embed_dimension(self, model: str) -> int | None:
        import httpx

        try:
            response = httpx.post(
                f"{self._settings.ollama_base_url.rstrip('/')}/api/embed",
                json={"model": model, "input": PROBE_TEXT},
                timeout=self._settings.ollama_health_timeout_seconds,
            )
            if not response.is_success:
                return None
            embeddings = response.json().get("embeddings")
        except Exception:
            return None
        if not isinstance(embeddings, list) or not embeddings or not isinstance(embeddings[0], list):
            return None
        return len(embeddings[0])

    def _qdrant(self) -> Any:
        if self._qdrant_client is None:
            from qdrant_client import QdrantClient

            self._qdrant_client = QdrantClient(url=self._settings.qdrant_url, timeout=int(self._settings.qdrant_timeout_seconds))
        return self._qdrant_client

    def qdrant_dimension(self, collection: str) -> int | None | QdrantUnreachable:
        try:
            client = self._qdrant()
            if not client.collection_exists(collection):
                return None
            vectors = client.get_collection(collection).config.params.vectors
        except Exception:
            return QDRANT_UNREACHABLE
        size = getattr(vectors, "size", None)
        if size is None and isinstance(vectors, Mapping) and len(vectors) == 1:
            size = getattr(next(iter(vectors.values())), "size", None)
        return int(size) if size is not None else QDRANT_UNREACHABLE

    def qdrant_point_count(self, collection: str) -> int | QdrantUnreachable:
        try:
            client = self._qdrant()
            if not client.collection_exists(collection):
                return 0
            return int(client.count(collection_name=collection, exact=True).count)
        except Exception:
            return QDRANT_UNREACHABLE

    def postgres_counts(self) -> PostgresCounts | None:
        try:
            from sqlalchemy import func, select

            from app.postgres.database import create_postgres_engine
            from app.postgres.models import Document, DocumentChunk, DocumentVersion, Memory

            engine = create_postgres_engine(str(self._settings.database_url), connect_timeout_seconds=5)
            try:
                with engine.connect() as connection:
                    # Same predicate as OperationalService.metrics()["active_chunks"]: the
                    # chunks a complete collection must hold one point for.
                    active_chunks = connection.scalar(
                        select(func.count())
                        .select_from(DocumentChunk)
                        .join(Document, Document.id == DocumentChunk.document_id)
                        .join(DocumentVersion, DocumentVersion.id == Document.active_version_id)
                        .where(DocumentChunk.version_id == DocumentVersion.id, Document.status == "indexed", DocumentVersion.status == "active")
                    ) or 0
                    memories = connection.scalar(select(func.count()).select_from(Memory)) or 0
            finally:
                engine.dispose()
        except Exception:
            return None
        self.last_counts = PostgresCounts(active_chunks=int(active_chunks), memories=int(memories))
        return self.last_counts


# ── resolution ──────────────────────────────────────────────────────────────────

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
        return self.status in DEVIATING

    @property
    def serving(self) -> bool:
        """status in {active, fallback, unverified, incomplete} — the role may be called."""
        return self.status in SERVING

    @property
    def flat_config(self) -> dict[str, Any] | None:
        """Deep copy of record.config for MODEL_ROLES; None for reranker and unconfigured roles.
        The ONLY edit ever applied: ocr with status `disabled` gets enabled: False."""
        if self.record is None or self.role not in MODEL_ROLES:
            return None
        config = copy.deepcopy(dict(self.record.config))
        if self.role == "ocr" and self.status == "disabled":
            config["enabled"] = False
        return config


@dataclass
class Resolved:
    registry: Registry
    roles: dict[str, RoleResolution]
    collections: QdrantCollections
    probed: bool
    _flat: dict[str, dict[str, Any]] | None = field(default=None, init=False, repr=False, compare=False)
    _reranker_recorded: tuple[Any, ...] | None = field(default=None, init=False, repr=False, compare=False)

    def flat_models(self) -> dict[str, dict[str, Any]]:
        """{role: flat_config} for every MODEL_ROLES role whose flat_config is not None
        (vision absent). Built once; the SAME object on every call."""
        if self._flat is None:
            flat: dict[str, dict[str, Any]] = {}
            for role in MODEL_ROLES:
                config = self.roles[role].flat_config
                if config is not None:
                    flat[role] = config
            self._flat = flat
        return self._flat

    def reranker_chain(self) -> tuple[VersionRecord, ...]:
        return self.roles["reranker"].chain

    def embedding_refusal(self) -> str | None:
        embedding = self.roles["embedding"]
        return embedding.reason if embedding.status == "degraded" else None

    def embedding_version_id(self) -> str | None:
        record = self.roles["embedding"].record
        return record.id if record is not None else None

    def model_name(self, role: str) -> str | None:
        record = self.roles[role].record
        if record is None:
            return None
        name = record.config.get("name")
        return str(name) if name is not None else None

    def record_reranker(self, *, loaded_id: str | None, status: Status, reason: str | None,
                        latency_ms: int | None = None) -> None:
        """Reranker only: the torch model cannot be loaded in every process, so RerankerService.warmup()
        reports back (status is `pending` until then). Emits model_version_fallback when it deviates. Idempotent."""
        key = (loaded_id, status, reason, latency_ms)
        if self._reranker_recorded == key:
            return
        self._reranker_recorded = key
        resolution = self.roles["reranker"]
        record = resolution.record
        if loaded_id is not None:
            try:
                record = self.registry.get("reranker", loaded_id)
            except ModelRegistryError:
                record = resolution.record      # a legacy single-name load: keep the pointer's record
        resolution.loaded_id = loaded_id
        resolution.status = status
        resolution.reason = reason
        resolution.record = record
        resolution.latency_ms = latency_ms
        resolution.verified = status not in ("off", "unconfigured", "pending")
        resolution.probe = ProbeOutcome(kind="reranker_load", ok=loaded_id is not None, detail=reason, ms=latency_ms)
        _log("info", "model_version_resolved", f"reranker resolved: {status}", role="reranker", loaded=loaded_id,
             status=status, verified=resolution.verified)
        if resolution.deviates:
            _log("warning", "model_version_fallback", f"reranker deviates from its pointer: {reason}", role="reranker",
                 requested=resolution.requested_id, loaded=loaded_id, status=status, reason=reason)

    def registry_view(self) -> dict[str, dict[str, Any]]:
        """/models.registry: {role: {active, requested, loaded, source, status, reason, verified, name,
        digest, collections: {documents, memories} (embedding only), latency_ms (reranker only), fallback: bool}}
        where fallback == deviates."""
        view: dict[str, dict[str, Any]] = {}
        for role, resolution in self.roles.items():
            record = resolution.record
            row: dict[str, Any] = {
                "active": self.registry.roles[role].active,
                "requested": resolution.requested_id,
                "loaded": resolution.loaded_id,
                "source": resolution.source,
                "status": resolution.status,
                "reason": resolution.reason,
                "verified": resolution.verified,
                "name": record.name if record is not None else None,
                "digest": record.digest if record is not None else None,
                "fallback": resolution.deviates,
            }
            if role == "embedding":
                row["collections"] = {"documents": self.collections.documents, "memories": self.collections.memories}
            if role == "reranker":
                row["latency_ms"] = resolution.latency_ms
            view[role] = row
        return view

    def fallback_flag(self) -> Literal["ok", "fallback"]:
        return "fallback" if any(resolution.deviates for resolution in self.roles.values()) else "ok"

    def attention_text(self) -> str | None:
        deviating = [resolution for resolution in self.roles.values() if resolution.deviates]
        if not deviating:
            return None
        lines = ["ATTENTION: a model role is not serving what its registry pointer names.", ""]
        for resolution in deviating:
            lines.append(f"{resolution.role}: requested={resolution.requested_id} loaded={resolution.loaded_id} "
                         f"status={resolution.status} reason={resolution.reason}")
            lines.extend(f"  {line}" for line in self._revert_lines(resolution))
        lines.append("")
        lines.append("The nightly eval refuses to grade this state; /models.registry carries the same rows.")
        return "\n".join(lines) + "\n"

    def _previous_id(self, resolution: RoleResolution) -> str | None:
        """The id a one-step revert names: what serves now after a fallback, else the nearest
        version listed BEFORE the requested one that may be chosen automatically (file order,
        `fallback: false` skipped — the walk chain() does). Read from the file, not from
        `resolution.chain`: that tuple is one entry long for embedding (NO_FALLBACK_ROLES) and
        for an ad-hoc tag pin, so it named a placeholder for four of the five deviating
        statuses. None when nothing earlier is registered (a single-version role, or a tag pin
        whose synthetic id is not in the file)."""
        if resolution.status == "fallback" and resolution.loaded_id:
            return resolution.loaded_id
        versions = self.registry.roles[resolution.role].versions
        ids = [record.id for record in versions]
        if resolution.requested_id not in ids:
            return None
        earlier = [record for record in versions[: ids.index(resolution.requested_id)] if record.fallback]
        return earlier[-1].id if earlier else None

    def _revert_lines(self, resolution: RoleResolution) -> list[str]:
        """The operator's next move, chosen by WHERE the pointer came from — an env pin is
        undone in the shell (editing `active` would not touch it; the pin re-triggers the
        fallback on every restart), an ad-hoc tag pin in `.env` or the shell (setting
        MODEL_VERSION_<ROLE> beside it refuses boot: "set one, not both"), a registry pointer
        in the file. An embedding contradiction also gets the rebuild command its reason
        names, pinned to the requested id: moving the pointer is not its remedy."""
        role, env = resolution.role, _env_name(resolution.role)
        active = self.registry.roles[role].active
        previous = self._previous_id(resolution)
        remedy = _remedy_command(resolution.reason)
        restart = "then restart run-local-ai-core.bat"
        lines: list[str] = []
        if resolution.source == "env_tag":
            lines.append(f"revert: unset DISCORD_MEMORY_{role.upper()}_MODEL (the ad-hoc tag pin, in .env or this shell), "
                         f"{restart}; the role then follows roles.{role}.active={active}")
        elif resolution.source == "env" and resolution.requested_id != active:
            alternative = f" (or set it to {previous})" if previous is not None else ""
            lines.append(f"revert: unset {env} in this shell{alternative}, {restart}")
        elif previous is not None:
            lines.append(f"revert: edit roles.{role}.active in backend/app/config/model_versions.yaml to {previous} "
                         f"or set {env}={previous} in the shell, {restart}")
        elif remedy is None:
            lines.append(f"revert: no earlier version of roles.{role} is registered — remedy: {resolution.reason}")
        if remedy is not None:
            lines.append(f"remedy: {remedy} in the shell, {restart}")
        return lines


class _Walker:
    """One resolve() call: caches the /api/tags answer and the Postgres counts so each
    is fetched at most once, whatever the number of roles that need them."""

    _UNSET = object()

    def __init__(self, registry: Registry, overrides: Overrides, probes: Probes | None) -> None:
        self.registry = registry
        self.overrides = overrides
        self.probes = probes
        self.collections = derive_collections(registry, overrides)
        self._tags: Any = self._UNSET
        self._counts: Any = self._UNSET

    def tags(self) -> Mapping[str, str] | None:
        if self._tags is self._UNSET:
            assert self.probes is not None
            self._tags = self.probes.ollama_tags()
        return self._tags

    def counts(self) -> PostgresCounts | None:
        if self._counts is self._UNSET:
            assert self.probes is not None
            self._counts = self.probes.postgres_counts()
        return self._counts

    def pointer(self, role: str) -> tuple[VersionRecord | None, Source, tuple[VersionRecord, ...]]:
        pinned = _pinned(self.registry, self.overrides, role)
        if pinned is not None:
            return pinned, "env", self.registry.chain(role, pinned.id)
        raw_tag = self.overrides.raw_tags.get(role)
        if raw_tag is not None:
            synthetic = VersionRecord(role=role, id=f"env:{raw_tag}", provider="ollama", config={"provider": "ollama", "name": raw_tag})
            return synthetic, "env_tag", (synthetic,)
        active = self.registry.roles[role].active
        if active is None:
            return None, "registry", ()
        return self.registry.get(role, active), "registry", self.registry.chain(role)

    def resolve_role(self, role: str) -> RoleResolution:
        requested, source, chain = self.pointer(role)
        if requested is None:
            _log("info", "model_version_config", f"{role}: active is null (not served)", role=role, requested=None, source=source)
            return RoleResolution(role, None, source, None, "unconfigured", None, None, (), None, False)
        _log("info", "model_version_config", f"{role}: {requested.id} ({source})", role=role, requested=requested.id, source=source)
        if role in self.overrides.disabled_roles:
            return RoleResolution(role, requested.id, source, None, "off", _FLAG_REASON.get(role, "feature flag off"), requested, chain, None, False)
        if role == "ocr" and not requested.config.get("enabled", False):
            return RoleResolution(role, requested.id, source, None, "off", "config.enabled=false", requested, chain, None, False)
        if self.probes is None:
            return RoleResolution(role, requested.id, source, requested.id, "active", None, requested, chain,
                                  ProbeOutcome(kind="skipped", ok=None, detail="MODEL_STARTUP_PROBES=false"), False)
        if requested.provider == "sentence-transformers":
            # The torch load happens in RerankerService.warmup(); resolve() only hands the chain over.
            return RoleResolution(role, requested.id, source, None, "pending", None, requested, chain, None, False)

        first_failure: str | None = None
        tried: list[str] = []
        for candidate in chain:
            verdict, outcome, reason = self._probe(role, candidate)
            _log("info", "model_version_probe", f"{role} {candidate.id}: {outcome.kind} ok={outcome.ok} {outcome.detail or ''}".rstrip(),
                 role=role, version_id=candidate.id, kind=outcome.kind, ok=outcome.ok, detail=outcome.detail, ms=outcome.ms)
            if verdict == "next":
                tried.append(candidate.id)
                if first_failure is None:
                    first_failure = f"{candidate.id} {outcome.detail}"
                continue
            if verdict == "unverified":
                # Ollama/Qdrant/Postgres not answering is not a reason to switch models: keep the pointer.
                return RoleResolution(role, requested.id, source, requested.id, "unverified", reason, requested, chain, outcome, False)
            if verdict == "degraded":
                return RoleResolution(role, requested.id, source, None, "degraded", reason, requested, chain, outcome, True)
            if verdict == "incomplete":
                return RoleResolution(role, requested.id, source, candidate.id, "incomplete", reason, requested, chain, outcome, True)
            status: Status = "active" if candidate.id == requested.id else "fallback"
            fallback_reason = None if status == "active" else f"{first_failure}; serving {candidate.id}"
            return RoleResolution(role, requested.id, source, candidate.id, status, fallback_reason, candidate, chain, outcome, True)

        exhausted: Status = "disabled" if role in DISABLE_ON_MISS_ROLES else "missing"
        reason = f"{first_failure or requested.id + ' no candidate'}; chain exhausted ({', '.join(tried) or requested.id})"
        return RoleResolution(role, requested.id, source, None, exhausted, reason, requested, chain,
                              ProbeOutcome(kind="tags" if requested.provider == "ollama" else "provider", ok=False, detail=reason), True)

    def _probe(self, role: str, candidate: VersionRecord) -> tuple[str, ProbeOutcome, str | None]:
        """One candidate. Verdict: pass | next | unverified | degraded | incomplete."""
        assert self.probes is not None
        started = perf_counter()
        elapsed = lambda: int((perf_counter() - started) * 1000)  # noqa: E731
        if candidate.provider in ("gemini", "deepseek"):
            if candidate.provider in self.overrides.registered_providers:
                return "pass", ProbeOutcome("provider", True, f"{candidate.provider} registered", elapsed()), None
            return "next", ProbeOutcome("provider", False, f"provider {candidate.provider} not registered (no API key)", elapsed()), None

        tags = self.tags()
        if tags is None:
            return "unverified", ProbeOutcome("tags", None, "Ollama /api/tags did not answer", elapsed()), f"{candidate.id}: Ollama /api/tags did not answer; pointer kept"
        tag = candidate.ollama_tag
        if tag not in tags:
            return "next", ProbeOutcome("tags", False, f"tag {tag} absent from /api/tags", elapsed()), None
        if candidate.digest and tags[tag] != candidate.digest:
            return "next", ProbeOutcome("tags+digest", False, f"digest_mismatch for {tag} (registry {candidate.digest[:19]}…, server {tags[tag][:19]}…)", elapsed()), None
        kind = "tags+digest" if candidate.digest else "tags"
        if role != "embedding":
            return "pass", ProbeOutcome(kind, True, f"tag {tag} present", elapsed()), None
        return self._probe_embedding(candidate, started)

    def _probe_embedding(self, candidate: VersionRecord, started: float) -> tuple[str, ProbeOutcome, str | None]:
        elapsed = lambda: int((perf_counter() - started) * 1000)  # noqa: E731
        assert self.probes is not None
        expected = int(candidate.config.get("dimensions") or 0)
        width = self.probes.ollama_embed_dimension(str(candidate.config["name"]))
        if width is None:
            return "unverified", ProbeOutcome("embed_dimension", None, "probe embed did not answer", elapsed()), f"{candidate.id}: probe embed did not answer; pointer kept"
        if width != expected:
            reason = f"{candidate.id}: probe embed returned width {width}, config.dimensions is {expected}"
            return "degraded", ProbeOutcome("embed_dimension", False, reason, elapsed()), reason

        incomplete: tuple[ProbeOutcome, str] | None = None
        unverified: tuple[ProbeOutcome, str] | None = None
        checks = (
            (self.collections.documents, "active_chunks", "active chunks", "rebuild_qdrant --missing-only"),
            (self.collections.memories, "memories", "memories rows", "rebuild_memories --missing-only"),
        )
        for collection, attribute, label, remedy in checks:
            size = self.probes.qdrant_dimension(collection)
            if isinstance(size, QdrantUnreachable):
                unverified = unverified or (ProbeOutcome("collection_dimension", None, f"Qdrant did not answer for {collection}", elapsed()),
                                            f"{candidate.id}: Qdrant did not answer for {collection}; pointer kept")
                continue
            if size is None:
                if self.overrides.allow_missing_collections:
                    continue
                counts = self.counts()
                if counts is None:
                    unverified = unverified or (ProbeOutcome("collection_dimension", None, f"{collection} absent and Postgres did not answer", elapsed()),
                                                f"{candidate.id}: {collection} absent and Postgres did not answer; pointer kept")
                    continue
                corpus = getattr(counts, attribute)
                if corpus > 0:
                    reason = (f"{candidate.id}: collection {collection} does not exist while {label} = {corpus}; "
                              f"run python -m scripts.{remedy} with MODEL_VERSION_EMBEDDING={candidate.id}")
                    return "degraded", ProbeOutcome("collection_dimension", False, reason, elapsed()), reason
                continue            # fresh install: nothing to hold yet
            if size != expected:
                reason = f"{candidate.id}: collection {collection} has width {size}, config.dimensions is {expected}"
                return "degraded", ProbeOutcome("collection_dimension", False, reason, elapsed()), reason
            if self.overrides.allow_missing_collections:
                continue
            points = self.probes.qdrant_point_count(collection)
            if isinstance(points, QdrantUnreachable):
                unverified = unverified or (ProbeOutcome("collection_count", None, f"Qdrant count did not answer for {collection}", elapsed()),
                                            f"{candidate.id}: Qdrant count did not answer for {collection}; pointer kept")
                continue
            counts = self.counts()
            if counts is None:
                unverified = unverified or (ProbeOutcome("collection_count", None, "Postgres did not answer", elapsed()),
                                            f"{candidate.id}: Postgres did not answer; pointer kept")
                continue
            corpus = getattr(counts, attribute)
            if points < corpus and incomplete is None:
                reason = (f"{candidate.id}: collection {collection} holds {points} points for {corpus} {label}; "
                          f"run python -m scripts.{remedy} with MODEL_VERSION_EMBEDDING={candidate.id}")
                incomplete = (ProbeOutcome("collection_count", False, reason, elapsed()), reason)
        if incomplete is not None:     # a verified shortfall outranks "could not decide"
            return "incomplete", incomplete[0], incomplete[1]
        if unverified is not None:
            return "unverified", unverified[0], unverified[1]
        return "pass", ProbeOutcome("collection_count", True, "width and counts agree", elapsed()), None


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
    walker = _Walker(registry, overrides, probes)
    roles: dict[str, RoleResolution] = {}
    for role in ROLES:
        resolution = walker.resolve_role(role)
        roles[role] = resolution
        fields: dict[str, Any] = {"role": role, "loaded": resolution.loaded_id, "status": resolution.status, "verified": resolution.verified}
        if role == "embedding":
            fields["collections"] = {"documents": walker.collections.documents, "memories": walker.collections.memories}
        _log("info", "model_version_resolved", f"{role}: {resolution.status} (loaded {resolution.loaded_id})", **fields)
        if resolution.deviates:
            _log("warning", "model_version_fallback", f"{role} deviates from its pointer: {resolution.reason}", role=role,
                 requested=resolution.requested_id, loaded=resolution.loaded_id, status=resolution.status, reason=resolution.reason)
    embedding_record = roles["embedding"].record
    assert embedding_record is not None
    expected = _collection_name(overrides.documents_collection, embedding_record.collection_suffix)
    if walker.collections.documents != expected:  # pragma: no cover - both derive from the same pointer
        raise ModelRegistryError(f"collection derivation disagrees with the embedding pointer: {walker.collections.documents} != {expected}")
    _log("info", "qdrant_collections", f"Qdrant collections {walker.collections.documents} / {walker.collections.memories}",
         documents=walker.collections.documents, memories=walker.collections.memories,
         suffix=embedding_record.collection_suffix, base=overrides.documents_collection)
    return Resolved(registry=registry, roles=roles, collections=walker.collections, probed=probes is not None)


def write_attention_marker(resolved: Resolved, logs_path: Path) -> Path | None:
    """API process only, after record_reranker(). Writes <logs_path>/ATTENTION_model_fallback.txt when
    any role deviates — one line per deviating role (requested, loaded, status, reason) plus the
    one-step revert, worded for the pointer's source (Resolved._revert_lines: the file's
    `active` / the MODEL_VERSION_<ROLE> pin / the DISCORD_MEMORY_<ROLE>_MODEL tag pin, and the
    rebuild command for an embedding contradiction); deletes it otherwise. Workers only log.
    logs_path is Settings.logs_path (LOG_DIR): the lab launchers (nightly_eval, eval_stack) hand
    their API a directory of its own, so a lab boot never erases or forges production's marker."""
    marker = Path(logs_path) / ATTENTION_FILENAME
    text = resolved.attention_text()
    if text is None:
        if marker.exists():
            marker.unlink()
        return None
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(text, encoding="utf-8")
    return marker


def overrides_from_settings(settings: "Settings") -> Overrides:
    """pins from model_version_<role>; raw_tags from discord_memory_extractor_model / _verifier_model;
    disabled_roles: condenser unless discord_condensation_enabled, extractor unless
    discord_memory_extractor_enabled, verifier unless both verifier and extractor flags;
    registered_providers from gemini_api_key / deepseek_api_key; collections from
    qdrant_documents_collection / qdrant_memories_collection."""
    pins = {role: pin for role in PINNABLE_ROLES if (pin := getattr(settings, f"model_version_{role}", None))}
    raw_tags: dict[str, str] = {}
    if settings.discord_memory_extractor_model:
        raw_tags["extractor"] = settings.discord_memory_extractor_model
    if settings.discord_memory_verifier_model:
        raw_tags["verifier"] = settings.discord_memory_verifier_model
    disabled: set[str] = set()
    if not settings.discord_condensation_enabled:
        disabled.add("condenser")
    if not settings.discord_memory_extractor_enabled:
        disabled.add("extractor")
    if not (settings.discord_memory_verifier_enabled and settings.discord_memory_extractor_enabled):
        disabled.add("verifier")
    providers = {"ollama"}
    if settings.gemini_api_key:
        providers.add("gemini")
    if settings.deepseek_api_key:
        providers.add("deepseek")
    return Overrides(
        pins=pins, raw_tags=raw_tags, disabled_roles=frozenset(disabled), registered_providers=frozenset(providers),
        documents_collection=settings.qdrant_documents_collection, memories_collection=settings.qdrant_memories_collection,
    )


# ── launcher lists ──────────────────────────────────────────────────────────────

def _launcher_chains(registry: Registry, overrides: Overrides) -> list[tuple[VersionRecord, ...]]:
    """The chains the launcher must make loadable: every role that is neither off nor
    unconfigured, requested first. Honours pins and raw tags. No probes."""
    walker = _Walker(registry, overrides, None)
    chains: list[tuple[VersionRecord, ...]] = []
    for role in ROLES:
        if role in overrides.disabled_roles:
            continue
        requested, _source, chain = walker.pointer(role)
        if requested is None:
            continue
        if role == "ocr" and not requested.config.get("enabled", False):
            continue
        chains.append(chain)
    return chains


def ollama_pull_list(registry: Registry, overrides: Overrides) -> list[str]:
    """Hub-sourced tags the launcher must pull: for every ollama role not off/unconfigured, the requested
    tag plus every tag in its chain, de-duplicated, file order. Honours pins. No probes."""
    tags: list[str] = []
    for chain in _launcher_chains(registry, overrides):
        for record in chain:
            if record.provider != "ollama" or record.ollama.source != "hub":
                continue
            tag = str(record.config["name"])
            if tag not in tags:
                tags.append(tag)
    return tags


def ollama_create_list(registry: Registry, overrides: Overrides) -> list[tuple[str, Path]]:
    """(tag, modelfile) for every modelfile-sourced tag in the same set."""
    entries: list[tuple[str, Path]] = []
    for chain in _launcher_chains(registry, overrides):
        for record in chain:
            if record.provider != "ollama" or record.ollama.source != "modelfile" or record.ollama.modelfile is None:
                continue
            entry = (str(record.config["name"]), record.ollama.modelfile)
            if entry not in entries:
                entries.append(entry)
    return entries


# ── --check ─────────────────────────────────────────────────────────────────────

def _ollama_cache_key(workflow: Path) -> str | None:
    """The `key:` of the actions/cache step that caches ~/.ollama, or None when absent."""
    document = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
    for job in (document.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            if not isinstance(step, Mapping) or not str(step.get("uses", "")).startswith("actions/cache"):
                continue
            with_block = step.get("with") or {}
            if str(with_block.get("path", "")).strip() == "~/.ollama":
                return str(with_block.get("key", ""))
    return None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check_registry(path: Path = DEFAULT_REGISTRY_PATH, *, ci_workflow: Path = CI_WORKFLOW_PATH) -> tuple[list[str], list[str]]:
    """The static rules behind `--check` (stdlib + yaml only, no network). Returns
    (errors, warnings); the CLI exits 1 when errors is non-empty."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        registry = load_registry(path)
    except ModelRegistryError as error:
        return [str(error)], []

    # Invariant #4: a served RAG-quality version must be able to point at the report that earned it.
    for role in ROLES:
        entry = registry.roles[role]
        for record in entry.versions:
            where = f"roles.{role} id={record.id}"
            existing = 0
            for gate, report in record.eval_reports.items():
                if report is None:
                    continue
                if not report.is_file():
                    errors.append(f"{where}: eval.reports.{gate} {report} does not exist")
                    continue
                existing += 1
                try:
                    data = _read_json(report)
                except (OSError, ValueError) as error:
                    errors.append(f"{where}: eval.reports.{gate} {report} is not readable JSON ({error})")
                    continue
                if not isinstance(data, Mapping):
                    errors.append(f"{where}: eval.reports.{gate} {report} is not a JSON object")
                    continue
                stamped = (data.get("versions") or {}).get(role) if isinstance(data.get("versions"), Mapping) else None
                if stamped is None:
                    message = f"{where}: eval.reports.{gate} {report} carries no versions.{role} stamp"
                    (warnings if record.id in GRANDFATHERED_UNSTAMPED else errors).append(message)
                elif stamped != record.id:
                    errors.append(f"{where}: eval.reports.{gate} {report} was produced by versions.{role}={stamped!r}")
                if gate in ("extractor_benchmark", "mteb"):
                    expected_name = record.config.get("name")
                    if data.get("model") != expected_name:
                        errors.append(f"{where}: eval.reports.{gate} {report} names model {data.get('model')!r}, config.name is {expected_name!r}")
            if record.id == entry.active and role in GATED_ROLES and existing == 0:
                errors.append(f"{where} (ACTIVE): needs at least one existing eval.reports path — promotion without a gate (invariant #4)")

    # Invariant #7: the resident set must fit the measured budget.
    total = 0
    general = registry.get("general", registry.roles["general"].active)
    for role in GATED_ROLES:
        active = registry.roles[role].active
        if active is None:
            continue
        record = registry.get(role, active)
        if record.vram_mib is None:
            errors.append(f"roles.{role} id={record.id} (ACTIVE): vram_mib is null — measure before promotion (data/vram_budget.md)")
            continue
        if role == "extractor" and record.config.get("name") == general.config.get("name"):
            continue                     # same resident tag as general: no extra residency
        total += record.vram_mib
    if total > registry.vram_budget_mib:
        errors.append(f"active general+embedding+reranker(+extractor) need {total} MiB, budget.vram_mib is {registry.vram_budget_mib}")

    # Reranker: a checkpoint is served only with its export contract; a hub pointer without parity scores is a warning.
    reranker_active = registry.roles["reranker"].active
    if reranker_active is not None:
        record = registry.get("reranker", reranker_active)
        where = f"roles.reranker id={record.id} (ACTIVE)"
        if record.path is not None:
            if record.digest is None:
                errors.append(f"{where}: digest.sha256 must be non-null for a path version")
            if record.probe is None or record.probe.scores is None:
                errors.append(f"{where}: probe.scores must be non-null for a path version (copied from export.json)")
            export = record.path / "export.json"
            if not export.is_file():
                errors.append(f"{where}: {export} does not exist")
            else:
                try:
                    data = _read_json(export)
                except (OSError, ValueError) as error:
                    errors.append(f"{where}: {export} is not readable JSON ({error})")
                    data = {}
                if data.get("activation_fn") != record.activation:
                    errors.append(f"{where}: export.json activation_fn {data.get('activation_fn')!r} != activation {record.activation!r}")
                exported_scores = data.get("scores")
                record_scores = list(record.probe.scores) if record.probe is not None and record.probe.scores is not None else None
                if not isinstance(exported_scores, list) or record_scores is None or len(exported_scores) != len(record_scores) \
                        or any(abs(float(a) - float(b)) > 1e-6 for a, b in zip(exported_scores, record_scores, strict=True)):
                    errors.append(f"{where}: export.json scores {exported_scores!r} != probe.scores {record_scores!r}")
                if data.get("model_safetensors_sha256") != record.digest:
                    errors.append(f"{where}: export.json model_safetensors_sha256 != digest.sha256")
        elif record.probe is None or record.probe.scores is None:
            warnings.append(f"{where}: probe.scores is null — parity is disarmed; run --record-probe {record.id}")

    # A create-built tag the launcher will be asked for must have its recipe and its pinned bytes.
    for role in ROLES:
        for record in registry.chain(role):
            if record.provider != "ollama" or record.ollama.source != "modelfile":
                continue
            where = f"roles.{role} id={record.id}"
            if record.ollama.modelfile is None or not record.ollama.modelfile.is_file():
                errors.append(f"{where}: ollama.modelfile {record.ollama.modelfile} does not exist")
            if record.ollama.gguf_sha256 is None:
                errors.append(f"{where}: ollama.gguf_sha256 is null (required once the version is active or in a chain)")

    # CI caches the embedding blobs by revision: a stale key would serve old weights under a new revision.
    if ci_workflow.is_file():
        embedding = registry.get("embedding", registry.roles["embedding"].active)
        expected_key = "ollama-" + str(embedding.config.get("revision"))
        try:
            key = _ollama_cache_key(ci_workflow)
        except yaml.YAMLError as error:
            key = None
            errors.append(f"{ci_workflow}: not valid YAML ({error})")
        else:
            if key is None:
                warnings.append(f"{ci_workflow}: no actions/cache step with path ~/.ollama; cache-key rule skipped")
            elif key != expected_key:
                errors.append(f"{ci_workflow}: Ollama cache key {key!r} != {expected_key!r} (active embedding config.revision)")
    else:
        warnings.append(f"{ci_workflow} not found; cache-key rule skipped")
    return errors, warnings


# ── --record-probe ──────────────────────────────────────────────────────────────

def record_probe(registry: Registry, version_id: str) -> list[float]:
    """HUB versions only (a `path` version's scores come from export.json): load on THIS runtime,
    score probe.pairs, return the scores rounded to 4 decimals. Needs the [rerank] extra."""
    record = registry.get("reranker", version_id)
    if record.path is not None:
        raise ModelRegistryError(f"{version_id} is a path version: its scores come from export.json, not from --record-probe")
    if record.probe is None or not record.probe.pairs:
        raise ModelRegistryError(f"{version_id} has no probe.pairs to score")
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as error:
        raise ModelRegistryError("--record-probe needs the optional extra: pip install -e .[rerank]") from error
    kwargs: dict[str, Any] = {"revision": record.revision}
    if record.activation is not None:
        import torch

        kwargs["default_activation_function"] = {"identity": torch.nn.Identity(), "sigmoid": torch.nn.Sigmoid()}[record.activation]
    if record.max_length is not None:
        kwargs["max_length"] = record.max_length
    model = CrossEncoder(record.hub, **kwargs)
    scores = model.predict([list(pair) for pair in record.probe.pairs])
    return [round(float(score), 4) for score in scores]


# ── CLI ─────────────────────────────────────────────────────────────────────────
#   cd backend && python -m app.config.model_registry <mode> [--registry PATH]
#   --check              load_registry + static rules (stdlib+yaml only; exit 1 with every violation listed)
#   --show [--no-probe]  resolve as this machine would; print registry_view() JSON (+ counts)
#   --ollama-pull-list   one tag per line            (launcher `for /f`)
#   --ollama-create-list "tag<TAB>modelfile" per line (launcher `for /f`)
#   --record-probe <id>  HUB versions only: load on THIS runtime, score probe.pairs, print the `scores:` block

def _settings_for_cli() -> "Settings":
    """This machine's Settings (.env + shell): the pins, flags, keys and collection bases
    the launcher and --show must honour. --registry only swaps the file, so it is read
    directly by load_registry() and never goes through Settings."""
    from app.config.settings import get_settings

    return get_settings()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.config.model_registry", description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate the registry against the static rules (CI)")
    mode.add_argument("--show", action="store_true", help="resolve as this machine would and print /models.registry")
    mode.add_argument("--ollama-pull-list", action="store_true", help="hub tags the launcher must pull, one per line")
    mode.add_argument("--ollama-create-list", action="store_true", help="tag<TAB>modelfile per create-built tag")
    mode.add_argument("--record-probe", metavar="ID", help="score probe.pairs of a hub reranker version on this runtime")
    parser.add_argument("--registry", type=Path, default=None, help="registry file (default: the shipped model_versions.yaml)")
    parser.add_argument("--no-probe", action="store_true", help="--show without probes (pointer only)")
    args = parser.parse_args(argv)
    registry_path = args.registry if args.registry is not None else DEFAULT_REGISTRY_PATH

    try:
        if args.check:
            errors, warnings = check_registry(registry_path)
            for message in warnings:
                print(f"WARNING: {message}")
            for message in errors:
                print(f"ERROR: {message}")
            print(f"{registry_path}: {len(errors)} error(s), {len(warnings)} warning(s)")
            return 1 if errors else 0

        if args.record_probe:
            registry = load_registry(registry_path)
            scores = record_probe(registry, args.record_probe)
            import platform

            import sentence_transformers

            print(f"# {args.record_probe} scored on sentence-transformers {sentence_transformers.__version__}, "
                  f"python {platform.python_version()}; paste under probe:")
            print(f"          scores: [{', '.join(f'{score:.4f}' for score in scores)}]")
            return 0

        settings = _settings_for_cli()
        registry = load_registry(registry_path)
        overrides = overrides_from_settings(settings)
        if args.ollama_pull_list:
            for tag in ollama_pull_list(registry, overrides):
                print(tag)
            return 0
        if args.ollama_create_list:
            for tag, modelfile in ollama_create_list(registry, overrides):
                print(f"{tag}\t{modelfile}")
            return 0

        probes = None if args.no_probe or not settings.model_startup_probes else ProductionProbes(settings)
        resolved = resolve(registry, overrides, probes)
        payload: dict[str, Any] = {"probed": resolved.probed, "model_fallback": resolved.fallback_flag(), "registry": resolved.registry_view()}
        if isinstance(probes, ProductionProbes) and probes.last_counts is not None:
            payload["counts"] = {"active_chunks": probes.last_counts.active_chunks, "memories": probes.last_counts.memories}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except ModelRegistryError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
