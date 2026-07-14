from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config.settings import get_settings
from app.llm_clients.ollama_client import OllamaClient
from app.routers import chat, code, conversations, documents, health, memory, models, ocr, rag, vision
from app.services.bm25_service import Bm25Service
from app.services.chat_service import ChatService
from app.services.cleanup_service import CleanupService
from app.services.code_service import CodeService
from app.services.logging_service import LoggingService
from app.services.model_router import ModelRouter
from app.services.document_service import DocumentService
from app.services.ocr_job_service import OcrJobService
from app.services.rag_service import RagService
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService
from app.services.reranker_service import RerankerService
from app.stores.qdrant_store import QdrantStore
from app.stores.sqlite_store import SQLiteStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = SQLiteStore(settings.database_path)
    store.initialize()
    ollama_client = OllamaClient(settings.ollama_base_url, settings.ollama_chat_timeout_seconds, settings.ollama_health_timeout_seconds, settings.ollama_retry_count)
    logging_service = LoggingService(store, settings.logs_path)
    router = ModelRouter(ollama_client, settings.load_models())
    config = settings.load_config()
    rag_config = config.get("rag", {})
    storage_config = config.get("storage", {})
    qdrant_store = QdrantStore(settings.qdrant_url, settings.qdrant_timeout_seconds)
    # --- Cleanup on startup ---
    cleanup = CleanupService(store, settings.documents_path, settings.ocr_runs_path)
    cleanup.run_all(
        documents_ttl_days=int(storage_config.get("documents_ttl_days", 30)),
        ocr_runs_ttl_days=int(storage_config.get("ocr_runs_ttl_days", 14)),
        logs_ttl_days=int(storage_config.get("logs_ttl_days", 7)),
    )
    app.state.store = store
    app.state.ollama_client = ollama_client
    app.state.models = settings.load_models()
    app.state.settings = settings
    app.state.qdrant_store = qdrant_store
    app.state.logging_service = logging_service
    app.state.memory_service = MemoryService(store, qdrant_store, router, logging_service)
    app.state.chat_service = ChatService(store, router, logging_service, settings.conversation_history_limit, app.state.memory_service)
    app.state.code_service = CodeService(router, logging_service)
    app.state.document_service = DocumentService(store, qdrant_store, router, logging_service, settings.documents_path, int(rag_config.get("chunk_size", 900)), int(rag_config.get("chunk_overlap", 150)))
    app.state.ocr_job_service = OcrJobService(router, settings.ocr_runs_path, store)
    bm25_service = Bm25Service(store)
    reranker_config = rag_config.get("reranker", {})
    reranker_service = RerankerService(bool(reranker_config.get("enabled", False)), str(reranker_config.get("model", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")), int(reranker_config.get("candidate_limit", 15)))
    retrieval_service = RetrievalService(qdrant_store, router, bm25_service, reranker_service, store, str(rag_config.get("retrieval_mode", "hybrid")), int(rag_config.get("rrf_k", 60)))
    app.state.rag_service = RagService(router, logging_service, retrieval_service)
    yield


app = FastAPI(title="Local AI Core", version="1C", lifespan=lifespan)
app.include_router(health.router)
app.include_router(models.router)
app.include_router(chat.router)
app.include_router(code.router)
app.include_router(documents.router)
app.include_router(ocr.router)
app.include_router(rag.router)
app.include_router(memory.router)
app.include_router(conversations.router)
app.include_router(vision.router)
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
