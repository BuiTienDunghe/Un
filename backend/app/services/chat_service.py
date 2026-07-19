from __future__ import annotations

from pathlib import Path
from time import perf_counter
from uuid import uuid4
from collections.abc import Iterator

from app.services.logging_service import LoggingService
from app.services.model_router import ModelRouter
from app.services.memory_service import MemoryService
from app.stores.auxiliary_store import AuxiliaryStore


class ConversationNotFoundError(Exception):
    pass


class ChatService:
    def __init__(self, store: AuxiliaryStore, router: ModelRouter, logging_service: LoggingService, history_limit: int, memory_service: MemoryService | None = None) -> None:
        self.store = store
        self.router = router
        self.logging_service = logging_service
        self.history_limit = history_limit
        self.memory_service = memory_service
        self.system_prompt = (Path(__file__).parents[1] / "prompts" / "general_system.md").read_text(encoding="utf-8")
        self.memory_prompt = (Path(__file__).parents[1] / "prompts" / "memory_system.md").read_text(encoding="utf-8")

    def respond(self, message: str, conversation_id: str | None, use_memory: bool = False, system_prompt: str | None = None) -> tuple[str, str, str, int]:
        if conversation_id is None:
            conversation_id = str(uuid4())
            self.store.create_conversation(conversation_id)
        elif not self.store.conversation_exists(conversation_id):
            raise ConversationNotFoundError(conversation_id)

        history = self.store.get_messages(conversation_id, self.history_limit)
        messages = [{"role": "system", "content": system_prompt or self.system_prompt}]
        if use_memory and self.memory_service is not None:
            memories = self.memory_service.search(message, top_k=5)
            if memories:
                context = "\n".join(f"- {memory['content']}" for memory in memories)
                messages.append({"role": "system", "content": f"{self.memory_prompt}\n\nRelevant memories:\n{context}"})
        messages.extend([*history, {"role": "user", "content": message}])
        started = perf_counter()
        answer, model_used = self.router.chat("general", messages)
        latency_ms = int((perf_counter() - started) * 1000)
        self.store.add_message(conversation_id, "user", message)
        self.store.add_message(conversation_id, "assistant", answer, model_used)
        self.logging_service.log_request("/chat", model_used, latency_ms, "ok")
        return answer, model_used, conversation_id, latency_ms

    def stream_response(self, message: str, conversation_id: str | None, use_memory: bool = False, system_prompt: str | None = None) -> tuple[Iterator[str], str, str]:
        is_new = conversation_id is None
        if conversation_id is None:
            conversation_id = str(uuid4())
            self.store.create_conversation(conversation_id)
        elif not self.store.conversation_exists(conversation_id):
            raise ConversationNotFoundError(conversation_id)
        history = self.store.get_messages(conversation_id, self.history_limit)
        messages = [{"role": "system", "content": system_prompt or self.system_prompt}]
        if use_memory and self.memory_service is not None:
            memories = self.memory_service.search(message, top_k=5)
            if memories:
                context = "\n".join(f"- {memory['content']}" for memory in memories)
                messages.append({"role": "system", "content": f"{self.memory_prompt}\n\nRelevant memories:\n{context}"})
        messages.extend([*history, {"role": "user", "content": message}])
        tokens, model_used = self.router.stream_chat("general", messages)

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
                if completed:
                    answer = "".join(answer_parts)
                    latency_ms = int((perf_counter() - started) * 1000)
                    self.store.add_message(conversation_id, "user", message)
                    self.store.add_message(conversation_id, "assistant", answer, model_used)
                    self.logging_service.log_request("/chat", model_used, latency_ms, "ok")
                elif is_new:
                    self.store.delete_conversation(conversation_id)

        return generate(), model_used, conversation_id
