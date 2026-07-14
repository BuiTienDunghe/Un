from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.parsers.smart_parser import SmartParser
from app.services.logging_service import LoggingService
from app.services.model_router import ModelRouter
from app.stores.qdrant_store import QdrantStore
from app.stores.sqlite_store import SQLiteStore
from app.utils.chunking import chunk_text
from app.utils.file_utils import safe_upload_suffix
from app.utils.text_cleaning import clean_text


class DocumentNotFoundError(Exception):
    pass


class DocumentAlreadyIndexingError(Exception):
    pass


class DocumentService:
    allowed_file_types = {
        ".pdf": {"application/pdf"},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        ".txt": {"text/plain"},
        ".md": {"text/markdown", "text/plain"},
    }

    def __init__(self, store: SQLiteStore, qdrant: QdrantStore, router: ModelRouter, logging_service: LoggingService, documents_path: Path, chunk_size: int, chunk_overlap: int) -> None:
        self.store = store
        self.qdrant = qdrant
        self.router = router
        self.logging_service = logging_service
        self.documents_path = documents_path
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.parser = SmartParser(router)

    async def upload(self, file: UploadFile, max_bytes: int) -> dict[str, str]:
        filename = file.filename or "upload"
        suffix = safe_upload_suffix(filename)
        if suffix not in self.allowed_file_types or file.content_type not in self.allowed_file_types[suffix]:
            raise ValueError("UNSUPPORTED_FILE_TYPE")
        content = await file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise OverflowError("DOCUMENT_TOO_LARGE")
        document_id = f"doc_{uuid4().hex}"
        stored_filename = f"{document_id}{suffix}"
        document_dir = self.documents_path / document_id
        document_dir.mkdir(parents=True, exist_ok=True)
        (document_dir / f"original{suffix}").write_bytes(content)
        self.store.create_document(document_id, filename, stored_filename, file.content_type)
        self.logging_service.log_request("/documents/upload", None, 0, "ok")
        return {"document_id": document_id, "filename": filename, "status": "uploaded"}

    def status(self, document_id: str) -> dict[str, object]:
        document = self.store.get_document(document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        return {
            "document_id": document["id"],
            "filename": document["original_filename"],
            "status": document["status"],
            "chunks_count": document["chunks_count"],
            "ocr_pages_count": document["ocr_pages_count"],
            "error_message": document["error_message"],
        }

    def index(self, document_id: str) -> tuple[int, int, int]:
        document = self.store.get_document(document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        if document["status"] == "indexing":
            raise DocumentAlreadyIndexingError(document_id)
        self.store.update_document_status(document_id, "indexing")
        try:
            stored = str(document["stored_filename"])
            suffix = Path(stored).suffix
            document_dir = self.documents_path / document_id
            file_path = document_dir / f"original{suffix}"
            if not file_path.exists():
                # Backward compat: try old flat layout
                file_path = self.documents_path.parent / "uploads" / stored
            pages = self.parser.parse(file_path)
            chunks: list[tuple[str, int | None, str]] = []
            for page, raw_text, extraction_method in pages:
                chunks.extend((chunk, page, extraction_method) for chunk in chunk_text(clean_text(raw_text), self.chunk_size, self.chunk_overlap))
            if not chunks:
                raise ValueError("Document contains no readable text")
            vectors = [self.router.embed(content)[0] for content, _, _ in chunks]
            self.qdrant.upsert_chunks(document_id, str(document["original_filename"]), chunks, vectors)
            self.store.replace_document_chunks(document_id, chunks)
            ocr_pages_count = sum(1 for _, _, extraction_method in pages if extraction_method == "ocr")
            self.store.update_document_status(document_id, "indexed", chunks_count=len(chunks), ocr_pages_count=ocr_pages_count)
            self.logging_service.log_request("/documents/index", None, 0, "ok")
            return len(chunks), len(vectors), ocr_pages_count
        except Exception as error:
            self.store.update_document_status(document_id, "failed", error_message=str(error))
            self.logging_service.log_request("/documents/index", None, 0, "error", "DOCUMENT_INDEX_FAILED")
            raise
