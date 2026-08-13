from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.postgres.discord_repositories import DiscordSessionRepository
from app.postgres.models import DiscordConversationSession


ACTIVE_SESSION_CONSTRAINTS = {
    "uq_discord_active_channel_session",
    "uq_discord_active_thread_session",
}


class DiscordSessionInputError(ValueError):
    pass


class DiscordDirectMessageUnsupportedError(DiscordSessionInputError):
    pass


@dataclass(frozen=True)
class DiscordSessionResolution:
    session_id: UUID
    backend_conversation_id: UUID
    created: bool
    status: str


class DiscordSessionService:
    """Resolve canonical Discord locations using PostgreSQL as source of truth."""

    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    @staticmethod
    def normalize(
        guild_id: str | None,
        channel_id: str,
        thread_id: str | None,
    ) -> tuple[str, str, str | None]:
        if guild_id is None:
            raise DiscordDirectMessageUnsupportedError("Direct messages are not supported in Sprint 1.")
        normalized_guild = guild_id.strip()
        normalized_channel = channel_id.strip()
        normalized_thread = thread_id.strip() if thread_id is not None else None
        if not normalized_guild:
            raise DiscordSessionInputError("guild_id cannot be empty.")
        if not normalized_channel:
            raise DiscordSessionInputError("channel_id cannot be empty.")
        if thread_id is not None and not normalized_thread:
            raise DiscordSessionInputError("thread_id cannot be empty when provided.")
        return normalized_guild, normalized_channel, normalized_thread

    @staticmethod
    def _result(session: DiscordConversationSession, created: bool) -> DiscordSessionResolution:
        return DiscordSessionResolution(
            session_id=session.id,
            backend_conversation_id=session.backend_conversation_id,
            created=created,
            status=session.status,
        )

    @staticmethod
    def _constraint_name(error: IntegrityError) -> str | None:
        diagnostic = getattr(getattr(error, "orig", None), "diag", None)
        return getattr(diagnostic, "constraint_name", None)

    def resolve(
        self,
        guild_id: str | None,
        channel_id: str,
        thread_id: str | None = None,
    ) -> DiscordSessionResolution:
        canonical = self.normalize(guild_id, channel_id, thread_id)
        for _ in range(3):
            try:
                with self.sessions.begin() as database:
                    repository = DiscordSessionRepository(database)
                    active = repository.find_active(*canonical, lock=True)
                    if active is not None and repository.backend_conversation_exists(active.backend_conversation_id):
                        repository.touch(active)
                        return self._result(active, False)
                    if active is not None:
                        repository.mark_orphaned(active)
                    conversation_id = repository.create_backend_conversation()
                    replacement = repository.create_session(*canonical, conversation_id)
                    database.flush()
                    return self._result(replacement, True)
            except IntegrityError as error:
                if self._constraint_name(error) not in ACTIVE_SESSION_CONSTRAINTS:
                    raise

            # A concurrent transaction won the partial unique index. Its
            # backend conversation was committed atomically with the mapping.
            with self.sessions.begin() as database:
                repository = DiscordSessionRepository(database)
                winner = repository.find_active(*canonical, lock=True)
                if winner is not None and repository.backend_conversation_exists(winner.backend_conversation_id):
                    repository.touch(winner)
                    return self._result(winner, False)
            # If the winner changed state or its conversation disappeared
            # immediately, retry the normal orphan lifecycle after closing the
            # read transaction.
        raise RuntimeError("Discord session resolution did not stabilize after concurrent updates.")
