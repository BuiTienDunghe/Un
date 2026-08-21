from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config.settings import PROJECT_ROOT, get_settings
from app.llm_clients.ollama_client import OllamaClient
from app.llm_clients.gemini_client import GeminiClient
from app.llm_clients.deepseek_client import DeepSeekClient
from app.routers import agent, auth, bot, chat, conversations, dashboard, discord_sessions, documents, health, memory, memory_review, models, ocr, rag, vision
from app.security.api_key import require_api_key_for_read
from app.security.auth import require_admin
from app.services.auth_service import AuthService
from app.services.postgres_bm25_service import PostgresBm25Service
from app.services.chat_service import ChatService
from app.services.chunk_context_service import ChunkContextService
from app.services.logging_service import LoggingService
from app.services.model_router import ModelRouter
from app.services.postgres_document_service import PostgresDocumentService
from app.services.ocr_job_service import OcrJobService
from app.services.ocr_service import OCRService
from app.services.rag_service import RagService
from app.services.agent_service import AgentService
from app.services.memory_service import MemoryService
from app.services.postgres_retrieval_service import PostgresRetrievalService
from app.services.job_queue_service import JobQueueService
from app.services.operational_service import OperationalService
from app.services.reranker_service import RerankerService
from app.services.bot_control_service import BotControlService
from app.services.discord_session_service import DiscordSessionService
from app.services.discord_memory_review_service import DiscordMemoryReviewService
from app.services.discord_memory_completion_service import (
    DiscordMemoryCompletionService,
)
from app.services.discord_turn_service import DiscordTurnService
from app.stores.qdrant_store import QdrantStore
from app.stores.embedding_cache_store import PostgresEmbeddingCacheStore
from app.stores.postgres_auxiliary_store import PostgresAuxiliaryStore
from app.postgres.database import create_postgres_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # ── Local Ollama client (always initialised) ──────────────────────────
    ollama_client = OllamaClient(
        settings.ollama_base_url,
        settings.ollama_chat_timeout_seconds,
        settings.ollama_health_timeout_seconds,
        settings.ollama_retry_count,
    )

    # ── Cloud LLM client registry ─────────────────────────────────────────
    # Only clients whose API key is present in .env are registered.
    # Add the key to .env then set the matching `provider:` in models.yaml.
    llm_clients: dict = {"ollama": ollama_client}
    if settings.gemini_api_key:
        llm_clients["gemini"] = GeminiClient(
            api_key=settings.gemini_api_key,
            chat_timeout=settings.gemini_chat_timeout_seconds,
            retry_count=settings.gemini_retry_count,
        )
    if settings.deepseek_api_key:
        llm_clients["deepseek"] = DeepSeekClient(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            chat_timeout=settings.deepseek_chat_timeout_seconds,
            retry_count=settings.deepseek_retry_count,
        )

    # Settings validates the mandatory PostgreSQL URL before this point.
    postgres_sessions = create_session_factory(create_postgres_engine(str(settings.database_url)))
    app.state.postgres_sessions = postgres_sessions
    auxiliary_store = PostgresAuxiliaryStore(postgres_sessions)
    logging_service = LoggingService(auxiliary_store, settings.logs_path)
    router = ModelRouter(llm_clients, settings.load_models())
    config = settings.load_config()
    rag_config = config.get("rag", {})
    storage_config = config.get("storage", {})
    qdrant_store = QdrantStore(settings.qdrant_url, settings.qdrant_timeout_seconds, settings.qdrant_memories_collection)
    app.state.auxiliary_store = auxiliary_store
    app.state.ollama_client = ollama_client
    app.state.models = settings.load_models()
    app.state.settings = settings
    app.state.qdrant_store = qdrant_store
    app.state.logging_service = logging_service
    app.state.memory_service = MemoryService(auxiliary_store, qdrant_store, router, logging_service)
    app.state.chat_service = ChatService(auxiliary_store, router, logging_service, settings.conversation_history_limit, app.state.memory_service)
    app.state.discord_session_service = DiscordSessionService(postgres_sessions)
    app.state.memory_review_service = DiscordMemoryReviewService(postgres_sessions, app.state.memory_service)
    app.state.discord_turn_service = DiscordTurnService(
        postgres_sessions,
        app.state.discord_session_service,
        app.state.chat_service,
        memory_completion_service=DiscordMemoryCompletionService(
            enabled=settings.discord_memory_ingestion_enabled,
            extractor_schema_version=(
                settings.discord_memory_extractor_schema_version
            ),
            max_attempts=settings.job_max_attempts,
        ),
        agent_tools_enabled=settings.discord_agent_tools_enabled,
    )
    ocr_service = OCRService(router, auxiliary_store)
    queue = (
        JobQueueService(
            settings.redis_url,
            settings.rq_queue_prefix,
            memory_queue_name=settings.discord_memory_queue_name,
        )
        if settings.ingestion_execution_backend == "rq"
        else None
    )
    chunk_context_service = ChunkContextService.from_config(router, rag_config, enabled_override=settings.rag_contextual_retrieval_enabled)
    app.state.document_service = PostgresDocumentService(
        postgres_sessions, PostgresEmbeddingCacheStore(postgres_sessions), qdrant_store, router, logging_service, settings.documents_path,
        int(rag_config.get("chunk_tokens", rag_config.get("chunk_size", 480))),
        int(rag_config.get("chunk_overlap_tokens", rag_config.get("chunk_overlap", 80))), ocr_service, queue, settings.job_max_attempts,
        chunk_context=chunk_context_service,
    )
    app.state.operational_service = OperationalService(
        postgres_sessions,
        settings.redis_url,
        settings.rq_queue_prefix,
        qdrant_store,
        ollama_client,
        settings.documents_path.parent / "cleanup-worker.heartbeat",
        memory_ingestion_enabled=settings.discord_memory_ingestion_enabled,
        memory_queue_name=settings.discord_memory_queue_name,
        backups_path=settings.postgres_backups_path,
        backup_heartbeat_path=settings.documents_path.parent / "backup-worker.heartbeat",
        backup_max_age_hours=float(storage_config.get("backup_interval_hours", 24)),
    )
    app.state.ocr_job_service = OcrJobService(router, settings.ocr_runs_path, auxiliary_store, ocr_service)
    reranker_service = RerankerService.from_config(rag_config, enabled_override=settings.rag_reranker_enabled)
    # Fail here, on a machine that turned the reranker on without the [rerank]
    # extra, rather than on that machine's first question (P4-3).
    reranker_service.warmup()
    retrieval_service = PostgresRetrievalService(qdrant_store, router, postgres_sessions, PostgresBm25Service(postgres_sessions), reranker_service, str(rag_config.get("retrieval_mode", "hybrid")), int(rag_config.get("rrf_k", 60)))
    app.state.rag_service = RagService(
        router,
        logging_service,
        retrieval_service,
        default_top_k=int(rag_config.get("top_k", 5)),
        max_context_chunks=int(rag_config.get("max_context_chunks", 5)),
        store=auxiliary_store,
        history_limit=settings.conversation_history_limit,
        condense_enabled=bool(rag_config.get("condense_enabled", True)),
    )
    agent_config = config.get("agent", {})
    app.state.agent_service = AgentService(
        router,
        retrieval_service,
        app.state.memory_service,
        app.state.operational_service,
        max_steps=int(agent_config.get("max_steps", 3)),
        tool_result_max_chars=int(agent_config.get("tool_result_max_chars", 1200)),
    )
    # ChatService is built before the retrieval stack the agent needs, so the
    # agent is handed over here instead of through the constructor.
    app.state.chat_service.agent_service = app.state.agent_service
    # P3-2: dashboard start/stop for the compose-managed Discord bot.
    app.state.bot_control_service = BotControlService(PROJECT_ROOT)
    # P3-1: accounts. Constructed even with auth off — /auth/config answers
    # {"enabled": false} and everything else in it 409s.
    app.state.auth_service = AuthService(
        postgres_sessions,
        jwt_secret=settings.local_ai_jwt_secret,
        access_minutes=settings.local_ai_access_token_minutes,
        refresh_days=settings.local_ai_refresh_token_days,
    )
    try:
        yield
    finally:
        pass


