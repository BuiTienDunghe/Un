from __future__ import annotations

import hashlib
import shutil
import threading
from datetime import UTC, datetime
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.parsers.smart_parser import SmartParser
from app.postgres.models import Document, DocumentVersion, IngestionRun
from app.postgres.repositories import InvalidStateTransition, PostgresDocumentRepository
from app.services.logging_service import LoggingService
from app.services.model_router import ModelRouter
from app.services.ocr_service import OCRService
from app.stores.embedding_cache_store import EmbeddingCacheIdentity, EmbeddingCacheStore, fingerprint
from app.stores.qdrant_store import QdrantStore
from app.utils.chunking import chunk_pages
from app.utils.file_utils import safe_upload_suffix


class DocumentNotFoundError(Exception):
    pass


class DocumentAlreadyIndexingError(Exception):
    pass


class IngestionNotFoundError(Exception):
    pass


class SourceUnavailableError(Exception):
    pass


class PostgresDocumentService:
    """Phase-2 synchronous runner: metadata is PostgreSQL, long work is outside transactions."""

    allowed_file_types = {".pdf": {"application/pdf"}, ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}, ".txt": {"text/plain"}, ".md": {"text/markdown", "text/plain"}}

    def __init__(self, session_factory: sessionmaker, embedding_cache: EmbeddingCacheStore, qdrant: QdrantStore, router: ModelRouter, logging_service: LoggingService, documents_path: Path, chunk_tokens: int, chunk_overlap_tokens: int, ocr_service: OCRService, job_queue: object | None = None, job_max_attempts: int = 3) -> None:
        self.sessions, self.embedding_cache, self.qdrant, self.router = session_factory, embedding_cache, qdrant, router
        self.logging_service, self.documents_path = logging_service, documents_path
        self.chunk_tokens, self.chunk_overlap_tokens, self.parser = chunk_tokens, chunk_overlap_tokens, SmartParser(ocr_service)
        self._lock = threading.Lock()
        self.job_queue, self.job_max_attempts = job_queue, job_max_attempts

    @staticmethod
    def _document_payload(document: Document, run: IngestionRun | None = None, version: DocumentVersion | None = None) -> dict[str, object]:
        return {"document_id": document.id, "filename": document.original_filename, "status": document.status, "chunks_count": run.total_chunks if run else 0, "ocr_pages_count": run.ocr_pages if run else 0, "content_hash": document.content_hash, "active_index_version": version.version_number if version else 0, "active_version_id": document.active_version_id, "source_available": document.source_available, "source_removed_at": document.source_removed_at.isoformat() if document.source_removed_at else None, "pinned": document.pinned, "retention_policy": document.retention_policy, "last_accessed_at": document.last_accessed_at.isoformat() if document.last_accessed_at else None, "ingestion": PostgresDocumentService._run_payload(run, version) if run else None, "error_message": document.error_message}

    @staticmethod
    def _run_payload(run: IngestionRun, version: DocumentVersion | None = None) -> dict[str, object]:
        return {"id": run.id, "document_id": run.document_id, "version_id": run.version_id, "index_version": version.version_number if version else 0, "status": run.status, "stage": run.current_stage, "current_stage": run.current_stage, "total_pages": run.total_pages, "processed_pages": run.processed_pages, "ocr_pages": run.ocr_pages, "chunks_count": run.total_chunks, "total_chunks": run.total_chunks, "vectors_count": run.embedded_chunks, "embedded_chunks": run.embedded_chunks, "progress_percent": run.progress_percent, "cancel_requested": run.cancel_requested, "error_code": run.error_code, "error_message": run.error_message}

    @staticmethod
    def _normalized_filename(filename: str) -> str:
        # Never permit a client-provided path to become a display identity.
        value = Path(filename).name.strip().casefold()
        if not value:
            raise ValueError("INVALID_FILENAME")
        return value

    @staticmethod
    def _decision(document: Document, digest: str, conflict: str, actions: list[str], suggested_filename: str | None = None) -> dict[str, object]:
        return {"document_id": document.id, "filename": document.original_filename, "status": document.status, "duplicate": True, "content_hash": digest, "action_required": True, "conflict": conflict, "available_actions": actions, "suggested_filename": suggested_filename}

    def _next_display_filename(self, filename: str) -> str:
        path = Path(filename)
        stem, suffix = path.stem, path.suffix
        number = 2
        while True:
            candidate = f"{stem} ({number}){suffix}"
            with self.sessions() as session:
                if not PostgresDocumentRepository(session).find_document_by_display_filename(self._normalized_filename(candidate)):
                    return candidate
            number += 1

    async def upload(self, file: UploadFile, max_bytes: int, decision: str | None = None) -> dict[str, object]:
        filename = Path(file.filename or "upload").name
        suffix = safe_upload_suffix(filename)
        if suffix not in self.allowed_file_types or file.content_type not in self.allowed_file_types[suffix]:
            raise ValueError("UNSUPPORTED_FILE_TYPE")
        content = await file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise OverflowError("DOCUMENT_TOO_LARGE")
        digest = hashlib.sha256(content).hexdigest()
        with self.sessions() as session:
            repository = PostgresDocumentRepository(session)
            named, hashed = repository.find_document_by_display_filename(self._normalized_filename(filename)), repository.find_document_by_hash(digest)

        if decision == "cancel":
            target = named or hashed
            return {"document_id": target.id if target else "", "filename": target.original_filename if target else filename, "status": target.status if target else "cancelled", "duplicate": bool(target), "content_hash": digest, "cancelled": True}

        if named and named.content_hash == digest:
            if decision == "use_existing":
                return {"document_id": named.id, "filename": named.original_filename, "status": named.status, "duplicate": True, "content_hash": digest}
            return self._decision(named, digest, "same_name_same_hash", ["use_existing", "cancel"])

        if not named and hashed:
            if decision == "rename":
                with self.sessions.begin() as session:
                    row = session.get(Document, hashed.id)
                    if not row:
                        raise DocumentNotFoundError(hashed.id)
                    row.original_filename, row.display_filename_normalized = filename, self._normalized_filename(filename)
                return {"document_id": hashed.id, "filename": filename, "status": hashed.status, "duplicate": True, "content_hash": digest, "renamed": True}
            return self._decision(hashed, digest, "new_name_existing_hash", ["rename", "cancel"])

        if named and named.content_hash != digest:
            # A different existing document owns the bytes.  Replacing would
            # violate the one-document-per-SHA invariant, so do not overwrite.
            if hashed and hashed.id != named.id:
                return self._decision(hashed, digest, "content_owned_by_another_document", ["cancel"])
            if decision == "replace":
                return self._replace_content(named.id, filename, suffix, file.content_type, content, digest)
            suggested = self._next_display_filename(filename)
            if decision == "keep_both":
                filename = suggested
            else:
                return self._decision(named, digest, "same_name_different_hash", ["replace", "keep_both", "cancel"], suggested)

        document_id = f"doc_{uuid4().hex}"
        folder = self.documents_path / document_id
        folder.mkdir(parents=True, exist_ok=False)
        source = folder / f"original{suffix}"
        try:
            source.write_bytes(content)
            with self.sessions.begin() as session:
                repository = PostgresDocumentRepository(session)
                if repository.find_document_by_hash(digest) or repository.find_document_by_display_filename(self._normalized_filename(filename)):
                    raise FileExistsError("duplicate upload raced")
                document, version, run = repository.create_upload(document_id, filename, f"{document_id}{suffix}", file.content_type, len(content), digest, self._normalized_filename(filename))
            self.logging_service.log_request("/documents/upload", None, 0, "ok")
            return {"document_id": document.id, "version_id": version.id, "run_id": run.id, "filename": filename, "status": "uploaded", "duplicate": False, "content_hash": digest}
        except FileExistsError:
            shutil.rmtree(folder, ignore_errors=True)
            with self.sessions() as session:
                existing = PostgresDocumentRepository(session).find_document_by_hash(digest)
                if existing:
                    return {"document_id": existing.id, "filename": existing.original_filename, "status": existing.status, "duplicate": True, "content_hash": digest}
            raise

    def _replace_content(self, document_id: str, filename: str, suffix: str, mime_type: str | None, content: bytes, digest: str) -> dict[str, object]:
        """Stage a new source for one document; activation remains version-safe."""
        path = self.documents_path / document_id
        path.mkdir(parents=True, exist_ok=True)
        target = path / f"original{suffix}"
        staged = path / f"original{suffix}.incoming"
        backup = path / f"original{suffix}.previous"
        staged.write_bytes(content)
        database_committed = False
        try:
            if target.exists():
                target.replace(backup)
            staged.replace(target)
            with self.sessions.begin() as session:
                row = session.get(Document, document_id)
                if not row:
                    raise DocumentNotFoundError(document_id)
                if row.content_hash == digest:
                    return {"document_id": row.id, "filename": row.original_filename, "status": row.status, "duplicate": True, "content_hash": digest}
                row.stored_filename, row.mime_type, row.content_hash, row.file_size, row.source_available = f"{document_id}{suffix}", mime_type, digest, len(content), True
            database_committed = True
            run = self.enqueue_index(document_id)
            return {"document_id": document_id, "filename": filename, "status": "processing", "duplicate": False, "content_hash": digest, "version_id": run["version_id"], "run_id": run["id"], "index_version": run["index_version"], "stage": run["stage"]}
        except Exception:
            # Once the row carries the new hash, the new bytes must stay: the
            # database and the disk may never disagree about the source.
            if not database_committed and backup.exists():
                backup.replace(target)
            staged.unlink(missing_ok=True)
            raise
        finally:
            backup.unlink(missing_ok=True)

    def _load(self, document_id: str) -> tuple[Document, IngestionRun | None, DocumentVersion | None]:
        with self.sessions() as session:
            repo = PostgresDocumentRepository(session)
            document = repo.get_document(document_id)
            if not document:
                raise DocumentNotFoundError(document_id)
            if document.status in {"deleting", "deleted"}:
                raise DocumentNotFoundError(document_id)
            run = repo.latest_run(document_id)
            version = session.get(DocumentVersion, document.active_version_id) if document.active_version_id else (session.get(DocumentVersion, run.version_id) if run else None)
            session.expunge_all()
            return document, run, version

    def status(self, document_id: str) -> dict[str, object]:
        document, run, version = self._load(document_id)
        return self._document_payload(document, run, version)

    def list_documents(self) -> list[dict[str, object]]:
        with self.sessions() as session:
            docs = session.scalars(select(Document).where(Document.status != "deleted").order_by(Document.created_at.desc())).all()
            result = []
            for document in docs:
                run = PostgresDocumentRepository(session).latest_run(document.id)
                version = session.get(DocumentVersion, document.active_version_id) if document.active_version_id else (session.get(DocumentVersion, run.version_id) if run else None)
                result.append(self._document_payload(document, run, version))
            return result

    def promote_ocr_run(self, job: dict[str, object]) -> dict[str, object]:
        """Promote completed OCR output without invoking OCR a second time."""
        if job.get("status") != "completed":
            raise ValueError("OCR run is not completed")
        raw_pages = job.get("pages")
        if not isinstance(raw_pages, list) or not raw_pages:
            raise ValueError("OCR run has no pages")
        pages: list[tuple[int | None, str, str]] = []
        for item in raw_pages:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise ValueError("OCR run contains invalid page output")
            pages.append((int(item["page"]) if item.get("page") is not None else None, str(item["text"]), "ocr"))
        content = "\n\n".join(text for _, text, _ in pages).encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        with self.sessions() as session:
            existing = PostgresDocumentRepository(session).find_document_by_hash(digest)
            if existing:
                return {"document_id": existing.id, "duplicate": True, "reused_ocr": True, "ingestion": None}
        document_id = f"doc_{uuid4().hex}"
        folder = self.documents_path / document_id
        folder.mkdir(parents=True, exist_ok=False)
        source = folder / "original.md"
        try:
            source.write_bytes(content)
            with self.sessions.begin() as session:
                repo = PostgresDocumentRepository(session)
                if repo.find_document_by_hash(digest):
                    raise FileExistsError("duplicate OCR promotion raced")
                document, _version, _run = repo.create_upload(document_id, str(job.get("filename") or "ocr-output.md"), f"{document_id}.md", "text/markdown", len(content), digest)
            ingestion = self.enqueue_index(document.id, precomputed_pages=pages)
            return {"document_id": document.id, "duplicate": False, "reused_ocr": True, "ingestion": ingestion}
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def enqueue_index(self, document_id: str, retry_of: str | None = None, precomputed_pages: list[tuple[int | None, str, str]] | None = None) -> dict[str, object]:
        with self.sessions.begin() as session:
            repo = PostgresDocumentRepository(session)
            document = repo.get_document(document_id)
            if not document:
                raise DocumentNotFoundError(document_id)
            if not self._source_path(document).is_file():
                raise SourceUnavailableError(document_id)
            run = repo.latest_run(document_id)
            if run and run.current_stage == "queued":
                version = session.get(DocumentVersion, run.version_id)
            else:
                try:
                    document, version, run = repo.create_reindex(document_id)
                except InvalidStateTransition as error:
                    raise DocumentAlreadyIndexingError(document_id) from error
            document.status = "processing"
            job = repo.create_job("extract_document", document_id, version.id, run.id, self.job_max_attempts) if self.job_queue else None
            session.flush()
            payload = self._run_payload(run, version)
        if job:
            # The job and its outbox event were committed atomically.  The
            # dispatcher is solely responsible for Redis publication.
            payload["job_id"], payload["queue_pending"] = job.id, True
        else:
            threading.Thread(target=self._run_index, args=(payload["id"], document_id, payload["version_id"], precomputed_pages), daemon=True).start()
        return payload

    def get_ingestion(self, run_id: str) -> dict[str, object]:
        with self.sessions() as session:
            run = PostgresDocumentRepository(session).get_run(run_id)
            if not run:
                raise IngestionNotFoundError(run_id)
            version = session.get(DocumentVersion, run.version_id)
            return self._run_payload(run, version)

    def cancel_ingestion(self, run_id: str) -> dict[str, object]:
        with self.sessions.begin() as session:
            repo = PostgresDocumentRepository(session)
            run = repo.get_run(run_id)
            if not run:
                raise IngestionNotFoundError(run_id)
            repo.request_cancel(run_id)
            version = session.get(DocumentVersion, run.version_id)
            return self._run_payload(run, version)

    def retry_ingestion(self, run_id: str) -> dict[str, object]:
        with self.sessions.begin() as session:
            repo = PostgresDocumentRepository(session)
            try:
                run = repo.retry_run(run_id)
            except KeyError as error:
                raise IngestionNotFoundError(run_id) from error
            except InvalidStateTransition as error:
                raise ValueError(str(error)) from error
            version = session.get(DocumentVersion, run.version_id)
            document = session.get(Document, run.document_id)
            if document is not None:
                document.status = "processing"
            job = repo.create_job("extract_document", run.document_id, run.version_id, run.id, self.job_max_attempts) if self.job_queue else None
            session.flush()
            payload = self._run_payload(run, version)
            if job:
                payload["job_id"], payload["queue_pending"] = job.id, True
        if not self.job_queue:
            threading.Thread(target=self._run_index, args=(run_id, str(payload["document_id"]), str(payload["version_id"]), None), daemon=True).start()
        return payload

    async def replace_source(self, document_id: str, file: UploadFile, max_bytes: int) -> dict[str, object]:
        document, _, _ = self._load(document_id)
        filename = Path(file.filename or document.original_filename).name
        suffix = safe_upload_suffix(filename)
        if suffix not in self.allowed_file_types or file.content_type not in self.allowed_file_types[suffix]:
            raise ValueError("UNSUPPORTED_FILE_TYPE")
        content = await file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise OverflowError("DOCUMENT_TOO_LARGE")
        digest = hashlib.sha256(content).hexdigest()
        if digest == document.content_hash:
            return {"duplicate": True, "ingestion": None, "content_hash": digest}
        with self.sessions() as session:
            owner = PostgresDocumentRepository(session).find_document_by_hash(digest)
            if owner and owner.id != document_id:
                raise ValueError("CONTENT_ALREADY_EXISTS")
        result = self._replace_content(document_id, document.original_filename, suffix, file.content_type, content, digest)
        return {"duplicate": False, "ingestion": {"id": result["run_id"], "index_version": result["index_version"], "status": "queued", "stage": result["stage"]}, "content_hash": digest}

    def delete_document(self, document_id: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(Document, document_id)
            if not row: raise DocumentNotFoundError(document_id)
            if row.status == "deleted": return
            row.status, row.deleted_requested_at = "deleting", datetime.now(UTC)
            PostgresDocumentRepository(session).create_document_delete_job(document_id, self.job_max_attempts)

    def remove_source(self, document_id: str) -> None:
        self._load(document_id)
        shutil.rmtree(self.documents_path / document_id, ignore_errors=True)
        with self.sessions.begin() as session:
            row = session.get(Document, document_id)
            if row:
                row.source_available = False

    def set_retention(self, document_id: str, pinned: bool | None, retention_policy: str | None) -> dict[str, object]:
        with self.sessions.begin() as session:
            row = session.get(Document, document_id)
            if not row:
                raise DocumentNotFoundError(document_id)
            if pinned is not None:
                row.pinned = pinned
            if retention_policy is not None:
                row.retention_policy = retention_policy
        return self.status(document_id)

    def _run_index(self, run_id: str, document_id: str, version_id: str, precomputed_pages: list[tuple[int | None, str, str]] | None) -> None:
        with self._lock:
            try:
                with self.sessions.begin() as session:
                    PostgresDocumentRepository(session).set_stage(run_id, "parsing", progress_percent=5)
                    document = session.get(Document, document_id)
                    if not document:
                        return
                    session.expunge(document)
                pages = precomputed_pages if precomputed_pages is not None else self.parser.parse(self._source_path(document), on_stage=lambda stage: self._set_stage(run_id, stage))
                with self.sessions.begin() as session:
                    repo = PostgresDocumentRepository(session)
                    repo.replace_pages(document_id, version_id, pages)
                    repo.set_stage(run_id, "chunking", total_pages=len(pages), processed_pages=len(pages), ocr_pages=sum(1 for _, _, method in pages if method == "ocr"), progress_percent=35)
                chunks = chunk_pages(pages, self.chunk_tokens, self.chunk_overlap_tokens)
                if not chunks:
                    raise ValueError("Document contains no readable text")
                with self.sessions.begin() as session:
                    repo = PostgresDocumentRepository(session)
                    repo.replace_chunks(document_id, version_id, chunks)
                    repo.set_stage(run_id, "embedding", total_chunks=len(chunks), progress_percent=45)
                vectors = []
                model = str(self.router.models["embedding"]["name"])
                for index, chunk in enumerate(chunks, 1):
                    vector = self._embed_with_cache(chunk.content, model)
                    vectors.append(vector)
                    self._set_stage(run_id, "embedding", embedded_chunks=index, progress_percent=45 + int(35 * index / len(chunks)))
                with self.sessions() as session:
                    filename = session.get(Document, document_id).original_filename
                    ids = [row.id for row in PostgresDocumentRepository(session).chunks_for_version(version_id)]
                self._set_stage(run_id, "qdrant_upsert", progress_percent=82)
                self.qdrant.upsert_chunks(document_id, version_id, filename, chunks, vectors, chunk_ids=ids)
                self._set_stage(run_id, "activating", embedded_chunks=len(chunks), progress_percent=95)
                with self.sessions.begin() as session:
                    if self.job_queue is not None:
                        raise RuntimeError("system activation is forbidden when RQ execution is enabled")
                    from loguru import logger
                    logger.warning("Using thread fallback system activation for run {}", run_id)
                    PostgresDocumentRepository(session).activate(run_id, system_context=True)
                self.logging_service.log_request("/documents/index", None, 0, "ok")
            except Exception as error:
                with self.sessions.begin() as session:
                    PostgresDocumentRepository(session).fail_run(run_id, "DOCUMENT_INDEX_FAILED", str(error)[:1000])
                self.logging_service.log_request("/documents/index", None, 0, "error", "DOCUMENT_INDEX_FAILED")

    def extract_for_worker(self, run_id: str, checkpoint: Callable[[], bool] | None = None, long_call: Callable[[], object] | None = None) -> tuple[str, str]:
        """Shared OCR/extraction core used by the independent OCR worker."""
        with self.sessions.begin() as session:
            repo = PostgresDocumentRepository(session)
            run = repo.get_run(run_id)
            if not run:
                raise IngestionNotFoundError(run_id)
            repo.set_stage(run_id, "parsing", progress_percent=5)
            document = session.get(Document, run.document_id)
            version_id, document_id = run.version_id, run.document_id
            session.expunge(document)
        if checkpoint and not checkpoint():
            raise PermissionError("worker lost job ownership before extraction")
        pages = self.parser.parse(self._source_path(document), on_stage=lambda stage: self._set_stage(run_id, stage), checkpoint=checkpoint, long_call=long_call)
        if checkpoint and not checkpoint():
            raise PermissionError("worker lost job ownership after extraction")
        with self.sessions.begin() as session:
            repo = PostgresDocumentRepository(session)
            repo.replace_pages(document_id, version_id, pages)
            repo.set_stage(run_id, "chunking", total_pages=len(pages), processed_pages=len(pages), ocr_pages=sum(1 for _, _, method in pages if method == "ocr"), progress_percent=35)
        return document_id, version_id

    def index_for_worker(self, run_id: str, checkpoint: Callable[[], bool] | None = None, long_call: Callable[[], object] | None = None, job_id: str | None = None, worker_id: str | None = None) -> None:
        """Shared chunk/embed/Qdrant/activation core used by the Index worker."""
        with self.sessions() as session:
            repo = PostgresDocumentRepository(session)
            run = repo.get_run(run_id)
            if not run:
                raise IngestionNotFoundError(run_id)
            document = session.get(Document, run.document_id)
            pages = [(page.page_number, page.selected_text or "", page.extraction_method) for page in repo.pages_for_version(run.version_id)]
            document_id, version_id, filename = run.document_id, run.version_id, document.original_filename
        if checkpoint and not checkpoint(): raise PermissionError("worker lost job ownership before chunking")
        chunks = chunk_pages(pages, self.chunk_tokens, self.chunk_overlap_tokens)
        if not chunks:
            raise ValueError("Document contains no readable text")
        with self.sessions.begin() as session:
            repo = PostgresDocumentRepository(session)
            repo.replace_chunks(document_id, version_id, chunks)
            repo.set_stage(run_id, "embedding", total_chunks=len(chunks), progress_percent=45)
        if checkpoint and not checkpoint(): raise PermissionError("worker lost job ownership after chunks")
        vectors, model = [], str(self.router.models["embedding"]["name"])
        for index, chunk in enumerate(chunks, 1):
            if checkpoint and not checkpoint(): raise PermissionError("worker lost job ownership before embedding")
            vector = self._embed_with_cache(chunk.content, model, long_call)
            vectors.append(vector)
            self._set_stage(run_id, "embedding", embedded_chunks=index, progress_percent=45 + int(35 * index / len(chunks)))
            if checkpoint and not checkpoint(): raise PermissionError("worker lost job ownership after embedding")
        with self.sessions() as session:
            ids = [row.id for row in PostgresDocumentRepository(session).chunks_for_version(version_id)]
        if checkpoint and not checkpoint(): raise PermissionError("worker lost job ownership before qdrant")
        self._set_stage(run_id, "qdrant_upsert", progress_percent=82)
        self.qdrant.upsert_chunks(document_id, version_id, filename, chunks, vectors, chunk_ids=ids)
        if checkpoint and not checkpoint(): raise PermissionError("worker lost job ownership after qdrant")
        self._set_stage(run_id, "activating", embedded_chunks=len(chunks), progress_percent=95)
        if checkpoint and not checkpoint(): raise PermissionError("worker lost job ownership before activation")
        with self.sessions.begin() as session:
            PostgresDocumentRepository(session).activate(run_id, job_id, worker_id)

    def _set_stage(self, run_id: str, stage: str, **values: object) -> None:
        with self.sessions.begin() as session:
            PostgresDocumentRepository(session).set_stage(run_id, stage, **values)

    def _cache_identity(self, content: str, dimensions: int | None) -> EmbeddingCacheIdentity | None:
        """Build identity only from explicitly configured model semantics.

        The current models.yaml declares neither a model revision nor a
        normalization policy.  In that safe state this returns ``None``: the
        worker embeds normally and never persists an ambiguously keyed vector.
        """
        config = self.router.models.get("embedding", {})
        revision = config.get("revision") or config.get("model_revision")
        normalization = config.get("normalization")
        if not revision or normalization is None or not dimensions:
            from loguru import logger
            logger.bind(event="embedding_cache_safe_miss", model=str(config.get("name", "unknown"))).warning(
                "Embedding cache bypassed because revision, normalization, or dimensions are not explicitly configured"
            )
            return None
        config_values = {key: value for key, value in config.items() if key not in {"revision", "model_revision", "normalization"}}
        return EmbeddingCacheIdentity(
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            model_name=str(config["name"]),
            model_revision=str(revision),
            dimensions=int(dimensions),
            config_fingerprint=fingerprint(config_values),
            normalization_fingerprint=fingerprint(normalization),
        )

    def _embed_with_cache(self, content: str, model: str, long_call: Callable[[], object] | None = None) -> list[float]:
        """Use cache only when the full identity is known; model work is session-free."""
        configured_dimensions = self.router.models.get("embedding", {}).get("dimensions")
        identity = self._cache_identity(content, int(configured_dimensions)) if configured_dimensions else None
        if identity is not None:
            try:
                cached = self.embedding_cache.get(identity)
            except Exception as error:
                from loguru import logger
                logger.bind(event="embedding_cache_lookup_failed", error_type=type(error).__name__).warning("Embedding cache lookup failed; embedding will continue")
                cached = None
            if cached is not None:
                return cached
        with (long_call() if long_call else nullcontext()):
            vector, returned_model = self.router.embed(content)
        vector = [float(value) for value in vector]
        identity = self._cache_identity(content, len(vector))
        if identity is not None:
            if returned_model != identity.model_name or model != identity.model_name:
                from loguru import logger
                logger.bind(event="embedding_cache_safe_miss").warning("Embedding cache bypassed because the returned model differs from configured model")
                return vector
            try:
                self.embedding_cache.save(identity, vector)
            except Exception as error:
                from loguru import logger
                logger.bind(event="embedding_cache_save_failed", error_type=type(error).__name__).warning("Embedding cache save failed; indexing will continue")
        return vector

    def cancellation_requested(self, run_id: str) -> bool:
        with self.sessions() as session:
            return PostgresDocumentRepository(session).cancellation_requested(run_id)

    def mark_cancelled(self, run_id: str) -> None:
        with self.sessions.begin() as session:
            repo = PostgresDocumentRepository(session)
            run = repo.get_run(run_id)
            if run and run.current_stage not in {"completed", "failed", "cancelled"}:
                repo.set_stage(run_id, "cancelled", error_code="CANCELLED", error_message="Cancelled at worker checkpoint")

    def _source_path(self, document: Document) -> Path:
        return self.documents_path / document.id / f"original{Path(document.stored_filename).suffix}"
