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


def derive_conversation_title(message: str) -> str | None:
    """First user message, whitespace-collapsed, as the server-side title."""
    title = " ".join(message.split())[:80].strip()
    return title or None


class ChatService:
    def __init__(self, store: AuxiliaryStore, router: ModelRouter, logging_service: LoggingService, history_limit: int, memory_service: MemoryService | None = None) -> None:
        self.store = store
        self.router = router
        self.logging_service = logging_service
        self.history_limit = history_limit
        self.memory_service = memory_service
        # Assigned by the composition root after the retrieval stack exists
        # (the agent needs services that are built later than this one).
        # None keeps every `use_tools` request on the plain-chat path.
        self.agent_service = None
        self.system_prompt = (Path(__file__).parents[1] / "prompts" / "general_system.md").read_text(encoding="utf-8")
        self.memory_prompt = (Path(__file__).parents[1] / "prompts" / "memory_system.md").read_text(encoding="utf-8")

    def respond(
        self,
        message: str,
        conversation_id: str | None,
        use_memory: bool = False,
        system_prompt: str | None = None,
        use_tools: bool = False,
    ) -> tuple[str, str, str, int, list[dict[str, object]] | None]:
        return self._respond(
            message,
            conversation_id,
            use_memory,
            system_prompt,
            use_tools=use_tools,
        )

    def respond_with_context(
        self,
        message: str,
        conversation_id: str,
        *,
        model_history: list[dict[str, str]],
        current_model_message: dict[str, str],
        context_system_prompt: str,
        system_prompt: str | None = None,
        use_tools: bool = False,
    ) -> tuple[str, str, str, int]:
        """Run chat with caller-built trusted context while persisting raw text.

        The ordinary Web UI path continues through ``respond`` and therefore
        retains its existing store-backed history behavior. Agent steps are
        persisted but not returned — Discord renders only the answer.
        """
        answer, model_used, returned_id, latency_ms, _ = self._respond(
            message,
            conversation_id,
            False,
            system_prompt,
            model_history=model_history,
            current_model_message=current_model_message,
            context_system_prompt=context_system_prompt,
            use_tools=use_tools,
        )
        return answer, model_used, returned_id, latency_ms

    def _respond(
        self,
        message: str,
        conversation_id: str | None,
        use_memory: bool,
        system_prompt: str | None,
        *,
        model_history: list[dict[str, str]] | None = None,
        current_model_message: dict[str, str] | None = None,
        context_system_prompt: str | None = None,
        use_tools: bool = False,
    ) -> tuple[str, str, str, int, list[dict[str, object]] | None]:
        is_new = conversation_id is None
        if conversation_id is None:
            conversation_id = str(uuid4())
            self.store.create_conversation(conversation_id, derive_conversation_title(message))
        elif not self.store.conversation_exists(conversation_id):
            raise ConversationNotFoundError(conversation_id)

        try:
            history = (
                self.store.get_messages(conversation_id, self.history_limit)
                if model_history is None
                else model_history
            )
            messages = [{"role": "system", "content": system_prompt or self.system_prompt}]
            if context_system_prompt:
                messages.append({"role": "system", "content": context_system_prompt})
            if use_memory and self.memory_service is not None:
                memories = self.memory_service.search(message, top_k=5)
                if memories:
                    context = "\n".join(f"- {memory['content']}" for memory in memories)
                    messages.append({"role": "system", "content": f"{self.memory_prompt}\n\nRelevant memories:\n{context}"})
            messages.extend(
                [
                    *history,
                    current_model_message or {"role": "user", "content": message},
                ]
            )
            started = perf_counter()
            agent_steps: list[dict[str, object]] | None = None
            if use_tools and self.agent_service is not None:
                answer, model_used, agent_steps = self.agent_service.run(messages)
            else:
                answer, model_used = self.router.chat("general", messages)
        except Exception:
            # The turn produced nothing durable; a failed model call must not
            # leave an empty conversation shell in the sidebar. Mirrors the
            # stream path below and RagService.respond.
            if is_new:
                self.store.delete_conversation(conversation_id)
            raise
        latency_ms = int((perf_counter() - started) * 1000)
        self.store.add_message(conversation_id, "user", message)
        assistant_message_id = self.store.add_message(conversation_id, "assistant", answer, model_used)
        if agent_steps:
            # Trace rows attach to the persisted answer they explain (P2-2).
            self.store.add_agent_traces(conversation_id, assistant_message_id, agent_steps)
        self.logging_service.log_request("/chat", model_used, latency_ms, "ok")
        return answer, model_used, conversation_id, latency_ms, agent_steps

    def stream_response(self, message: str, conversation_id: str | None, use_memory: bool = False, system_prompt: str | None = None) -> tuple[Iterator[str], str, str]:
        is_new = conversation_id is None
        if conversation_id is None:
            conversation_id = str(uuid4())
            self.store.create_conversation(conversation_id, derive_conversation_title(message))
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
                if completed or answer_parts:
                    # A turn the user stopped mid-stream is still a real turn:
                    # persist the partial answer so history matches what the
                    # user saw on screen.
                    answer = "".join(answer_parts)
                    latency_ms = int((perf_counter() - started) * 1000)
                    self.store.add_message(conversation_id, "user", message)
                    self.store.add_message(conversation_id, "assistant", answer, model_used)
                    self.logging_service.log_request("/chat", model_used, latency_ms, "ok")
                elif is_new:
                    # No token ever arrived; drop the conversation shell.
                    self.store.delete_conversation(conversation_id)

        return generate(), model_used, conversation_id