app = FastAPI(title="Local AI Core", version=__version__, lifespan=lifespan)
# /health and /models stay public unconditionally: the launcher, the smoke test
# and the Settings dialog all read them before anyone can supply a key.
app.include_router(health.router)
app.include_router(models.router)
# Auth endpoints are public by necessity (login/refresh/config); their admin
# subroutes carry require_admin themselves.
app.include_router(auth.router)
app.include_router(auth.alias_router)
# Write routes carry their own `require_api_key`. This adds the opt-in read
# guard on top, so `LOCAL_AI_PROTECT_READS=true` closes the whole surface.
read_guard = [Depends(require_api_key_for_read)]
# Admin surfaces (P3-1): oversight and operations. `require_admin` is a no-op
# while auth is disabled, so single-user installs keep today's behavior.
admin_guard = [*read_guard, Depends(require_admin)]
app.include_router(agent.router, dependencies=admin_guard)
app.include_router(bot.router, dependencies=admin_guard)
app.include_router(chat.router, dependencies=read_guard)
app.include_router(documents.router, dependencies=read_guard)
app.include_router(ocr.router, dependencies=read_guard)
app.include_router(rag.router, dependencies=read_guard)
app.include_router(memory.router, dependencies=read_guard)
app.include_router(memory_review.router, dependencies=admin_guard)
app.include_router(conversations.router, dependencies=read_guard)
app.include_router(dashboard.router, dependencies=admin_guard)
app.include_router(discord_sessions.router, dependencies=admin_guard)
app.include_router(vision.router, dependencies=read_guard)
app.mount("/ui", StaticFiles(directory=str(Path(__file__).parent / "frontend"), html=True), name="ui")


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, error: HTTPException) -> JSONResponse:
    detail = error.detail if isinstance(error.detail, dict) else {}
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": True,
            "error_code": detail.get("error_code", "HTTP_ERROR"),
            "message": detail.get("message", str(error.detail)),
            "detail": detail.get("detail"),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, error: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": True, "error_code": "INVALID_INPUT", "message": "Request input is invalid", "detail": str(error.errors())})


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": True, "error_code": "INTERNAL_ERROR", "message": "An unexpected server error occurred", "detail": None})
