from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RerankerUnavailableError(Exception):
    pass


class RerankerService:
    def __init__(self, enabled: bool, model_name: str, candidate_limit: int, model_loader: Callable[[str], Any] | None = None) -> None:
        self.enabled = enabled
        self.model_name = model_name
        self.candidate_limit = candidate_limit
        self._model_loader = model_loader or self._load_cross_encoder
        self._model: Any | None = None

    def rerank(self, question: str, candidates: list[dict[str, object]], top_k: int) -> list[dict[str, object]]:
        candidates = candidates[:self.candidate_limit]
        if not self.enabled or len(candidates) <= 1:
            return candidates[:top_k]
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
        return ranked[:top_k]

    @staticmethod
    def _load_cross_encoder(model_name: str) -> Any:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(model_name)
