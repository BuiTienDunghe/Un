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
from app.services.discord_memory_verifier import (
    DiscordMemoryVerifierAdapter,
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
    # Model registry: the extractor and verifier tags come from the resolved
    # pointer (roles.extractor.active, or the DISCORD_MEMORY_*_MODEL ad-hoc pin
    # as source env_tag), never from a Settings default. A role whose tag is
    # absent from Ollama resolves `disabled`, so the worker runs the rule filter
    # only instead of failing every job on a 404. The record is kept on `off`
    # and `disabled`, so the candidate row still names the model. The first job
    # of the process pays the probes; later jobs reuse settings._resolved.
    resolved = settings.resolve_models()
    extractor_role = resolved.roles["extractor"]
    extractor_model = (
        str(extractor_role.record.config["name"]) if extractor_role.record else ""
    )
    extractor_enabled = (
        settings.discord_memory_extractor_enabled and extractor_role.serving
    )
    verifier_role = resolved.roles["verifier"]
    verifier_model = (
        str(verifier_role.record.config["name"]) if verifier_role.record else ""
    )
    verifier_enabled = (
        settings.discord_memory_verifier_enabled
        and settings.discord_memory_extractor_enabled
        and verifier_role.serving
    )
    extractor = (
        DiscordMemoryExtractorAdapter(
            base_url=settings.ollama_base_url,
            model=extractor_model,
            schema_version=settings.discord_memory_extractor_schema_version,
            num_ctx=settings.discord_memory_extractor_num_ctx,
            temperature=settings.discord_memory_extractor_temperature,
            seed=settings.discord_memory_extractor_seed,
            timeout_seconds=settings.discord_memory_extractor_timeout_seconds,
            retry_count=settings.discord_memory_extractor_retry_count,
            json_fallback=settings.discord_memory_extractor_json_fallback,
        )
        if extractor_enabled
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
        # The durable log sink before the router, as in the API (invariant #6).
        logging_service = LoggingService(auxiliary_store, settings.logs_path)
        # One embedding version == one memories collection; the sweep lets a
        # revoked memory be deleted from every registered collection.
        collections = settings.qdrant_collections()
        review_service = DiscordMemoryReviewService(
            sessions,
            MemoryService(
                auxiliary_store,
                QdrantStore(
                    settings.qdrant_url,
                    settings.qdrant_timeout_seconds,
                    collections.memories,
                    memories_sweep=collections.all_memories,
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
                    embedding_refusal=resolved.embedding_refusal(),
                ),
                logging_service,
            ),
        )
    verifier = (
        DiscordMemoryVerifierAdapter(
            base_url=settings.ollama_base_url,
            model=verifier_model,
            timeout_seconds=settings.discord_memory_verifier_timeout_seconds,
        )
        if verifier_enabled
        else None
    )
    outcome = DiscordMemoryWorkerService(
        sessions,
        worker_id=socket.gethostname(),
        lease_seconds=settings.job_stale_timeout_seconds,
        memory_policy_enabled=settings.discord_memory_ingestion_enabled,
        extractor_enabled=extractor_enabled,
        extractor_model=extractor_model,
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
        verifier=verifier,
    ).process(job_id)
    if outcome.status == "retrying":
        # RQ Retry transports the same deterministic job ID; PostgreSQL owns
        # durable retry state and attempt count.
        raise RuntimeError("Discord memory rule-filter job requested retry")
