from __future__ import annotations

from pathlib import Path
from time import perf_counter
from uuid import uuid4
from collections.abc import Iterator

from app.services.chat_service import ConversationNotFoundError, derive_conversation_title
from app.services.logging_service import LoggingService
from app.services.model_router import ModelRouter
from app.stores.auxiliary_store import AuxiliaryStore
from typing import Protocol


class RetrievalBackend(Protocol):
    def retrieve(self, question: str, top_k: int, document_id: str | list[str] | None = None) -> list[dict[str, object]]: ...


class InsufficientContextError(Exception):
    pass


class RagService:
    def __init__(self, router: ModelRouter, logging_service: LoggingService, retrieval_service: RetrievalBackend, default_top_k: int = 5, max_context_chunks: int = 5, store: AuxiliaryStore | None = None) -> None:
        self.router = router
        self.logging_service = logging_service
        self.retrieval_service = retrieval_service
        self.default_top_k = max(1, default_top_k)
        self.max_context_chunks = max(1, max_context_chunks)
        self.store = store
        self.system_prompt = (Path(__file__).parents[1] / "prompts" / "rag_system.md").read_text(encoding="utf-8")

    def _resolve_conversation(self, question: str, conversation_id: str | None) -> tuple[str | None, bool]:
        """Create or validate the conversation this RAG turn belongs to.

        RAG answers are persisted as ordinary conversation turns so users can
        reopen them later; the retrieval context itself stays single-question
        (history is never fed into the RAG prompt).
        """
        if self.store is None:
            return None, False
        if conversation_id is None:
            conversation_id = str(uuid4())
            self.store.create_conversation(conversation_id, derive_conversation_title(question))
            return conversation_id, True
        if not self.store.conversation_exists(conversation_id):
            raise ConversationNotFoundError(conversation_id)
        return conversation_id, False

    def _persist_turn(self, conversation_id: str | None, question: str, answer: str, model_used: str, sources: list[dict[str, object]] | None = None) -> None:
        if self.store is None or conversation_id is None:
            return
        self.store.add_message(conversation_id, "user", question)
        self.store.add_message(conversation_id, "assistant", answer, model_used, self._citations(sources or []))

    @staticmethod
    def _citations(sources: list[dict[str, object]]) -> list[dict[str, object]]:
        """Reduce retrieval hits to what a reopened conversation needs to show.

        The excerpt is stored as a snapshot rather than re-read from the chunk
        at display time: a citation must keep showing the text the answer was
        actually based on, even after the document is replaced or removed.
        """
        return [
            {
                "document_id": source.get("document_id", ""),
                "chunk_id": source.get("chunk_id", source.get("chunk_index", "")),
                "filename": source.get("filename", ""),
                # The retrieval payload carries `page` for single-page chunks.
                "page_start": source.get("page_start", source.get("page")),
                "page_end": source.get("page_end"),
                "heading_path": source.get("heading_path"),
                "score": source.get("score", 0.0),
                "excerpt": str(source.get("content", ""))[:300],
            }
            for source in sources
        ]

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

    def respond(self, question: str, top_k: int | None, document_id: str | list[str] | None, conversation_id: str | None = None) -> tuple[str, str, int, list[dict[str, object]], str | None]:
        started = perf_counter()
        conversation_id, created = self._resolve_conversation(question, conversation_id)
        try:
            sources, context = self._retrieve_context(question, top_k, document_id)
            answer, model_used = self.router.chat("general", [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}])
        except Exception:
            if created and self.store is not None:
                self.store.delete_conversation(conversation_id)
            raise
        latency_ms = int((perf_counter() - started) * 1000)
        self._persist_turn(conversation_id, question, answer, model_used, sources)
        self.logging_service.log_request("/rag/chat", model_used, latency_ms, "ok")
        return answer, model_used, latency_ms, sources, conversation_id

    def stream_response(self, question: str, top_k: int | None, document_id: str | list[str] | None, conversation_id: str | None = None) -> tuple[Iterator[str], str, list[dict[str, object]], str | None]:
        conversation_id, created = self._resolve_conversation(question, conversation_id)
        try:
            sources, context = self._retrieve_context(question, top_k, document_id)
            tokens, model_used = self.router.stream_chat("general", [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}])
        except Exception:
            if created and self.store is not None:
                self.store.delete_conversation(conversation_id)
            raise

        def generate() -> Iterator[str]:
            started = perf_counter()
            answer_parts: list[str] = []
            completed = False
            try:
                for token in tokens:
                    answer_parts.append(token)
                    yield token
                completed = True
            finally:
                if completed or answer_parts:
                    # A stopped stream keeps its partial answer, and the
                    # citations it was already grounded in go with it.
                    self._persist_turn(conversation_id, question, "".join(answer_parts), model_used, sources)
                    if completed:
                        self.logging_service.log_request("/rag/chat", model_used, int((perf_counter() - started) * 1000), "ok")
                elif created and self.store is not None:
                    self.store.delete_conversation(conversation_id)

        return generate(), model_used, sources, conversation_id
