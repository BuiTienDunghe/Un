from __future__ import annotations

import socket

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.services.discord_memory_extractor import (
    DiscordMemoryExtractorAdapter,
)
from app.services.discord_memory_worker_service import (
    DiscordMemoryWorkerService,
)


def discord_memory_ingest(job_id: str) -> None:
    """RQ entrypoint for deterministic Discord-memory candidate filtering."""

    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for memory workers")
    sessions = create_session_factory(
        create_postgres_engine(str(settings.database_url))
    )
    extractor = (
        DiscordMemoryExtractorAdapter(
            base_url=settings.ollama_base_url,
            model=settings.discord_memory_extractor_model,
            schema_version=settings.discord_memory_extractor_schema_version,
            num_ctx=settings.discord_memory_extractor_num_ctx,
            temperature=settings.discord_memory_extractor_temperature,
            seed=settings.discord_memory_extractor_seed,
            timeout_seconds=settings.discord_memory_extractor_timeout_seconds,
            retry_count=settings.discord_memory_extractor_retry_count,
            json_fallback=settings.discord_memory_extractor_json_fallback,
        )
        if settings.discord_memory_extractor_enabled
        else None
    )
    outcome = DiscordMemoryWorkerService(
        sessions,
        worker_id=socket.gethostname(),
        lease_seconds=settings.job_stale_timeout_seconds,
        memory_policy_enabled=settings.discord_memory_ingestion_enabled,
        extractor_enabled=settings.discord_memory_extractor_enabled,
        extractor_model=settings.discord_memory_extractor_model,
        extractor_schema_version=(
            settings.discord_memory_extractor_schema_version
        ),
        extractor=extractor,
    ).process(job_id)
    if outcome.status == "retrying":
        # RQ Retry transports the same deterministic job ID; PostgreSQL owns
        # durable retry state and attempt count.
        raise RuntimeError("Discord memory rule-filter job requested retry")
