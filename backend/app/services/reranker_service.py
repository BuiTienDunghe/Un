"""Cross-encoder reranking (P4-3): reorder retrieval candidates at QUERY time.

Unlike P4-2's contextual retrieval, this cost lands on every question, not on
indexing — so the thing to watch is latency, not model-call count. The
inference-budget invariant (plan §1) is about *generation* calls: a
cross-encoder is a small scoring model, so the number of generation calls per
question is unchanged. That is not a licence to ignore the cost; the added
milliseconds are measured and gated in docs/p4_progress.md.

Model registry: ``warmup()`` walks a chain of version records (active first,
then the earlier versions the registry allows as fallbacks) and NEVER raises.
A version is rejected when it cannot be imported, is not cached (fallbacks may
not download), fails to load, or loads but is not the checkpoint the record
describes — digest, activation, head size, input window, or probe-pair parity.
"Loadable" alone was never enough: a ST 5.x export whose config lacks the
activation name loads fine under 3.4.1 and then scores through Sigmoid, and a
random classification head passes the constructor (docs/p4_progress.md). The
chain ends in ``disabled`` rather than a refused boot (invariant #5); the
resolver upstream reports that as a deviation.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

if TYPE_CHECKING:
    from app.config.model_registry import VersionRecord

# The hub model every version chain used to be: kept only for the legacy
# (versions=None) read of rag.reranker.model, which left models.yaml with the registry.
HUB_DEFAULT_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
# Timed predict at warmup: the probe pairs cycled to this many, so latency_ms is
# measured on a batch the size of a real question (candidate_limit is 15).
TIMING_PAIRS = 15
# Fragments of the errors transformers / huggingface_hub raise for a snapshot that is
# not in the disk cache while local_files_only is set (measured: OSError "couldn't find
# them in the cached files" wrapping LocalEntryNotFoundError "disk cache ... outgoing
# traffic has been disabled").
_NOT_CACHED_MARKERS = (
    "couldn't find them in the cached files",
    "disk cache",
    "outgoing traffic has been disabled",
    "local_files_only",
)
# Same sentinel guard as _input_limit: HuggingFace reports "no limit" as an
# astronomically large integer (VERY_LARGE_INTEGER, 1e30), which must fall back to
# 512 while a genuine long context (Qwen3-Reranker 131072) must not.
_LIMIT_SENTINEL = 10_000_000


class RerankerUnavailableError(Exception):
    pass


class _VersionRejected(Exception):
    """One chain entry failed a warmup check. ``code`` is the design's reason vocabulary:
    import | not_cached | load | digest | activation | num_labels | max_length | parity."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class WarmupOutcome:
    """What warmup() decided; main.py maps ``status`` onto the registry's reranker
    status (loaded -> active|fallback, rejected_all -> disabled, flag_off -> off,
    no_versions -> unconfigured)."""

    status: Literal["loaded", "rejected_all", "flag_off", "no_versions"]
    loaded_id: str | None
    source: Literal["active", "fallback", "legacy"] | None
    reason: str | None
    latency_ms: int | None
    digest_ok: bool | None
    parity_ok: bool | None


