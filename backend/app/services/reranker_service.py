"""Cross-encoder reranking (P4-3): reorder retrieval candidates at QUERY time.

Unlike P4-2's contextual retrieval, this cost lands on every question, not on
indexing — so the thing to watch is latency, not model-call count. The
inference-budget invariant (plan §1) is about *generation* calls: a
cross-encoder is a small scoring model, so the number of generation calls per
question is unchanged. That is not a licence to ignore the cost; the added
milliseconds are measured and gated in docs/p4_progress.md.
"""
from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any

from loguru import logger


class RerankerUnavailableError(Exception):
    pass


class RerankerService:
    def __init__(self, enabled: bool, model_name: str, candidate_limit: int, model_loader: Callable[[str], Any] | None = None, window_stride_ratio: float = 0.5) -> None:
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

    @classmethod
    def from_config(cls, rag_config: dict, *, enabled_override: bool | None = None, model_loader: Callable[[str], Any] | None = None) -> "RerankerService":
        """Build from the models.yaml ``rag`` block, honouring a per-machine override.

        ``enabled_override`` is ``Settings.rag_reranker_enabled`` (env
        ``RAG_RERANKER_ENABLED``): ``None`` follows the shared models.yaml
        default; ``True``/``False`` lets one machine diverge without editing a
        versioned file. This matters more here than for P4-2: the reranker needs
        the optional ``[rerank]`` extra (PyTorch), so a machine that has not
        installed it pins the flag off instead of forking models.yaml.

        Same shape as ``ChunkContextService.from_config`` on purpose — one
        resolver idiom for every per-machine flag.
        """
        config = rag_config.get("reranker", {}) or {}
        yaml_enabled = bool(config.get("enabled", False))
        enabled = yaml_enabled if enabled_override is None else bool(enabled_override)
        logger.bind(
            event="reranker_config", enabled=enabled,
            source="env" if enabled_override is not None else "models.yaml",
            yaml_enabled=yaml_enabled, model=str(config.get("model", "")),
            candidate_limit=int(config.get("candidate_limit", 15)),
        ).info(
            "Reranker {} ({})", "ON" if enabled else "OFF",
            "per-machine env override" if enabled_override is not None else "models.yaml default",
        )
        return cls(
            enabled,
            str(config.get("model", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")),
            int(config.get("candidate_limit", 15)),
            model_loader=model_loader,
        )

    def warmup(self) -> None:
        """Load the model now, at startup, or fail loudly now.

        Two reasons this is not left to the first question. A machine that turns
        the flag on without ``pip install -e .[rerank]`` must find out while it
        is starting the server, not when a user asks something — the failure is
        a deployment mistake, and RerankerUnavailableError says exactly how to
        fix it. And the first cross-encoder call otherwise pays the whole model
        load, which would land on one unlucky question and distort the p95 the
        P4-3 gate is measured against.
        """
        if not self.enabled:
            return
        started = perf_counter()
        try:
            self._model = self._model_loader(self.model_name)
        except RerankerUnavailableError:
            raise
        except Exception as error:
            raise RerankerUnavailableError(f"Unable to load reranker {self.model_name}") from error
        logger.bind(event="reranker_warmup", model=self.model_name, seconds=round(perf_counter() - started, 1)).info(
            "Reranker model loaded in {:.1f}s", perf_counter() - started
        )

    def _model_window(self, model: Any, question: str) -> int:
        """Passage tokens per scoring call: the model's input minus the question.

        Measured the hard way. A fixed safety margin (64 tokens) looked prudent
        and was actively harmful: on one candidate the answer sat at tokens
        448-510, so a 448-token window scored -0.710 while the model's own
        512-token truncation scored 1.405. The window must therefore be as
        WIDE as the model really allows — anything narrower invents a new cut
        in a method whose whole purpose is to remove one.

        The limit is read from the model, never hard-coded: a different
        cross-encoder in models.yaml has a different input size.
        """
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
        if not isinstance(limit, int) or limit <= 0 or limit > 10_000_000:
            limit = 512
        tokenizer = getattr(model, "tokenizer", None)
        question_tokens = len(tokenizer.encode(question, add_special_tokens=False)) if tokenizer else 0
        # Three specials for the [CLS] q [SEP] p [SEP] layout, plus one spare.
        return max(64, int(limit) - question_tokens - 4)

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
            model = self._model or self._model_loader(self.model_name)
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
    def _load_cross_encoder(model_name: str) -> Any:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as error:
            # T6: the library is an optional extra now — a clear pointer beats
            # a bare ModuleNotFoundError for whoever flips reranker.enabled.
            raise RerankerUnavailableError(
                "Reranker cần gói tùy chọn: pip install -e .[rerank]"
            ) from error
        return CrossEncoder(model_name)
