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
    def __init__(self, enabled: bool, model_name: str, candidate_limit: int, model_loader: Callable[[str], Any] | None = None) -> None:
        self.enabled = enabled
        self.model_name = model_name
        self.candidate_limit = candidate_limit
        self._model_loader = model_loader or self._load_cross_encoder
        self._model: Any | None = None

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
            scores = model.predict([(question, str(candidate["content"])) for candidate in candidates])
        except Exception as error:
            raise RerankerUnavailableError(f"Unable to load or run reranker {self.model_name}") from error
        ranked = [
            {**candidate, "reranker_score": float(score)}
            for candidate, score in sorted(zip(candidates, scores, strict=True), key=lambda item: item[1], reverse=True)
        ]
        # One line per question so the added milliseconds are attributable: the
        # /rag/search latency the eval reports is retrieval + this, and P4-3 is
        # gated on the delta (docs/p4_progress.md).
        logger.bind(event="rerank_done", candidates=len(candidates), top_k=top_k, ms=int((perf_counter() - started) * 1000)).info(
            "Reranked {} candidates in {}ms", len(candidates), int((perf_counter() - started) * 1000)
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
