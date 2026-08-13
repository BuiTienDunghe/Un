from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.postgres.discord_memory_job_repository import (
    DiscordMemoryJobRepository,
)


class DiscordMemoryRecoveryService:
    """Lease recovery isolated from document ingestion state machines."""

    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def recover_stale(
        self,
        *,
        limit: int = 100,
        dry_run: bool = False,
    ) -> int:
        count = 0
        with self.sessions.begin() as database:
            repository = DiscordMemoryJobRepository(database)
            for job in repository.stale_jobs(limit=limit):
                count += 1
                if not dry_run:
                    repository.requeue_stale(job)
        return count

