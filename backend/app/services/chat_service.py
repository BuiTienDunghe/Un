from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from hashlib import sha256
from time import perf_counter
from uuid import uuid4
from collections.abc import Callable, Iterator

from loguru import logger

from app.llm_clients.usage import consume_usage
from app.services.agent_service import AGENT_GUIDE, STOP_TURN_BUDGET_EXHAUSTED, clock_note
from app.services.tool_state import ToolStateRecorder
from app.services.tool_state_bridge import continuity_scope, history_budget, restore_history
from app.services.input_metrics import model_input_measurements
from app.services.call_budget import CHAT_CALL_CAP, turn_call_budget
from app.services.logging_service import LoggingService
from app.services.model_router import ModelRouter
from app.services.memory_service import MemoryService
from app.services.pastes import search_text, shorten_pastes
from app.stores.auxiliary_store import AuxiliaryStore


class ConversationNotFoundError(Exception):
    pass


def derive_conversation_title(message: str) -> str | None:
    """First user message, whitespace-collapsed, as the server-side title."""
    title = " ".join(message.split())[:80].strip()
    return title or None


class ChatService:
    def __init__(self, store: AuxiliaryStore, router: ModelRouter, logging_service: LoggingService, history_limit: int, memory_service: MemoryService | None = None, *, tool_state_enabled: bool = False) -> None:
        self.store = store
        self.router = router
        self.logging_service = logging_service
        self.history_limit = history_limit
        self.memory_service = memory_service
        self.tool_state_enabled = tool_state_enabled
        self.source_memory = None
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
        user_id: str | None = None,
        on_step: Callable[[dict[str, object]], None] | None = None,
        tool_context: dict[str, object] | None = None,
    ) -> tuple[str, str, str, int, list[dict[str, object]] | None]:
        # tool_context: only the /chat route passes one, to mark the owner's turn (local_files.py).
        return self._respond(
            message,
            conversation_id,
            use_memory,
            system_prompt,
            use_tools=use_tools,
            user_id=user_id,
            on_step=on_step,
            tool_context=tool_context,
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
        tool_context: dict[str, object] | None = None,
        on_step: Callable[[dict[str, object]], None] | None = None,
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
            tool_context=tool_context,
            on_step=on_step,
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
        tool_context: dict[str, object] | None = None,
        user_id: str | None = None,
        on_step: Callable[[dict[str, object]], None] | None = None,
    ) -> tuple[str, str, str, int, list[dict[str, object]] | None]:
        from app.services.source_memory import MemoryReader, explicit_remember
        from contextlib import nullcontext
        v2 = self.source_memory
        reader = (tool_context or {}).get("_memory_reader") or MemoryReader.web(user_id)
        # Review2 R4: a web "remember" first takes its send time from the database clock, under
        # the memory locks. A forget that commits after this moment carries a later barrier, so
        # save() refuses even when the snapshot below already shows the forget's new epoch. It is
        # read before the app-clock stamp, so (with true clocks) a note that is saved always has a
        # message that stays in the history. The stored message keeps the app clock (review2 F).
        remember_sent_at = v2.now(reader) if v2 and model_history is None and explicit_remember(message) else None
        # Stamped before the epoch snapshot: if the user forgets during this turn, the
        # barrier lands after this moment and the history filter drops the message.
        sent_at = datetime.now(UTC)
        epoch, barrier = v2.snapshot(reader) if v2 else (None, None)
        if v2 and "_memory_epoch" in (tool_context or {}):
            epoch = tool_context["_memory_epoch"]
        if v2:
            tool_context = {**(tool_context or {}), "_memory_reader": reader, "_memory_epoch": epoch}
        is_new = conversation_id is None
        request_started = perf_counter()
        state_request_id = str((tool_context or {}).get("turn_id") or uuid4()) if self.tool_state_enabled else None
        if conversation_id is None:
            conversation_id = str(uuid4())
            self.store.create_conversation(conversation_id, derive_conversation_title(message), user_id)
        elif not self.store.conversation_exists(conversation_id):
            raise ConversationNotFoundError(conversation_id)
        elif v2 and model_history is None and self.store.conversation_owner(conversation_id) != user_id:
            raise ConversationNotFoundError(conversation_id)

        try:
            state_on = self.tool_state_enabled and use_tools and self.agent_service is not None
            history = (
                self.store.get_agent_history(conversation_id, self.history_limit)
                if state_on and model_history is None else
                self.store.get_messages(conversation_id, self.history_limit)
                if model_history is None
                else model_history
            )
            if v2 and model_history is None:
                history = v2.history(reader, conversation_id, self.history_limit)
            receipt = ""
            if v2 and model_history is None:
                from app.services.source_memory import explicit_forget
                if explicit_forget(message):
                    count = v2.forget_actor(reader.tenant, reader.actor)
                    epoch, barrier = v2.snapshot(reader)
                    history = v2.history(reader, conversation_id, self.history_limit)
                    tool_context["_memory_epoch"] = epoch
                    receipt = f"Backend đã quên {count} nguồn về người dùng."
                elif explicit_remember(message) and len(message) <= 10000:
                    from app.services.source_memory import MemoryConflict
                    try:
                        saved = v2.save(reader, message, source_id=f"web-turn:{uuid4()}", expected_epoch=epoch,
                                        sent_at=remember_sent_at)
                        receipt = f"Backend đã lưu nguyên văn source_id={saved['id']} revision={saved['revision']}."
                    except MemoryConflict:
                        receipt = "Chưa lưu: ngữ cảnh vừa bị sửa hoặc quên."
                elif explicit_remember(message):
                    receipt = "Chưa lưu: câu nguồn vượt giới hạn 10000 ký tự."
            agent_mode = use_tools and self.agent_service is not None
            if not agent_mode:
                # A paste from an earlier tool-mode turn: plain chat cannot open its slip,
                # so it gets a one-line note instead of the whole text (ticket 20 #3).
                history = shorten_pastes(history)
            messages = [{"role": "system", "content": system_prompt or self.system_prompt}]
            if receipt:
                messages.append({"role": "system", "content": receipt})
            if context_system_prompt:
                messages.append({"role": "system", "content": context_system_prompt})
            if v2 and use_memory:
                context = v2.context(reader, search_text(message))
                if context:
                    messages.append({"role": "system", "content": context})
            if not v2 and use_memory and self.memory_service is not None:
                memories = self.memory_service.search(search_text(message), top_k=5)
                if memories:
                    context = "\n".join(f"- {memory['content']}" for memory in memories)
                    messages.append({"role": "system", "content": f"{self.memory_prompt}\n\nRelevant memories:\n{context}"})
            if v2:
                from app.services.source_memory import bound_history
                offered = self.agent_service._offered_schemas(tool_context) if agent_mode else []
                guide = self.agent_service.defense.agent_guide(AGENT_GUIDE) if agent_mode else ""
                base = [*messages, current_model_message or {"role":"user", "content":message}]
                room = history_budget(base, offered, guide, int(self.router.models.get("general", {}).get("context",16384)))["room"]
                history, index_map = bound_history(history, min(12000, room))
                if "_state_anchors" in tool_context:
                    tool_context["_state_anchors"] = [{**a, "index":index_map[a["index"]]}
                        for a in tool_context["_state_anchors"] if a["index"] in index_map]
            history_rows = history
            history = [{key: value for key, value in row.items() if key != "message_id"} for row in history_rows]
            history_prefix = len(messages)
            messages.extend(
                [
                    *history,
                    clock_note(),
                    current_model_message or {"role": "user", "content": message},
                ]
            )
            agent_steps: list[dict[str, object]] | None = None
            recorder = None
            state_scope = None
            state_stats = {"groups": 0, "chars": 0, "dropped": 0}
            if state_on:
                recorder = ToolStateRecorder()
                state_scope = continuity_scope(conversation_id, user_id, tool_context)
                schemas = self.agent_service._offered_schemas(tool_context)
                # Conservative character budget, including the actual schemas
                # and guide. This is an estimate, not a tokenizer guarantee.
                window = int(self.router.models.get("general", {}).get("context", 16384))
                budget = history_budget(messages, schemas, self.agent_service.defense.agent_guide(AGENT_GUIDE), window)
                base_chars, schema_chars = budget["base_chars"], budget["schema_chars"]
                try:
                    messages, state_stats = restore_history(self.store, conversation_id, state_scope, messages,
                        history_prefix, history_rows, tool_context, self.agent_service.registry, budget["room"],
                        allowed_names={schema["function"]["name"] for schema in schemas})
                except Exception as error:
                    logger.bind(event="tool_state_load_failed", error_type=type(error).__name__).warning("Tool history unavailable; using text history")
                tool_context = {**(tool_context or {}), "_tool_recorder": recorder}
                logger.bind(event="tool_state_context", request_id=state_request_id,
                    base_chars=base_chars, schema_chars=schema_chars, history_chars=state_stats["chars"],
                    groups=state_stats["groups"], dropped=state_stats["dropped"]).info("Prepared bounded tool history")
            started = perf_counter()
            # In agent mode the agent counts its own calls; this turn adds none (ticket 43).
            with model_input_measurements(state_on) as input_metrics, turn_call_budget("chat", 0 if agent_mode else CHAT_CALL_CAP):
                if agent_mode:
                    # on_step: the agent's progress, for a caller that shows it (ticket 20 #4).
                    answer, model_used, agent_steps = self.agent_service.run(
                        messages, tool_context=tool_context, on_step=on_step
                    )
                else:
                    answer, model_used = self.router.chat("general", messages)
        except Exception:
            # The turn produced nothing durable; a failed model call must not
            # leave an empty conversation shell in the sidebar. Mirrors the
            # stream path below and RagService.respond.
            if is_new:
                self.store.delete_conversation(conversation_id)
            raise
        model_finished = perf_counter()
        # Full-request latency, not model-call latency: the dashboard feeds
        # every row into one percentile, and a row that skips history + memory
        # lookup is a different quantity wearing the same name.
        latency_ms = int((perf_counter() - request_started) * 1000)
        usage = consume_usage()
        with v2.publication(reader, epoch) if v2 else nullcontext(True) as current:
            if not current:
                answer = "Nguồn trí nhớ vừa được sửa hoặc quên. Vui lòng hỏi lại để dùng dữ liệu hiện tại."
                agent_steps, recorder = None, None
            # A revoked turn keeps the user's words on screen, but stamped at send time
            # (before the barrier) so they never come back as model history.
            self.store.add_message(conversation_id, "user", message, **({"created_at": sent_at} if v2 else {}))
            assistant_message_id = self.store.add_message(conversation_id, "assistant", answer, model_used)
            if agent_steps:
                # Trace rows attach to the persisted answer they explain (P2-2).
                # Discord turns are the ones that carry their guild; the web's do not.
                source = "discord" if (tool_context or {}).get("guild_id") else "web"
                self.store.add_agent_traces(conversation_id, assistant_message_id, agent_steps, source=source)
                if recorder is not None and state_scope is not None:
                    try:
                        payload = recorder.payload()
                        if payload.get("groups"):
                            self.store.save_tool_state(conversation_id, assistant_message_id, state_scope, payload,
                                                       origin=(tool_context or {}).get("turn_id"))
                    except Exception as error:
                        logger.bind(event="tool_state_save_failed", error_type=type(error).__name__).warning("Answer saved but tool history unavailable")
        # Ticket 16: a turn that ran out of time replied with a fixed sentence, not an
        # answer; the dashboard counts it as an error, under its own code.
        out_of_time = bool(agent_steps) and agent_steps[-1].get("stop_reason") == STOP_TURN_BUDGET_EXHAUSTED
        self.logging_service.log_request(
            "/chat", model_used, latency_ms, "error" if out_of_time else "ok",
            "AGENT_TURN_BUDGET" if out_of_time else None,
            message_id=assistant_message_id, tokens_in=usage["tokens_in"], tokens_out=usage["tokens_out"],
            # Hashed per turn: /chat accepts a caller-supplied system prompt
            # (the Discord bot sends its own), so one constant would lie.
            prompt_hash=sha256(str(messages[0]["content"]).encode("utf-8")).hexdigest(),
        )
        if state_on:
            logger.bind(event="tool_state_request_completed", request_id=state_request_id,
                prepare_ms=round((started-request_started)*1000), agent_ms=round((model_finished-started)*1000),
                persist_ms=round((perf_counter()-model_finished)*1000), model_calls=len(input_metrics or []),
                message_chars=sum(row["message_chars"] for row in input_metrics or []),
                schema_chars=sum(row["schema_chars"] for row in input_metrics or []),
                tokens_in=usage["tokens_in"], tokens_out=usage["tokens_out"]).info("Completed state-enabled request")
        return answer, model_used, conversation_id, latency_ms, agent_steps

    def stream_response(self, message: str, conversation_id: str | None, use_memory: bool = False, system_prompt: str | None = None, user_id: str | None = None) -> tuple[Iterator[str], str, str]:
        if self.source_memory:
            # Buffer until the generation check succeeds; never stream revoked context.
            answer, model, cid, _, _ = self.respond(message, conversation_id, use_memory, system_prompt, user_id=user_id)
            return iter([answer]), model, cid
        is_new = conversation_id is None
        if conversation_id is None:
            conversation_id = str(uuid4())
            self.store.create_conversation(conversation_id, derive_conversation_title(message), user_id)
        elif not self.store.conversation_exists(conversation_id):
            raise ConversationNotFoundError(conversation_id)
        # The stream path is plain chat: a paste in the history becomes its note (ticket 20 #3).
        history = shorten_pastes(self.store.get_messages(conversation_id, self.history_limit))
        messages = [{"role": "system", "content": system_prompt or self.system_prompt}]
        if use_memory and self.memory_service is not None:
            memories = self.memory_service.search(search_text(message), top_k=5)
            if memories:
                context = "\n".join(f"- {memory['content']}" for memory in memories)
                messages.append({"role": "system", "content": f"{self.memory_prompt}\n\nRelevant memories:\n{context}"})
        messages.extend([*history, clock_note(), {"role": "user", "content": message}])
        started = perf_counter()
        with turn_call_budget("chat", CHAT_CALL_CAP):
            tokens, model_used = self.router.stream_chat("general", messages)
        prompt_hash = sha256(str(messages[0]["content"]).encode("utf-8")).hexdigest()

        def generate() -> Iterator[str]:
            answer_parts: list[str] = []
            completed = False
            last_token_at = perf_counter()
            try:
                for token in tokens:
                    answer_parts.append(token)
                    last_token_at = perf_counter()
                    yield token
                completed = True
            finally:
                if completed or answer_parts:
                    # A turn the user stopped mid-stream is still a real turn:
                    # persist the partial answer so history matches what the
                    # user saw on screen.
                    answer = "".join(answer_parts)
                    usage = consume_usage()
                    # See rag_service: on abort this finally runs at garbage
                    # collection, seconds later — the last token is the only
                    # honest end of a stopped turn.
                    ended_at = perf_counter() if completed else last_token_at
                    latency_ms = int((ended_at - started) * 1000)
                    assistant_message_id: int | None = None
                    try:
                        self.store.add_message(conversation_id, "user", message)
                        assistant_message_id = self.store.add_message(conversation_id, "assistant", answer, model_used)
                    except Exception:
                        # Conversation deleted during the abort-to-collection
                        # window: transcript lost, measurement kept.
                        pass
                    # An interrupted stream used to be logged as "ok" — one of
                    # the reasons 142/142 production rows carried that status.
                    self.logging_service.log_request(
                        "/chat", model_used, latency_ms, "ok" if completed else "stopped",
                        message_id=assistant_message_id, tokens_in=usage["tokens_in"], tokens_out=usage["tokens_out"], prompt_hash=prompt_hash,
                    )
                elif is_new:
                    # No token ever arrived; drop the conversation shell.
                    self.store.delete_conversation(conversation_id)

        return generate(), model_used, conversation_id
