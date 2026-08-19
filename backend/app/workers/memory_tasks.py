from __future__ import annotations

import socket

from app.config.settings import get_settings
from app.llm_clients.ollama_client import OllamaClient
from app.postgres.database import create_postgres_engine, create_session_factory
from app.services.discord_memory_extractor import (
    DiscordMemoryExtractorAdapter,
)
from app.services.discord_memory_review_service import (
    DiscordMemoryReviewService,
)
from app.services.discord_memory_worker_service import (
    DiscordMemoryWorkerService,
)
from app.services.logging_service import LoggingService
from app.services.memory_service import MemoryService
from app.services.model_router import ModelRouter
from app.stores.postgres_auxiliary_store import PostgresAuxiliaryStore
from app.stores.qdrant_store import QdrantStore


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
    # P2-1: with a threshold configured, the worker applies its own
    # high-confidence proposals through the same review service the dashboard
    # uses — identical audit trail and web mirror, reviewed_by="agent".
    review_service = None
    if (
        settings.discord_memory_extractor_enabled
        and settings.discord_memory_auto_apply_threshold is not None
    ):
        auxiliary_store = PostgresAuxiliaryStore(sessions)
        review_service = DiscordMemoryReviewService(
            sessions,
            MemoryService(
                auxiliary_store,
                QdrantStore(
                    settings.qdrant_url,
                    settings.qdrant_timeout_seconds,
                    settings.qdrant_memories_collection,
                ),
                ModelRouter(
                    {
                        "ollama": OllamaClient(
                            settings.ollama_base_url,
                            settings.ollama_chat_timeout_seconds,
                            settings.ollama_health_timeout_seconds,
                            settings.ollama_retry_count,
                        )
                    },
                    settings.load_models(),
                ),
                LoggingService(auxiliary_store, settings.logs_path),
            ),
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
        review_service=review_service,
        auto_apply_threshold=(
            settings.discord_memory_auto_apply_threshold
            if review_service is not None
            else None
        ),
    ).process(job_id)
    if outcome.status == "retrying":
        # RQ Retry transports the same deterministic job ID; PostgreSQL owns
        # durable retry state and attempt count.
        raise RuntimeError("Discord memory rule-filter job requested retry")