class RerankerService:
    def __init__(
        self, enabled: bool, model_name: str, candidate_limit: int, model_loader: Callable[..., Any] | None = None,
        window_stride_ratio: float = 0.5, *, versions: Sequence[VersionRecord] | None = None,
    ) -> None:
        self.enabled = enabled
        self.model_name = model_name
        self.candidate_limit = candidate_limit
        self._model_loader = model_loader or self._load_cross_encoder
        self._model: Any | None = None
        # P4-6: a passage longer than the model's input window is scored in
        # overlapping windows instead of being silently truncated. The stride is
        # a fraction of the window; 0.5 means each window shares half its tokens
        # with the previous one, so a phrase cannot fall in a seam.
        self.window_stride_ratio = window_stride_ratio
        # Model registry: the fallback chain, active first. None = legacy single-name
        # service — the loader is called as loader(name) with no kwargs, so the
        # `lambda _:` loaders of the existing tests keep working. () = the registry
        # has nothing to serve (reranker active: null); never indexed.
        self.versions: tuple[VersionRecord, ...] | None = tuple(versions) if versions is not None else None
        self.loaded: VersionRecord | None = None
        self.outcome: WarmupOutcome | None = None

    @classmethod
    def from_config(
        cls, rag_config: dict, *, enabled_override: bool | None = None, model_loader: Callable[..., Any] | None = None,
        versions: Sequence[VersionRecord] | None = None,
    ) -> "RerankerService":
        """Build from the models.yaml ``rag`` block, honouring a per-machine override.

        ``enabled_override`` is ``Settings.rag_reranker_enabled`` (env
        ``RAG_RERANKER_ENABLED``): ``None`` follows the shared models.yaml
        default; ``True``/``False`` lets one machine diverge without editing a
        versioned file. This matters more here than for P4-2: the reranker needs
        the optional ``[rerank]`` extra (PyTorch), so a machine that has not
        installed it pins the flag off instead of forking models.yaml.

        Same shape as ``ChunkContextService.from_config`` on purpose — one
        resolver idiom for every per-machine flag.

        ``versions`` is the registry chain (``Resolved.reranker_chain()``): the
        model name is the chain head's. ``None`` is the legacy read of
        ``rag.reranker.model``; ``()`` (reranker ``active: null``) is nothing to
        serve, so the service is built disabled and warmup reports ``no_versions``.
        """
        config = rag_config.get("reranker", {}) or {}
        yaml_enabled = bool(config.get("enabled", False))
        enabled = yaml_enabled if enabled_override is None else bool(enabled_override)
        if versions is None:
            model_name = str(config.get("model", HUB_DEFAULT_MODEL))
        elif len(versions) > 0:
            model_name = versions[0].name
        else:
            model_name, enabled = "", False
        logger.bind(
            event="reranker_config", enabled=enabled,
            source="env" if enabled_override is not None else "models.yaml",
            yaml_enabled=yaml_enabled, model=model_name,
            candidate_limit=int(config.get("candidate_limit", 15)),
        ).info(
            "Reranker {} ({})", "ON" if enabled else "OFF",
            "per-machine env override" if enabled_override is not None else "models.yaml default",
        )
        return cls(
            enabled,
            model_name,
            int(config.get("candidate_limit", 15)),
            model_loader=model_loader,
            versions=versions,
        )

    def warmup(self) -> WarmupOutcome:
        """Load the model now, at startup — and NEVER raise.

        Two reasons this is not left to the first question. A machine that turns
        the flag on without ``pip install -e .[rerank]`` must find out while it
        is starting the server, not when a user asks something. And the first
        cross-encoder call otherwise pays the whole model load, which would land
        on one unlucky question and distort the p95 the P4-3 gate is measured
        against.

        Finding out no longer means refusing to boot (invariant #5): every
        version of the chain is tried in order, a rejected one is logged as
        ``reranker_version_rejected`` with its reason, and an exhausted chain
        leaves the service disabled (pass-through) with ``source="fallback"`` so
        the resolver, /health and the nightly all see the deviation. The
        request-time contract is unchanged: a model that breaks later still
        raises RerankerUnavailableError -> 503.
        """
        if self.versions is not None and len(self.versions) == 0:
            # Checked before the flag: from_config already disabled the service for an
            # empty chain, and "unconfigured" is the truthful state, not "off".
            self.enabled = False
            outcome = WarmupOutcome("no_versions", None, None, None, None, None, None)
        elif not self.enabled:
            outcome = WarmupOutcome("flag_off", None, None, None, None, None, None)
        elif self.versions is None:
            outcome = self._warmup_legacy()
        else:
            outcome = self._warmup_chain()
        self.outcome = outcome
        return outcome

    def _warmup_legacy(self) -> WarmupOutcome:
        """Today's single-name load; an exception disables instead of raising."""
        started = perf_counter()
        try:
            self._model = self._model_loader(self.model_name)
        except Exception as error:
            code = "import" if isinstance(error, (ImportError, RerankerUnavailableError)) else "load"
            self.enabled = False
            logger.bind(event="reranker_version_rejected", version_id=self.model_name, source="legacy", reason=code, detail=str(error)[:300]).warning(
                "Reranker {} rejected ({}): {}", self.model_name, code, error
            )
            return WarmupOutcome("rejected_all", None, "legacy", f"{self.model_name} {code}: {error}", None, None, None)
        logger.bind(event="reranker_warmup", model=self.model_name, seconds=round(perf_counter() - started, 1)).info(
            "Reranker model loaded in {:.1f}s", perf_counter() - started
        )
        return WarmupOutcome("loaded", self.model_name, "legacy", None, None, None, None)

    def _warmup_chain(self) -> WarmupOutcome:
        assert self.versions is not None
        rejections: list[str] = []
        for index, record in enumerate(self.versions):
            kwargs = record.loader_kwargs()
            if index > 0:
                # A rejection may never start a download (invariant #5): only the
                # operator-chosen active version may reach the hub at warmup; a
                # fallback serves from the disk cache or is rejected as not_cached.
                kwargs["local_files_only"] = True
            started = perf_counter()
            try:
                model, digest_ok = self._load_version(record, kwargs)
                parity_ok = self._check_parity(model, record)
                latency_ms = self._timed_predict(model, record)
            except _VersionRejected as rejected:
                logger.bind(event="reranker_version_rejected", version_id=record.id, index=index, reason=rejected.code, detail=rejected.detail[:300]).warning(
                    "Reranker version {} rejected ({}): {}", record.id, rejected.code, rejected.detail
                )
                rejections.append(f"{record.id} {rejected.code}: {rejected.detail}")
                continue
            # The survivor: the lazy path in rerank() reloads THIS record, not the chain head.
            self._model, self.loaded, self.model_name = model, record, record.name
            source = "active" if index == 0 else "fallback"
            ms = int((perf_counter() - started) * 1000)
            max_ms = record.probe.max_ms if record.probe is not None else None
            over_cap = max_ms is not None and latency_ms is not None and latency_ms > max_ms
            log = logger.bind(
                event="reranker_version_loaded", version_id=record.id, source=source, ms=ms,
                digest_ok=digest_ok, parity_ok=parity_ok, latency_ms=latency_ms, max_ms=max_ms, over_cap=over_cap,
            )
            # Over the latency cap is a WARNING that keeps serving (invariant #7 asks for a
            # measured threshold, and the number is what the gate reads), never a rejection.
            (log.warning if over_cap else log.info)(
                "Reranker {} loaded as {} in {}ms (probe {}ms{})", record.id, source, ms, latency_ms,
                f" > cap {max_ms}ms" if over_cap else "",
            )
            reason = "; ".join([*rejections, f"serving {record.id}"]) if rejections else None
            return WarmupOutcome("loaded", record.id, source, reason, latency_ms, digest_ok, parity_ok)
        # Every version rejected: pass-through at rerank(); the resolver reports `disabled`.
        self.enabled = False
        return WarmupOutcome("rejected_all", None, "fallback", "; ".join(rejections), None, None, None)

    def _load_version(self, record: VersionRecord, kwargs: dict[str, Any]) -> tuple[Any, bool | None]:
        """Pre-load checks, the load itself, post-load checks. Raises _VersionRejected."""
        digest_ok: bool | None = None
        if record.path is not None:
            export = record.path / "export.json"
            if export.exists():
                # Contract with the exporter: the record's activation is a copy of
                # export.json's. A mismatch means the record lies about the
                # checkpoint, and the loader would force the wrong activation.
                try:
                    activation_fn = json.loads(export.read_text(encoding="utf-8")).get("activation_fn")
                except (OSError, ValueError) as error:
                    raise _VersionRejected("activation", f"export.json unreadable: {error}") from error
                if activation_fn != record.activation:
                    raise _VersionRejected("activation", f"export.json activation_fn={activation_fn!r} but the record says {record.activation!r}")
            if record.digest is not None:
                # Hash of the file AS WRITTEN: re-saving changes the bytes with
                # identical tensors, so "these bytes" is the only honest identity.
                digest_file = record.path / (record.digest_file or "model.safetensors")
                actual = self._sha256(digest_file)
                if actual != record.digest:
                    raise _VersionRejected("digest", f"{digest_file.name} sha256 {actual or 'missing'} != {record.digest}")
                digest_ok = True
        try:
            model = self._model_loader(record.name, **kwargs)
        except (ImportError, RerankerUnavailableError) as error:
            raise _VersionRejected("import", str(error)) from error
        except Exception as error:
            code = "not_cached" if kwargs.get("local_files_only") and self._is_not_cached(error) else "load"
            raise _VersionRejected(code, f"{type(error).__name__}: {error}") from error
        if record.num_labels is not None:
            actual_labels = self._num_labels(model)
            if actual_labels != record.num_labels:
                raise _VersionRejected("num_labels", f"{actual_labels} != {record.num_labels}")
        if record.max_length is not None:
            actual_length = self._input_limit(model)
            if actual_length != record.max_length:
                raise _VersionRejected("max_length", f"{actual_length} != {record.max_length}")
        return model, digest_ok

    def _check_parity(self, model: Any, record: VersionRecord) -> bool | None:
        """Probe-pair parity: None when the record carries no scores (disarmed)."""
        spec = record.probe
        if spec is None or spec.scores is None or not spec.pairs:
            return None
        try:
            scores = [float(value) for value in model.predict([list(pair) for pair in spec.pairs])]
        except Exception as error:
            raise _VersionRejected("parity", f"probe predict failed: {type(error).__name__}: {error}") from error
        if len(scores) != len(spec.scores):
            raise _VersionRejected("parity", f"{len(scores)} scores for {len(spec.scores)} pairs")
        for position, (score, expected) in enumerate(zip(scores, spec.scores, strict=True)):
            if abs(score - expected) > spec.tolerance:
                raise _VersionRejected("parity", f"pair {position}: {score:.4f} vs recorded {expected:.4f} (tolerance {spec.tolerance})")
        return True

    def _timed_predict(self, model: Any, record: VersionRecord) -> int | None:
        """One predict on TIMING_PAIRS pairs (the probe pairs cycled): the measured latency."""
        spec = record.probe
        if spec is None or not spec.pairs:
            return None
        cycled = [list(spec.pairs[index % len(spec.pairs)]) for index in range(TIMING_PAIRS)]
        started = perf_counter()
        try:
            model.predict(cycled)
        except Exception as error:
            raise _VersionRejected("load", f"timed predict failed: {type(error).__name__}: {error}") from error
        return int((perf_counter() - started) * 1000)

    @staticmethod
    def _num_labels(model: Any) -> int | None:
        """model.model.config.num_labels (the transformers head), else model.config."""
        for holder in (getattr(model, "model", None), model):
            config = getattr(holder, "config", None)
            value = getattr(config, "num_labels", None)
            if value is not None:
                return int(value)
        return None

    @staticmethod
    def _sha256(path: Any) -> str | None:
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
        except OSError:
            return None
        return digest.hexdigest()

    @staticmethod
    def _is_not_cached(error: BaseException) -> bool:
        """Is this a 'snapshot not in the disk cache' failure? Walks the cause chain:
        transformers wraps huggingface_hub's LocalEntryNotFoundError in an OSError."""
        seen: set[int] = set()
        current: BaseException | None = error
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if type(current).__name__ == "LocalEntryNotFoundError":
                return True
            message = str(current).lower()
            if any(marker in message for marker in _NOT_CACHED_MARKERS):
                return True
            current = current.__cause__ or current.__context__
        return False

    @staticmethod
    def _input_limit(model: Any) -> int:
        """The model's input window in tokens, read from the model, never hard-coded:
        a different cross-encoder has a different input size. CrossEncoder leaves
        ``max_length`` None unless it was passed (measured on 3.4.1), so the tokenizer's
        limit is the usual source."""
        limit = getattr(model, "max_length", None)
        if not limit:
            tokenizer = getattr(model, "tokenizer", None)
            limit = getattr(tokenizer, "model_max_length", None)
        # A tokenizer with no configured limit reports HuggingFace's sentinel,
        # which is astronomically large (VERY_LARGE_INTEGER, 1e30) — not merely
        # big. The guard must reject THAT while accepting a genuine long
        # context: Qwen3-Reranker reports 131072 and BGE-reranker-m3 8192, and
        # a 100_000 threshold silently forced both back to 512, discarding the
        # very capability such a model would be chosen for.
        if not isinstance(limit, int) or limit <= 0 or limit > _LIMIT_SENTINEL:
            limit = 512
        return int(limit)

    def _model_window(self, model: Any, question: str) -> int:
        """Passage tokens per scoring call: the model's input minus the question.

        Measured the hard way. A fixed safety margin (64 tokens) looked prudent
        and was actively harmful: on one candidate the answer sat at tokens
        448-510, so a 448-token window scored -0.710 while the model's own
        512-token truncation scored 1.405. The window must therefore be as
        WIDE as the model really allows — anything narrower invents a new cut
        in a method whose whole purpose is to remove one.
        """
        limit = self._input_limit(model)
        tokenizer = getattr(model, "tokenizer", None)
        question_tokens = len(tokenizer.encode(question, add_special_tokens=False)) if tokenizer else 0
        # Three specials for the [CLS] q [SEP] p [SEP] layout, plus one spare.
        return max(64, limit - question_tokens - 4)

    def _windows(self, model: Any, text: str, question: str) -> list[str]:
        """Split a passage into overlapping windows that each fit the model.

        Sliced out of the ORIGINAL string through the fast tokenizer's offset
        mapping, never re-decoded from token ids: decoding a slice collapses
        newlines (measured — a markdown passage's "

" came back as a single
        space) and that costs the model the paragraph and code-fence structure
        it scores on. On one candidate that round-trip alone moved the score
        from 1.405 to -0.008, i.e. it would have introduced a worse bug than
        the truncation this method exists to fix.

        Short passages -- the common case -- return unchanged and cost exactly
        what they cost before, so nothing about the majority path changes.
        """
        tokenizer = getattr(model, "tokenizer", None)
        if tokenizer is None or not getattr(tokenizer, "is_fast", False):
            # No offset mapping available: truncation is the old behaviour and
            # is still better than handing the model mangled text.
            return [text]
        encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        offsets = [span for span in encoded["offset_mapping"] if span[1] > span[0]]
        window = self._model_window(model, question)
        if len(offsets) <= window:
            return [text]
        stride = max(1, int(window * self.window_stride_ratio))
        pieces: list[str] = []
        for start in range(0, len(offsets), stride):
            span = offsets[start:start + window]
            if not span:
                break
            pieces.append(text[span[0][0]:span[-1][1]])
            if start + window >= len(offsets):
                break
        return pieces or [text]

    def rerank(self, question: str, candidates: list[dict[str, object]], top_k: int) -> list[dict[str, object]]:
        if not self.enabled:
            # Disabled means pass-through: candidate_limit is a rerank
            # budget and must not truncate a plain retrieval result.
            return candidates[:top_k]
        candidates = candidates[:self.candidate_limit]
        if len(candidates) <= 1:
            return candidates[:top_k]
        started = perf_counter()
        try:
            # Lazy reload goes through the loaded record's kwargs (revision, offline,
            # activation): a reload that bypassed the record could fetch a different
            # snapshot than warmup verified.
            model = self._model or self._model_loader(self.model_name, **(self.loaded.loader_kwargs() if self.loaded else {}))
            self._model = model
            # P4-6: one pair per WINDOW, not per candidate. A passage longer
            # than the model's input was previously truncated, so a phrase past
            # the cut was invisible to scoring -- on the production corpus that
            # was 65% of chunks. A candidate keeps its best window's score,
            # which is the standard reading of "does this passage answer it".
            pairs: list[tuple[str, str]] = []
            spans: list[tuple[int, int]] = []
            for candidate in candidates:
                windows = self._windows(model, str(candidate["content"]), question)
                spans.append((len(pairs), len(pairs) + len(windows)))
                pairs.extend((question, window) for window in windows)
            raw = model.predict(pairs)
            scores = [max(float(value) for value in raw[start:stop]) for start, stop in spans]
        except Exception as error:
            raise RerankerUnavailableError(f"Unable to load or run reranker {self.model_name}") from error
        ranked = [
            {**candidate, "reranker_score": float(score)}
            for candidate, score in sorted(zip(candidates, scores, strict=True), key=lambda item: item[1], reverse=True)
        ]
        # One line per question so the added milliseconds are attributable: the
        # /rag/search latency the eval reports is retrieval + this, and P4-3 is
        # gated on the delta (docs/p4_progress.md).
        logger.bind(event="rerank_done", candidates=len(candidates), windows=len(pairs), top_k=top_k, ms=int((perf_counter() - started) * 1000)).info(
            "Reranked {} candidates ({} windows) in {}ms", len(candidates), len(pairs), int((perf_counter() - started) * 1000)
        )
        return ranked[:top_k]

    @staticmethod
    def _load_cross_encoder(model_name: str, *, revision: str | None = None, local_files_only: bool = False, activation: str | None = None) -> Any:
        """CrossEncoder(model_name, revision=, local_files_only=, default_activation_function=).

        All three kwargs exist in sentence-transformers 3.4.1 (the [rerank] pin). The
        legacy call ``_load_cross_encoder(name)`` is byte-for-byte today's
        ``CrossEncoder(name)``: both extra kwargs are at their defaults.
        """
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as error:
            # T6: the library is an optional extra now — a clear pointer beats
            # a bare ModuleNotFoundError for whoever flips reranker.enabled.
            raise RerankerUnavailableError(
                "Reranker cần gói tùy chọn: pip install -e .[rerank]"
            ) from error
        kwargs: dict[str, Any] = {"revision": revision, "local_files_only": local_files_only or bool(os.getenv("HF_HUB_OFFLINE"))}
        if activation is not None:
            import torch

            # 3.4.1 picks Sigmoid for a 1-label head whose config lacks
            # sbert_ce_default_activation_function — every ST 5.x export — and the
            # scores saturate at logit >= 17 (measured: the shipped probe pairs go from
            # [2.998, -8.978, 7.515] to [0.95, 0.0001, 0.9995]). The record decides;
            # the loader enforces it; parity at warmup proves it.
            kwargs["default_activation_function"] = {"identity": torch.nn.Identity(), "sigmoid": torch.nn.Sigmoid()}[activation]
        return CrossEncoder(model_name, **kwargs)
