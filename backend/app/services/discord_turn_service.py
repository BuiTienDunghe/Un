from __future__ import annotations

import threading
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.postgres.discord_memory_repositories import DiscordMemoryRepository
from app.postgres.discord_repositories import DiscordSessionRepository
from app.postgres.models import DiscordConversationSession, DiscordSessionTurn
from app.services.chat_service import ChatService, ConversationNotFoundError
from app.services.discord_session_service import DiscordSessionService
from app.services.discord_memory_completion_service import (
    DiscordMemoryCompletionService,
)
from app.services.discord_speaker_context import (
    DISCORD_HISTORY_USAGE_RULES,
    DISCORD_SPEAKER_ATTRIBUTION_RULES,
    BotReplyTargetContext,
    DiscordReplyTargetContext,
    ReplyTargetContext,
    build_discord_speaker_context,
)


class DiscordTurnNotFoundError(KeyError):
    pass


class DiscordTurnOwnershipError(RuntimeError):
    pass


class DiscordTurnDeliveryConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscordTurnResult:
    turn_id: UUID
    session_id: UUID
    sequence_number: int
    status: str
    created: bool = False
    answer: str | None = None
    model_used: str | None = None
    execution_token: str | None = None
    replacement_turn_id: UUID | None = None


class DiscordTurnService:
    """Durable per-session FIFO lifecycle with short database transactions."""

    def __init__(
        self,
        sessions: sessionmaker,
        session_service: DiscordSessionService,
        chat_service: ChatService,
        *,
        lease_seconds: int = 120,
        max_attempts: int = 3,
        memory_completion_service: DiscordMemoryCompletionService | None = None,
        agent_tools_enabled: bool = False,
        agent_tools_guild_allowlist: frozenset[str] | None = None,
    ) -> None:
        self.sessions = sessions
        self.session_service = session_service
        self.chat_service = chat_service
        self.lease_seconds = max(3, lease_seconds)
        self.max_attempts = max(1, max_attempts)
        self.memory_completion_service = memory_completion_service
        # P2-2: Discord turns become agent turns (tool use + trace) when on.
        self.agent_tools_enabled = agent_tools_enabled
        # The document corpus is backend-wide, so tools only run for guilds
        # the operator listed. None = allow every guild (explicit "*" in
        # settings); an EMPTY set fails CLOSED — a misconfigured allowlist
        # must not reopen the observed cross-guild document leak (review
        # finding 28/08).
        self.agent_tools_guild_allowlist = agent_tools_guild_allowlist
        self.history_turn_limit = max(
            1,
            int(getattr(chat_service, "history_limit", 12)) // 2,
        )

    def _tools_allowed_for_guild(self, guild_id: str | None) -> bool:
        if not self.agent_tools_enabled:
            return False
        if self.agent_tools_guild_allowlist is None:
            return True
        return guild_id in self.agent_tools_guild_allowlist

    @staticmethod
    def _result(
        turn: DiscordSessionTurn,
        *,
        created: bool = False,
        execution_token: str | None = None,
        status: str | None = None,
        replacement_turn_id: UUID | None = None,
    ) -> DiscordTurnResult:
        return DiscordTurnResult(
            turn_id=turn.id,
            session_id=turn.session_id,
            sequence_number=turn.sequence_number,
            status=status or turn.status,
            created=created,
            answer=turn.response_text,
            model_used=turn.model_used,
            execution_token=execution_token,
            replacement_turn_id=replacement_turn_id,
        )

    def enqueue(
        self,
        session_id: UUID,
        discord_message_id: str,
        message: str,
        system_prompt: str | None = None,
        *,
        author_id: str,
        author_display_name: str,
        reply_to_discord_message_id: str | None = None,
    ) -> DiscordTurnResult:
        normalized_message_id = discord_message_id.strip()
        normalized_author_id = author_id.strip()
        normalized_display_name = author_display_name.strip()
        normalized_reply_id = (
            reply_to_discord_message_id.strip()
            if reply_to_discord_message_id is not None
            else None
        )
        if not normalized_message_id:
            raise ValueError("discord_message_id cannot be empty.")
        if not message.strip():
            raise ValueError("message cannot be empty.")
        if not normalized_author_id:
            raise ValueError("author_id cannot be empty.")
        if not normalized_display_name:
            raise ValueError("author_display_name cannot be empty.")
        if normalized_reply_id == "":
            raise ValueError("reply_to_discord_message_id cannot be empty.")
        return self._enqueue_persisted(
            session_id,
            normalized_message_id,
            message,
            system_prompt,
            author_id=normalized_author_id,
            author_display_name=normalized_display_name,
            reply_to_discord_message_id=normalized_reply_id,
        )

    def _enqueue_persisted(
        self,
        session_id: UUID,
        discord_message_id: str,
        message: str,
        system_prompt: str | None,
        *,
        author_id: str | None,
        author_display_name: str | None,
        reply_to_discord_message_id: str | None,
    ) -> DiscordTurnResult:
        with self.sessions.begin() as database:
            repository = DiscordSessionRepository(database)
            try:
                turn, created = repository.enqueue_turn(
                    session_id,
                    discord_message_id,
                    message,
                    author_id=author_id,
                    author_display_name=author_display_name,
                    reply_to_discord_message_id=reply_to_discord_message_id,
                    system_prompt=system_prompt,
                    max_attempts=self.max_attempts,
                )
            except KeyError as error:
                raise DiscordTurnNotFoundError(str(session_id)) from error
            database.flush()
            return self._result(turn, created=created)

    def get(self, turn_id: UUID) -> DiscordTurnResult:
        with self.sessions() as database:
            turn = database.get(DiscordSessionTurn, turn_id)
            if turn is None:
                raise DiscordTurnNotFoundError(str(turn_id))
            return self._result(turn)

    def claim(self, turn_id: UUID) -> DiscordTurnResult:
        token = uuid4().hex
        with self.sessions.begin() as database:
            repository = DiscordSessionRepository(database)
            try:
                claimed = repository.claim_turn(
                    turn_id,
                    token,
                    lease_seconds=self.lease_seconds,
                )
            except KeyError as error:
                raise DiscordTurnNotFoundError(str(turn_id)) from error
            if claimed is not None:
                return self._result(claimed, execution_token=token)
            current = database.get(DiscordSessionTurn, turn_id)
            if current is None:
                raise DiscordTurnNotFoundError(str(turn_id))
            return self._result(current)

    def heartbeat(self, turn_id: UUID, execution_token: str) -> None:
        with self.sessions.begin() as database:
            if not DiscordSessionRepository(database).heartbeat_turn(
                turn_id,
                execution_token,
                lease_seconds=self.lease_seconds,
            ):
                raise DiscordTurnOwnershipError("Turn lease is no longer owned by this execution.")

    def complete(
        self,
        turn_id: UUID,
        execution_token: str,
        discord_response_message_ids: list[str],
    ) -> DiscordTurnResult:
        normalized_ids = [value.strip() for value in discord_response_message_ids]
        if (
            not normalized_ids
            or len(normalized_ids) > 16
            or any(not value or len(value) > 64 for value in normalized_ids)
            or len(set(normalized_ids)) != len(normalized_ids)
        ):
            raise ValueError(
                "Discord response message IDs must contain 1-16 unique, "
                "non-empty identifiers."
            )
        try:
            with self.sessions.begin() as database:
                repository = DiscordSessionRepository(database)
                outcome = repository.complete_turn(
                    turn_id,
                    execution_token,
                    normalized_ids,
                )
                if outcome == "ownership_lost":
                    raise DiscordTurnOwnershipError(
                        "Turn lease is no longer owned by this execution."
                    )
                if outcome == "conflict":
                    raise DiscordTurnDeliveryConflictError(
                        "Turn completion conflicts with persisted Discord "
                        "response delivery IDs."
                    )
                if (
                    outcome == "completed"
                    and self.memory_completion_service is not None
                ):
                    self.memory_completion_service.on_first_completion(
                        database,
                        turn_id,
                    )
                database.flush()
                turn = database.get(DiscordSessionTurn, turn_id)
                assert turn is not None
                return self._result(turn)
        except IntegrityError as error:
            raise DiscordTurnDeliveryConflictError(
                "A Discord response message is already linked to another turn."
            ) from error

    def fail(
        self,
        turn_id: UUID,
        execution_token: str,
        error: str,
        *,
        retryable: bool,
    ) -> DiscordTurnResult:
        with self.sessions.begin() as database:
            turn = DiscordSessionRepository(database).fail_turn(
                turn_id,
                execution_token,
                error,
                retryable=retryable,
            )
            if turn is None:
                raise DiscordTurnOwnershipError("Turn lease is no longer owned by this execution.")
            return self._result(turn)

    def cancel(self, turn_id: UUID, error: str | None = None) -> DiscordTurnResult:
        with self.sessions.begin() as database:
            repository = DiscordSessionRepository(database)
            if not repository.cancel_turn(turn_id, error):
                raise DiscordTurnOwnershipError("Only a queued turn can be cancelled.")
            turn = database.get(DiscordSessionTurn, turn_id)
            assert turn is not None
            return self._result(turn)

    def cancel_open_for_operator_stop(self) -> list[DiscordTurnResult]:
        with self.sessions.begin() as database:
            turns = DiscordSessionRepository(database).cancel_open_turns(
                reason="Cancelled because the Discord bot was stopped by the operator.",
            )
            return [self._result(turn) for turn in turns]

    def recover_stale(self, *, limit: int = 100) -> list[DiscordTurnResult]:
        with self.sessions.begin() as database:
            turns = DiscordSessionRepository(database).recover_stale(limit=limit)
            return [self._result(turn) for turn in turns]

    def _heartbeat_loop(
        self,
        turn_id: UUID,
        execution_token: str,
        stop: threading.Event,
    ) -> None:
        interval = max(1, self.lease_seconds // 3)
        while not stop.wait(interval):
            try:
                self.heartbeat(turn_id, execution_token)
            except DiscordTurnOwnershipError:
                return

    @staticmethod
    def _resolve_reply_target(
        repository: DiscordSessionRepository,
        turn: DiscordSessionTurn,
    ) -> DiscordReplyTargetContext | None:
        """Resolve an exact target without relying on history text or display names."""

        reply_id = turn.reply_to_discord_message_id
        if reply_id is None:
            return None
        target = repository.find_reply_target_turn(
            turn.session_id,
            reply_id,
            before_sequence=turn.sequence_number,
        )
        if target is not None:
            has_stable_author = bool(target.author_id)
            return ReplyTargetContext(
                discord_message_id=reply_id,
                sequence=target.sequence_number,
                author_id=target.author_id,
                author_display_name=target.author_display_name,
                request_text=target.request_text,
                resolution_status=(
                    "resolved_user_message"
                    if has_stable_author
                    else "legacy_unavailable"
                ),
                same_author_as_current=(
                    target.author_id == turn.author_id
                    if has_stable_author and bool(turn.author_id)
                    else None
                ),
            )
        bot_delivery = repository.find_bot_response_delivery(
            turn.session_id,
            reply_id,
            before_sequence=turn.sequence_number,
        )
        if bot_delivery is not None:
            _, originating_turn = bot_delivery
            return BotReplyTargetContext(
                discord_response_message_id=reply_id,
                originating_turn_sequence=originating_turn.sequence_number,
                originating_user_author_id=originating_turn.author_id,
                originating_user_display_name=(
                    originating_turn.author_display_name
                ),
                originating_request_text=originating_turn.request_text,
                assistant_response_text=originating_turn.response_text or "",
                resolution_status="resolved_bot_response",
                same_originating_author_as_current=(
                    originating_turn.author_id == turn.author_id
                    if originating_turn.author_id and turn.author_id
                    else None
                ),
            )
        resolution_status = (
            "outside_session"
            if repository.reply_target_exists_outside_session(
                turn.session_id,
                reply_id,
            )
            or repository.bot_response_exists_outside_session(
                turn.session_id,
                reply_id,
            )
            else "not_found"
        )
        return ReplyTargetContext(
            discord_message_id=reply_id,
            sequence=None,
            author_id=None,
            author_display_name=None,
            request_text=None,
            resolution_status=resolution_status,
            same_author_as_current=None,
        )

    def _orphan_and_requeue(
        self,
        turn: DiscordSessionTurn,
        execution_token: str,
    ) -> DiscordTurnResult:
        with self.sessions() as database:
            source_session = database.get(DiscordConversationSession, turn.session_id)
            if source_session is None:
                raise DiscordTurnNotFoundError(str(turn.session_id))
            canonical = (
                source_session.guild_id,
                source_session.channel_id,
                source_session.thread_id,
            )
        # Keep the old head running until its replacement has been durably
        # enqueued. This prevents a later old-session turn from racing ahead
        # and receiving the first sequence on the replacement session.
        replacement_session = self.session_service.resolve(*canonical)
        replacement = self._enqueue_persisted(
            replacement_session.session_id,
            turn.discord_message_id,
            turn.request_text,
            turn.system_prompt,
            author_id=turn.author_id,
            author_display_name=turn.author_display_name,
            reply_to_discord_message_id=turn.reply_to_discord_message_id,
        )
        self.fail(
            turn.id,
            execution_token,
            "Backend conversation no longer exists; turn moved to a replacement session.",
            retryable=False,
        )
        return DiscordTurnResult(
            turn_id=turn.id,
            session_id=turn.session_id,
            sequence_number=turn.sequence_number,
            status="requeued",
            replacement_turn_id=replacement.turn_id,
        )

    def execute(self, turn_id: UUID) -> DiscordTurnResult:
        # Recovery is its own short transaction. Claim commits before any model
        # call, and completion/failure happens in a later transaction.
        self.recover_stale()
        claimed = self.claim(turn_id)
        if claimed.status != "running" or claimed.execution_token is None:
            return claimed

        execution_token = claimed.execution_token
        with self.sessions() as database:
            turn = database.get(DiscordSessionTurn, turn_id)
            if turn is None:
                raise DiscordTurnNotFoundError(str(turn_id))
            request_text = turn.request_text
            system_prompt = turn.system_prompt
            response_text = turn.response_text
            model_used = turn.model_used
            session = database.get(DiscordConversationSession, turn.session_id)
            if session is None:
                raise DiscordTurnNotFoundError(str(turn.session_id))
            conversation_id = str(session.backend_conversation_id)
            use_tools_for_turn = self._tools_allowed_for_guild(session.guild_id)
            repository = DiscordSessionRepository(database)
            previous_turns = repository.context_turns(
                turn.session_id,
                turn.sequence_number,
                limit=self.history_turn_limit,
            )
            reply_target = self._resolve_reply_target(repository, turn)
            speaker_context = build_discord_speaker_context(
                previous_turns,
                turn,
                reply_target=reply_target,
            )
            model_history = [*speaker_context.history]
            if speaker_context.reply_target_message is not None:
                model_history.append(speaker_context.reply_target_message)
            # Memory reaches the answer as an unconditional ledger SELECT, not
            # as a tool the model may or may not call (measured: 4/19 turns)
            # and not via the unfiltered Qdrant mirror (memory_design.md §3).
            # Same transaction as the history read; the model call stays
            # outside it (invariant #2). Zero extra model calls (invariant #7).
            # Step 4 (28/08): guild-wide, not asker-only — both observed
            # production uses cross the asker boundary (PA asking about
            # Dũng's birthday; Dũng asking what PA stated about him). Each
            # line names its subject by author_id so the model can join it
            # against the speaker labels in the history. Ordering is a
            # MEASURED variable (§13.7): the history-usage rules must be the
            # LAST system content, so the memory block goes in the middle.
            active_memories = DiscordMemoryRepository(database).list_active_context_memories(
                guild_id=session.guild_id,
                subject_id=None,
                all_members=True,
                limit=50,
            )
            if active_memories:
                memory_lines = "\n".join(
                    (
                        f"- [{memory.fact_key} | về author_id="
                        f"{memory.subject_id}] {memory.canonical_fact}"
                        if memory.scope == "member_in_guild"
                        else f"- [{memory.fact_key} | về server] "
                        f"{memory.canonical_fact}"
                    )
                    for memory in active_memories
                )
                context_system_prompt = (
                    f"{DISCORD_SPEAKER_ATTRIBUTION_RULES}\n"
                    "Trí nhớ dài hạn đã được xác nhận về server và thành viên "
                    "(chỉ dùng khi câu hỏi thật sự liên quan):\n"
                    f"{memory_lines}\n\n"
                    f"{DISCORD_HISTORY_USAGE_RULES}"
                )
            else:
                context_system_prompt = speaker_context.system_instruction

        # A delivery retry reuses the stored response and never calls the model
        # a second time.
        if response_text is not None:
            return DiscordTurnResult(
                turn_id=turn_id,
                session_id=claimed.session_id,
                sequence_number=claimed.sequence_number,
                status="running",
                answer=response_text,
                model_used=model_used,
                execution_token=execution_token,
            )

        stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(turn_id, execution_token, stop),
            daemon=True,
        )
        heartbeat.start()
        try:
            answer, used_model, _, _ = self.chat_service.respond_with_context(
                request_text,
                conversation_id,
                model_history=model_history,
                current_model_message=speaker_context.current_message,
                context_system_prompt=context_system_prompt,
                system_prompt=system_prompt,
                use_tools=use_tools_for_turn,
            )
        except ConversationNotFoundError:
            return self._orphan_and_requeue(turn, execution_token)
        except Exception as error:
            return self.fail(
                turn_id,
                execution_token,
                f"{type(error).__name__}: {error}",
                retryable=True,
            )
        finally:
            stop.set()
            heartbeat.join(timeout=1)

        with self.sessions.begin() as database:
            saved = DiscordSessionRepository(database).save_response(
                turn_id,
                execution_token,
                answer,
                used_model,
                lease_seconds=self.lease_seconds,
            )
            if not saved:
                raise DiscordTurnOwnershipError(
                    "Turn ownership was lost before the response could be persisted."
                )
            turn = database.get(DiscordSessionTurn, turn_id)
            assert turn is not None
            return self._result(turn, execution_token=execution_token)
