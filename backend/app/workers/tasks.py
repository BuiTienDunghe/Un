from __future__ import annotations

import socket
import threading
from time import perf_counter
from contextlib import contextmanager

from loguru import logger

from app.config.settings import get_settings
from app.llm_clients.ollama_client import OllamaClient
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.repositories import PostgresDocumentRepository
from app.services.chunk_context_service import ChunkContextService
from app.services.job_queue_service import JobQueueService
from app.services.logging_service import LoggingService
from app.services.model_router import ModelRouter
from app.services.ocr_service import OCRService
from app.services.postgres_document_service import PostgresDocumentService
from app.stores.embedding_cache_store import PostgresEmbeddingCacheStore
from app.stores.qdrant_store import QdrantStore
from app.stores.postgres_auxiliary_store import PostgresAuxiliaryStore
from app.services.job_errors import classify_error, retry_delay


def _checkpoint(sessions, job_id: str, worker_id: str, run_id: str) -> bool:
    settings = get_settings()
    with sessions.begin() as session:
        repo = PostgresDocumentRepository(session)
        return not repo.cancellation_requested(run_id) and repo.heartbeat(job_id, worker_id, settings.job_stale_timeout_seconds) and repo.worker_owns_job(job_id, worker_id)


@contextmanager
def _heartbeat_timer(sessions, job_id: str, worker_id: str, run_id: str):
    """Own session per tick; the caller checks lost ownership after the long call."""
    stop, lost = threading.Event(), threading.Event()
    interval = max(1, get_settings().job_stale_timeout_seconds // 3)
    def beat() -> None:
        while not stop.wait(interval):
            if not _checkpoint(sessions, job_id, worker_id, run_id):
                lost.set(); return
    thread = threading.Thread(target=beat, daemon=True); thread.start()
    try:
        yield
    finally:
        stop.set(); thread.join(timeout=interval + 1)
    if lost.is_set():
        raise PermissionError("worker lost ownership during long dependency call")


def _handle_error(sessions, queue, job_id: str, run_id: str, job_type: str, error: Exception) -> bool:
    retryable, code = classify_error(error)
    with sessions.begin() as session:
        repo = PostgresDocumentRepository(session); job = repo.get_job(job_id)
        retry = bool(job and retryable and job.attempts < job.max_attempts and not repo.cancellation_requested(run_id))
        if retry:
            delay = retry_delay(job.attempts); repo.retry_job(job_id, code, str(error)[:1000], delay)
        else:
            repo.fail_job(job_id, code, str(error)[:1000]); repo.fail_run(run_id, code, str(error)[:1000])
    # The currently executing RQ delivery cannot be safely re-enqueued with
    # the same deterministic job ID.  Returning True lets its configured RQ
    # Retry schedule the transport retry after this task fails; PostgreSQL has
    # already persisted retrying/available_at above.
    return retry


def _service() -> tuple[PostgresDocumentService, object, JobQueueService]:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for RQ workers")
    router = ModelRouter(OllamaClient(settings.ollama_base_url, settings.ollama_chat_timeout_seconds, settings.ollama_health_timeout_seconds, settings.ollama_retry_count), settings.load_models())
    sessions = create_session_factory(create_postgres_engine(settings.database_url))
    # Workers use PostgreSQL for document state, auxiliary domains, and the
    # embedding cache.  SQLite remains isolated to the cleanup process.
    auxiliary_store = PostgresAuxiliaryStore(sessions)
    rag_config = settings.load_config().get("rag", {})
    chunk_context = ChunkContextService.from_config(router, rag_config, enabled_override=settings.rag_contextual_retrieval_enabled)
    service = PostgresDocumentService(sessions, PostgresEmbeddingCacheStore(sessions), QdrantStore(settings.qdrant_url, settings.qdrant_timeout_seconds, documents_collection=settings.qdrant_documents_collection), router, LoggingService(auxiliary_store, settings.logs_path), settings.documents_path, int(rag_config.get("chunk_tokens", 480)), int(rag_config.get("chunk_overlap_tokens", 80)), OCRService(router, auxiliary_store), chunk_context=chunk_context)
    return (
        service,
        sessions,
        JobQueueService(
            settings.redis_url,
            settings.rq_queue_prefix,
            memory_queue_name=settings.discord_memory_queue_name,
        ),
    )


def extract_document(job_id: str) -> None:
    service, sessions, queue = _service()
    with sessions.begin() as session:
        repo = PostgresDocumentRepository(session); job = repo.start_job(job_id, socket.gethostname(), get_settings().job_stale_timeout_seconds)
        if not job: return
        run_id = job.ingestion_run_id
    try:
        started = perf_counter()
        worker_id = socket.gethostname()
        if not _checkpoint(sessions, job_id, worker_id, str(run_id)):
            service.mark_cancelled(str(run_id)); return
        document_id, version_id = service.extract_for_worker(str(run_id), lambda: _checkpoint(sessions, job_id, worker_id, str(run_id)), lambda: _heartbeat_timer(sessions, job_id, worker_id, str(run_id)))
        logger.bind(event="ocr_processing", job_id=job_id, run_id=run_id, duration_ms=round((perf_counter()-started)*1000, 1)).info("OCR/extraction completed")
        if not _checkpoint(sessions, job_id, worker_id, str(run_id)):
            service.mark_cancelled(str(run_id)); return
        with sessions.begin() as session:
            repo = PostgresDocumentRepository(session); index = repo.create_job("index_document", document_id, version_id, str(run_id), get_settings().job_max_attempts)
            # ``Job.id`` is a SQLAlchemy default assigned on flush.  The ID is
            # also the deterministic RQ delivery ID, so it must exist before
            # the transaction commits and the enqueue occurs.
            session.flush()
            if not repo.complete_owned_job(job_id, worker_id):
                raise PermissionError("worker lost ownership before completing extraction job")
            index_id = index.id
        logger.info("created index job {} with durable outbox event", index_id)
    except Exception as error:
        with sessions.begin() as session:
            repo = PostgresDocumentRepository(session)
            cancelled = repo.cancellation_requested(str(run_id))
            if cancelled:
                repo.cancel_job(job_id)
        if cancelled:
            service.mark_cancelled(str(run_id))
            return
        if _handle_error(sessions, queue, job_id, str(run_id), "extract_document", error):
            raise


def index_document(job_id: str) -> None:
    service, sessions, queue = _service()
    with sessions.begin() as session:
        repo = PostgresDocumentRepository(session); job = repo.start_job(job_id, socket.gethostname(), get_settings().job_stale_timeout_seconds)
        if not job: return
        run_id = job.ingestion_run_id
    try:
        started = perf_counter()
        worker_id = socket.gethostname()
        if not _checkpoint(sessions, job_id, worker_id, str(run_id)):
            service.mark_cancelled(str(run_id)); return
        service.index_for_worker(str(run_id), lambda: _checkpoint(sessions, job_id, worker_id, str(run_id)), lambda: _heartbeat_timer(sessions, job_id, worker_id, str(run_id)), job_id, worker_id)
        logger.bind(event="embedding_indexing", job_id=job_id, run_id=run_id, duration_ms=round((perf_counter()-started)*1000, 1)).info("Embedding/indexing completed")
        if not _checkpoint(sessions, job_id, worker_id, str(run_id)):
            service.mark_cancelled(str(run_id)); return
        with sessions.begin() as session:
            if not PostgresDocumentRepository(session).complete_owned_job(job_id, worker_id):
                raise PermissionError("worker lost ownership before completing index job")
    except Exception as error:
        with sessions.begin() as session:
            repo = PostgresDocumentRepository(session)
            cancelled = repo.cancellation_requested(str(run_id))
            if cancelled:
                repo.cancel_job(job_id)
        if cancelled:
            service.mark_cancelled(str(run_id))
            return
        if _handle_error(sessions, queue, job_id, str(run_id), "index_document", error):
            raise
