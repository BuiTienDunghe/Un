from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.postgres.models import (
    Conversation,
    DiscordConversationSession,
    DiscordSessionTurn,
    DiscordTurnDelivery,
)


class DiscordSessionRepository:
    """Persistence primitives used inside caller-owned short transactions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_active(
        self,
        guild_id: str,
        channel_id: str,
        thread_id: str | None,
        *,
        lock: bool = False,
    ) -> DiscordConversationSession | None:
        statement = select(DiscordConversationSession).where(
            DiscordConversationSession.guild_id == guild_id,
            DiscordConversationSession.channel_id == channel_id,
            DiscordConversationSession.status == "active",
        )
        statement = statement.where(
            DiscordConversationSession.thread_id.is_(None)
            if thread_id is None
            else DiscordConversationSession.thread_id == thread_id
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def backend_conversation_exists(self, conversation_id: UUID) -> bool:
        return self.session.get(Conversation, str(conversation_id)) is not None

    def create_backend_conversation(self) -> UUID:
        conversation_id = uuid4()
        self.session.add(Conversation(id=str(conversation_id)))
        return conversation_id

    def create_session(
        self,
        guild_id: str,
        channel_id: str,
        thread_id: str | None,
        backend_conversation_id: UUID,
    ) -> DiscordConversationSession:
        now = datetime.now(UTC)
        session = DiscordConversationSession(
            id=uuid4(),
            guild_id=guild_id,
            channel_id=channel_id,
            thread_id=thread_id,
            backend_conversation_id=backend_conversation_id,
            origin="discord",
            visibility="internal",
            status="active",
            started_at=now,
            last_active_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(session)
        return session

    @staticmethod
    def touch(session: DiscordConversationSession) -> None:
        now = datetime.now(UTC)
        session.last_active_at = now
        session.updated_at = now

    @staticmethod
    def mark_orphaned(session: DiscordConversationSession) -> None:
        now = datetime.now(UTC)
        session.status = "orphaned"
        session.orphaned_at = now
        session.updated_at = now

    def enqueue_turn(
        self,
        session_id: UUID,
        discord_message_id: str,
        request_text: str,
        *,
        author_id: str | None,
        author_display_name: str | None,
        reply_to_discord_message_id: str | None = None,
        system_prompt: str | None = None,
        available_at: datetime | None = None,
        max_attempts: int = 3,
    ) -> tuple[DiscordSessionTurn, bool]:
        # Locking the parent serializes sequence allocation without holding a
        # transaction during model inference. The future worker will claim and
        # complete turns in separate short transactions.
        parent = self.session.scalar(
            select(DiscordConversationSession)
            .where(DiscordConversationSession.id == session_id)
            .with_for_update()
        )
        if parent is None:
            raise KeyError(str(session_id))
        # The factory disables autoflush. Flush any earlier turn added in the
        # same transaction before idempotency/max-sequence queries.
        self.session.flush()
        existing = self.session.scalar(
            select(DiscordSessionTurn).where(
                DiscordSessionTurn.session_id == session_id,
                DiscordSessionTurn.discord_message_id == discord_message_id,
            )
        )
        if existing is not None:
            return existing, False
        sequence = int(
            self.session.scalar(
                select(func.coalesce(func.max(DiscordSessionTurn.sequence_number), 0)).where(
                    DiscordSessionTurn.session_id == session_id
                )
            )
            or 0
        ) + 1
        now = datetime.now(UTC)
        turn = DiscordSessionTurn(
            id=uuid4(),
            session_id=session_id,
            discord_message_id=discord_message_id,
            sequence_number=sequence,
            request_text=request_text,
            author_id=author_id,
            author_display_name=author_display_name,
            reply_to_discord_message_id=reply_to_discord_message_id,
            system_prompt=system_prompt,
            status="queued",
            available_at=available_at or now,
            max_attempts=max_attempts,
            created_at=now,
            updated_at=now,
        )
        self.session.add(turn)
        return turn, True

    def context_turns(
        self,
        session_id: UUID,
        before_sequence: int,
        *,
        limit: int,
    ) -> list[DiscordSessionTurn]:
        if limit <= 0:
            return []
        rows = list(
            self.session.scalars(
                select(DiscordSessionTurn)
                .where(
                    DiscordSessionTurn.session_id == session_id,
                    DiscordSessionTurn.sequence_number < before_sequence,
                    # Only responses actually delivered and acknowledged by
                    # Discord are safe shared-channel history.
                    DiscordSessionTurn.status == "completed",
                    # A non-null response means ChatService successfully added
                    # the user/assistant pair to the backend conversation.
                    DiscordSessionTurn.response_text.is_not(None),
                )
                .order_by(DiscordSessionTurn.sequence_number.desc())
                .limit(limit)
            )
        )
        rows.reverse()
        return rows

    def find_reply_target_turn(
        self,
        session_id: UUID,
        discord_message_id: str,
        *,
        before_sequence: int,
    ) -> DiscordSessionTurn | None:
        """Find an exact invocation target inside the current Discord session."""

        return self.session.scalar(
            select(DiscordSessionTurn).where(
                DiscordSessionTurn.session_id == session_id,
                DiscordSessionTurn.discord_message_id == discord_message_id,
                DiscordSessionTurn.sequence_number < before_sequence,
            )
        )

    def reply_target_exists_outside_session(
        self,
        session_id: UUID,
        discord_message_id: str,
    ) -> bool:
        """Distinguish a cross-session reference without exposing its content."""

        return (
            self.session.scalar(
                select(DiscordSessionTurn.id)
                .where(
                    DiscordSessionTurn.session_id != session_id,
                    DiscordSessionTurn.discord_message_id == discord_message_id,
                )
                .limit(1)
            )
            is not None
        )

    def find_bot_response_delivery(
        self,
        session_id: UUID,
        discord_message_id: str,
        *,
        before_sequence: int,
    ) -> tuple[DiscordTurnDelivery, DiscordSessionTurn] | None:
        """Resolve an exact delivered bot message inside the current session."""

        return self.session.execute(
            select(DiscordTurnDelivery, DiscordSessionTurn)
            .join(
                DiscordSessionTurn,
                DiscordSessionTurn.id == DiscordTurnDelivery.turn_id,
            )
            .where(
                DiscordSessionTurn.session_id == session_id,
                DiscordSessionTurn.sequence_number < before_sequence,
                DiscordTurnDelivery.discord_message_id == discord_message_id,
            )
        ).first()

    def bot_response_exists_outside_session(
        self,
        session_id: UUID,
        discord_message_id: str,
    ) -> bool:
        """Detect cross-session bot-response IDs without exposing their data."""

        return (
            self.session.scalar(
                select(DiscordTurnDelivery.id)
                .join(
                    DiscordSessionTurn,
                    DiscordSessionTurn.id == DiscordTurnDelivery.turn_id,
                )
                .where(
                    DiscordSessionTurn.session_id != session_id,
                    DiscordTurnDelivery.discord_message_id
                    == discord_message_id,
                )
                .limit(1)
            )
            is not None
        )

    def delivery_message_ids(self, turn_id: UUID) -> list[str]:
        return list(
            self.session.scalars(
                select(DiscordTurnDelivery.discord_message_id)
                .where(DiscordTurnDelivery.turn_id == turn_id)
                .order_by(DiscordTurnDelivery.chunk_index)
            )
        )

    def cancel_open_turns(
        self,
        *,
        reason: str,
    ) -> list[DiscordSessionTurn]:
        """Terminally cancel every queued/running Discord turn.

        The controller stops the bot before invoking this operation, so parent
        row locks close the remaining enqueue/claim race without holding a
        transaction during inference.
        """
        session_ids = list(
            self.session.scalars(
                select(DiscordSessionTurn.session_id)
                .where(DiscordSessionTurn.status.in_(("queued", "running")))
                .distinct()
            )
        )
        cancelled: list[DiscordSessionTurn] = []
        now = datetime.now(UTC)
        for session_id in sorted(session_ids, key=str):
            parent = self.session.scalar(
                select(DiscordConversationSession)
                .where(DiscordConversationSession.id == session_id)
                .with_for_update()
            )
            if parent is None:
                continue
            turns = list(
                self.session.scalars(
                    select(DiscordSessionTurn)
                    .where(
                        DiscordSessionTurn.session_id == session_id,
                        DiscordSessionTurn.status.in_(("queued", "running")),
                    )
                    .order_by(DiscordSessionTurn.sequence_number)
                    .with_for_update()
                )
            )
            for turn in turns:
                turn.status = "cancelled"
                turn.completed_at = now
                turn.error = reason[:4_000]
                turn.worker_id = None
                turn.lease_expires_at = None
                turn.heartbeat_at = None
                turn.updated_at = now
                cancelled.append(turn)
        return cancelled

    def claim_turn(
        self,
        turn_id: UUID,
        worker_id: str,
        *,
        lease_seconds: int,
    ) -> DiscordSessionTurn | None:
        target = self.session.get(DiscordSessionTurn, turn_id)
        if target is None:
            raise KeyError(str(turn_id))
        # The parent row is the per-session mutex. It serializes competing
        # claimers without blocking unrelated sessions.
        parent = self.session.scalar(
            select(DiscordConversationSession)
            .where(DiscordConversationSession.id == target.session_id)
            .with_for_update()
        )
        if parent is None:
            raise KeyError(str(target.session_id))
        self.session.refresh(target)
        now = datetime.now(UTC)
        head = self.session.scalar(
            select(DiscordSessionTurn)
            .where(
                DiscordSessionTurn.session_id == target.session_id,
                DiscordSessionTurn.status.in_(("queued", "running")),
            )
            .order_by(DiscordSessionTurn.sequence_number)
            .limit(1)
            .with_for_update()
        )
        if (
            head is None
            or head.id != target.id
            or head.status != "queued"
            or head.available_at > now
        ):
            return None
        head.status = "running"
        head.worker_id = worker_id
        head.started_at = now
        head.heartbeat_at = now
        head.lease_expires_at = now + timedelta(seconds=lease_seconds)
        head.attempt_count += 1
        head.error = None
        head.updated_at = now
        self.session.flush()
        return head

    def heartbeat_turn(
        self,
        turn_id: UUID,
        worker_id: str,
        *,
        lease_seconds: int,
    ) -> bool:
        turn = self.session.scalar(
            select(DiscordSessionTurn)
            .where(DiscordSessionTurn.id == turn_id)
            .with_for_update()
        )
        now = datetime.now(UTC)
        if (
            turn is None
            or turn.status != "running"
            or turn.worker_id != worker_id
            or turn.lease_expires_at is None
            or turn.lease_expires_at <= now
        ):
            return False
        turn.heartbeat_at = now
        turn.lease_expires_at = now + timedelta(seconds=lease_seconds)
        turn.updated_at = now
        return True

    def save_response(
        self,
        turn_id: UUID,
        worker_id: str,
        response_text: str,
        model_used: str,
        *,
        lease_seconds: int,
    ) -> bool:
        turn = self.session.scalar(
            select(DiscordSessionTurn)
            .where(DiscordSessionTurn.id == turn_id)
            .with_for_update()
        )
        now = datetime.now(UTC)
        if (
            turn is None
            or turn.status != "running"
            or turn.worker_id != worker_id
            or turn.lease_expires_at is None
            or turn.lease_expires_at <= now
        ):
            return False
        turn.response_text = response_text
        turn.model_used = model_used
        turn.heartbeat_at = now
        turn.lease_expires_at = now + timedelta(seconds=lease_seconds)
        turn.updated_at = now
        return True

    def complete_turn(
        self,
        turn_id: UUID,
        worker_id: str,
        discord_response_message_ids: list[str],
    ) -> Literal["completed", "idempotent", "conflict", "ownership_lost"]:
        turn = self.session.scalar(
            select(DiscordSessionTurn)
            .where(DiscordSessionTurn.id == turn_id)
            .with_for_update()
        )
        if turn is None:
            return "ownership_lost"
        existing_ids = self.delivery_message_ids(turn_id)
        if turn.status == "completed":
            return (
                "idempotent"
                if existing_ids == discord_response_message_ids
                and bool(existing_ids)
                else "conflict"
            )
        now = datetime.now(UTC)
        if (
            turn.status != "running"
            or turn.worker_id != worker_id
            or turn.lease_expires_at is None
            or turn.lease_expires_at <= now
        ):
            return "ownership_lost"
        linked_turn_ids = list(
            self.session.execute(
                select(
                    DiscordTurnDelivery.discord_message_id,
                    DiscordTurnDelivery.turn_id,
                ).where(
                    DiscordTurnDelivery.discord_message_id.in_(
                        discord_response_message_ids
                    )
                )
            )
        )
        if any(linked_turn_id != turn_id for _, linked_turn_id in linked_turn_ids):
            return "conflict"
        for chunk_index, message_id in enumerate(discord_response_message_ids):
            self.session.add(
                DiscordTurnDelivery(
                    id=uuid4(),
                    turn_id=turn_id,
                    discord_message_id=message_id,
                    chunk_index=chunk_index,
                    created_at=now,
                )
            )
        turn.status = "completed"
        turn.completed_at = now
        turn.worker_id = None
        turn.lease_expires_at = None
        turn.heartbeat_at = None
        turn.updated_at = now
        return "completed"

    def fail_turn(
        self,
        turn_id: UUID,
        worker_id: str,
        error: str,
        *,
        retryable: bool,
        retry_delay_seconds: int = 0,
    ) -> DiscordSessionTurn | None:
        turn = self.session.scalar(
            select(DiscordSessionTurn)
            .where(DiscordSessionTurn.id == turn_id)
            .with_for_update()
        )
        now = datetime.now(UTC)
        if (
            turn is None
            or turn.status != "running"
            or turn.worker_id != worker_id
            or turn.lease_expires_at is None
            or turn.lease_expires_at <= now
        ):
            return None
        turn.error = error[:4_000]
        turn.worker_id = None
        turn.lease_expires_at = None
        turn.heartbeat_at = None
        turn.updated_at = now
        if retryable and turn.attempt_count < turn.max_attempts:
            turn.status = "queued"
            turn.available_at = now + timedelta(seconds=retry_delay_seconds)
            turn.completed_at = None
        else:
            turn.status = "failed"
            turn.completed_at = now
        return turn

    def cancel_turn(self, turn_id: UUID, error: str | None = None) -> bool:
        turn = self.session.scalar(
            select(DiscordSessionTurn)
            .where(DiscordSessionTurn.id == turn_id)
            .with_for_update()
        )
        if turn is None or turn.status != "queued":
            return False
        now = datetime.now(UTC)
        turn.status = "cancelled"
        turn.completed_at = now
        turn.error = error[:4_000] if error else None
        turn.updated_at = now
        return True

    def recover_stale(self, *, limit: int = 100) -> list[DiscordSessionTurn]:
        now = datetime.now(UTC)
        stale = list(
            self.session.scalars(
                select(DiscordSessionTurn)
                .where(
                    DiscordSessionTurn.status == "running",
                    DiscordSessionTurn.lease_expires_at <= now,
                )
                .order_by(DiscordSessionTurn.lease_expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for turn in stale:
            turn.error = "Worker lease expired."
            turn.worker_id = None
            turn.lease_expires_at = None
            turn.heartbeat_at = None
            turn.updated_at = now
            if turn.attempt_count < turn.max_attempts:
                turn.status = "queued"
                turn.available_at = now
                turn.completed_at = None
            else:
                turn.status = "failed"
                turn.completed_at = now
        return stale
