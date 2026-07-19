from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.schemas.document_schema import DocumentStatusResponse, IndexRequest, IndexResponse, IngestionStatusResponse, ReplaceSourceResponse, RetentionRequest, UploadResponse
from app.services.postgres_document_service import DocumentAlreadyIndexingError, DocumentNotFoundError, IngestionNotFoundError, SourceUnavailableError
from app.stores.qdrant_store import QdrantDimensionMismatchError

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentStatusResponse])
def list_documents(request: Request) -> list[DocumentStatusResponse]:
    return [DocumentStatusResponse(**document) for document in request.app.state.document_service.list_documents()]


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_document(request: Request, file: UploadFile = File(...), decision: str | None = Form(default=None)) -> UploadResponse:
    try:
        result = await request.app.state.document_service.upload(file, request.app.state.settings.max_upload_size_bytes, decision=decision)
        return UploadResponse(**result)
    except ValueError as error:
        raise HTTPException(status_code=415, detail={"error_code": "UNSUPPORTED_FILE_TYPE", "message": "Only PDF, DOCX, TXT, and MD files are supported"}) from error
    except OverflowError as error:
        raise HTTPException(status_code=413, detail={"error_code": "DOCUMENT_TOO_LARGE", "message": "The uploaded file exceeds the configured size limit"}) from error


@router.post("/{document_id}/replace", response_model=ReplaceSourceResponse, status_code=202)
async def replace_document_source(document_id: str, request: Request, file: UploadFile = File(...)) -> ReplaceSourceResponse:
    try:
        result = await request.app.state.document_service.replace_source(document_id, file, request.app.state.settings.max_upload_size_bytes)
        run = result["ingestion"]
        return ReplaceSourceResponse(document_id=document_id, duplicate=bool(result["duplicate"]), content_hash=str(result["content_hash"]), ingestion_run_id=str(run["id"]) if run else None, index_version=int(run["index_version"]) if run else None, status=str(run["status"]) if run else None, stage=str(run["stage"]) if run else None)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "DOCUMENT_NOT_FOUND", "message": f"Document {error} does not exist"}) from error
    except DocumentAlreadyIndexingError as error:
        raise HTTPException(status_code=409, detail={"error_code": "DOCUMENT_ALREADY_INDEXING", "message": f"Document {error} is already indexing"}) from error
    except SourceUnavailableError as error:
        raise HTTPException(status_code=409, detail={"error_code": "SOURCE_UNAVAILABLE", "message": f"Document {error} has no original source file; upload a replacement before reindexing"}) from error
    except ValueError as error:
        raise HTTPException(status_code=415, detail={"error_code": "UNSUPPORTED_FILE_TYPE", "message": str(error)}) from error
    except OverflowError as error:
        raise HTTPException(status_code=413, detail={"error_code": "DOCUMENT_TOO_LARGE", "message": "The uploaded file exceeds the configured size limit"}) from error


@router.post("/index", response_model=IndexResponse, status_code=202)
def index_document(payload: IndexRequest, request: Request) -> IndexResponse:
    try:
        run = request.app.state.document_service.enqueue_index(payload.document_id)
        return IndexResponse(document_id=payload.document_id, ingestion_run_id=str(run["id"]), index_version=int(run["index_version"]), version_id=str(run.get("version_id")) if run.get("version_id") else None, job_id=str(run.get("job_id")) if run.get("job_id") else None, status=str(run["status"]), stage=str(run["stage"]))
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "DOCUMENT_NOT_FOUND", "message": f"Document {error} does not exist"}) from error
    except DocumentAlreadyIndexingError as error:
        raise HTTPException(status_code=409, detail={"error_code": "DOCUMENT_ALREADY_INDEXING", "message": f"Document {error} is already indexing"}) from error
    except SourceUnavailableError as error:
        raise HTTPException(status_code=409, detail={"error_code": "SOURCE_UNAVAILABLE", "message": f"Document {error} has no original source file; upload a replacement before reindexing"}) from error
    except QdrantDimensionMismatchError as error:
        raise HTTPException(status_code=422, detail={"error_code": "VECTOR_DIMENSION_MISMATCH", "message": str(error)}) from error
    except Exception as error:
        raise HTTPException(status_code=422, detail={"error_code": "DOCUMENT_PARSE_FAILED", "message": str(error)}) from error


@router.get("/ingestions/{run_id}", response_model=IngestionStatusResponse)
def ingestion_status(run_id: str, request: Request) -> IngestionStatusResponse:
    try:
        return IngestionStatusResponse(**request.app.state.document_service.get_ingestion(run_id))
    except IngestionNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "INGESTION_NOT_FOUND", "message": f"Ingestion {error} does not exist"}) from error


@router.post("/ingestions/{run_id}/cancel", response_model=IngestionStatusResponse)
def cancel_ingestion(run_id: str, request: Request) -> IngestionStatusResponse:
    try:
        return IngestionStatusResponse(**request.app.state.document_service.cancel_ingestion(run_id))
    except IngestionNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "INGESTION_NOT_FOUND", "message": f"Ingestion {error} does not exist"}) from error


@router.post("/ingestions/{run_id}/retry", response_model=IndexResponse, status_code=202)
def retry_ingestion(run_id: str, request: Request) -> IndexResponse:
    try:
        run = request.app.state.document_service.retry_ingestion(run_id)
        return IndexResponse(document_id=str(run["document_id"]), ingestion_run_id=str(run["id"]), index_version=int(run["index_version"]), version_id=str(run.get("version_id")) if run.get("version_id") else None, status=str(run["status"]), stage=str(run["stage"]))
    except IngestionNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "INGESTION_NOT_FOUND", "message": f"Ingestion {error} does not exist"}) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail={"error_code": "INGESTION_NOT_RETRYABLE", "message": str(error)}) from error


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, request: Request) -> None:
    try:
        request.app.state.document_service.delete_document(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "DOCUMENT_NOT_FOUND", "message": f"Document {error} does not exist"}) from error


@router.delete("/{document_id}/source", status_code=204)
def remove_document_source(document_id: str, request: Request) -> None:
    """Remove only the original artifact; indexed knowledge remains available."""
    try:
        request.app.state.document_service.remove_source(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "DOCUMENT_NOT_FOUND", "message": f"Document {error} does not exist"}) from error
    except DocumentAlreadyIndexingError as error:
        raise HTTPException(status_code=409, detail={"error_code": "DOCUMENT_ALREADY_INDEXING", "message": f"Document {error} is already indexing"}) from error


@router.patch("/{document_id}/retention", response_model=DocumentStatusResponse)
def set_document_retention(document_id: str, payload: RetentionRequest, request: Request) -> DocumentStatusResponse:
    try:
        return DocumentStatusResponse(**request.app.state.document_service.set_retention(document_id, payload.pinned, payload.retention_policy))
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "DOCUMENT_NOT_FOUND", "message": f"Document {error} does not exist"}) from error


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
def document_status(document_id: str, request: Request) -> DocumentStatusResponse:
    try:
        return DocumentStatusResponse(**request.app.state.document_service.status(document_id))
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "DOCUMENT_NOT_FOUND", "message": f"Document {error} does not exist"}) from error
