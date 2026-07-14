from __future__ import annotations

from pathlib import Path
from time import perf_counter
from collections.abc import Iterator

from app.services.logging_service import LoggingService
from app.services.model_router import ModelRouter
from app.services.retrieval_service import RetrievalService


class InsufficientContextError(Exception):
    pass


class RagService:
    def __init__(self, router: ModelRouter, logging_service: LoggingService, retrieval_service: RetrievalService) -> None:
        self.router = router
        self.logging_service = logging_service
        self.retrieval_service = retrieval_service
        self.system_prompt = (Path(__file__).parents[1] / "prompts" / "rag_system.md").read_text(encoding="utf-8")

    def respond(self, question: str, top_k: int, document_id: str | None) -> tuple[str, str, int, list[dict[str, object]]]:
        started = perf_counter()
        sources = self.retrieval_service.retrieve(question, top_k, document_id)
        if not sources:
            raise InsufficientContextError("No indexed document context was found")
        context = "\n\n".join(f"[Source {index + 1}] {source['content']}" for index, source in enumerate(sources))
        answer, model_used = self.router.chat("general", [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}])
        latency_ms = int((perf_counter() - started) * 1000)
        self.logging_service.log_request("/rag/chat", model_used, latency_ms, "ok")
        return answer, model_used, latency_ms, sources

    def stream_response(self, question: str, top_k: int, document_id: str | None) -> tuple[Iterator[str], str, list[dict[str, object]]]:
        sources = self.retrieval_service.retrieve(question, top_k, document_id)
        if not sources:
            raise InsufficientContextError("No indexed document context was found")
        context = "\n\n".join(f"[Source {index + 1}] {source['content']}" for index, source in enumerate(sources))
        tokens, model_used = self.router.stream_chat("general", [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}])

        def generate() -> Iterator[str]:
            started = perf_counter()
            completed = False
            try:
                for token in tokens:
                    yield token
                completed = True
            finally:
                if completed:
                    self.logging_service.log_request("/rag/chat", model_used, int((perf_counter() - started) * 1000), "ok")

        return generate(), model_used, sources
