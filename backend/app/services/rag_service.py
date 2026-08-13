from __future__ import annotations

from pathlib import Path
from time import perf_counter
from collections.abc import Iterator

from app.services.logging_service import LoggingService
from app.services.model_router import ModelRouter
from typing import Protocol


class RetrievalBackend(Protocol):
    def retrieve(self, question: str, top_k: int, document_id: str | list[str] | None = None) -> list[dict[str, object]]: ...


class InsufficientContextError(Exception):
    pass


class RagService:
    def __init__(self, router: ModelRouter, logging_service: LoggingService, retrieval_service: RetrievalBackend, default_top_k: int = 5, max_context_chunks: int = 5) -> None:
        self.router = router
        self.logging_service = logging_service
        self.retrieval_service = retrieval_service
        self.default_top_k = max(1, default_top_k)
        self.max_context_chunks = max(1, max_context_chunks)
        self.system_prompt = (Path(__file__).parents[1] / "prompts" / "rag_system.md").read_text(encoding="utf-8")

    def _retrieve_context(self, question: str, top_k: int | None, document_id: str | list[str] | None) -> tuple[list[dict[str, object]], str]:
        """Retrieve and format context; returned sources are exactly the cited ones."""
        sources = self.retrieval_service.retrieve(question, top_k or self.default_top_k, document_id)
        # Only passages placed in the prompt may be reported as sources,
        # otherwise citation numbering would point at unseen passages.
        sources = sources[: self.max_context_chunks]
        if not sources:
            raise InsufficientContextError("No indexed document context was found")
        context = "\n\n".join(self._passage(index, source) for index, source in enumerate(sources))
        return sources, context

    @staticmethod
    def _passage(index: int, source: dict[str, object]) -> str:
        origin = str(source.get("filename", "unknown"))
        page = source.get("page_start")
        if page is not None:
            origin += f", page {page}" if source.get("page_end") in {None, page} else f", pages {page}-{source['page_end']}"
        return f"[Source {index + 1}] ({origin})\n{source['content']}"

    def respond(self, question: str, top_k: int | None, document_id: str | list[str] | None) -> tuple[str, str, int, list[dict[str, object]]]:
        started = perf_counter()
        sources, context = self._retrieve_context(question, top_k, document_id)
        answer, model_used = self.router.chat("general", [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}])
        latency_ms = int((perf_counter() - started) * 1000)
        self.logging_service.log_request("/rag/chat", model_used, latency_ms, "ok")
        return answer, model_used, latency_ms, sources

    def stream_response(self, question: str, top_k: int | None, document_id: str | list[str] | None) -> tuple[Iterator[str], str, list[dict[str, object]]]:
        sources, context = self._retrieve_context(question, top_k, document_id)
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
