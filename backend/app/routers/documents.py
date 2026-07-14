from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from app.schemas.document_schema import DocumentStatusResponse, IndexRequest, IndexResponse, UploadResponse
from app.services.document_service import DocumentAlreadyIndexingError, DocumentNotFoundError
from app.stores.qdrant_store import QdrantDimensionMismatchError

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_document(request: Request, file: UploadFile = File(...)) -> UploadResponse:
    try:
        result = await request.app.state.document_service.upload(file, request.app.state.settings.max_upload_size_bytes)
        return UploadResponse(**result)
    except ValueError as error:
        raise HTTPException(status_code=415, detail={"error_code": "UNSUPPORTED_FILE_TYPE", "message": "Only PDF, DOCX, TXT, and MD files are supported"}) from error
    except OverflowError as error:
        raise HTTPException(status_code=413, detail={"error_code": "DOCUMENT_TOO_LARGE", "message": "The uploaded file exceeds the configured size limit"}) from error


@router.post("/index", response_model=IndexResponse)
def index_document(payload: IndexRequest, request: Request) -> IndexResponse:
    try:
        chunks, vectors, ocr_pages_count = request.app.state.document_service.index(payload.document_id)
        return IndexResponse(document_id=payload.document_id, chunks_created=chunks, vectors_created=vectors, status="indexed", ocr_pages_count=ocr_pages_count)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "DOCUMENT_NOT_FOUND", "message": f"Document {error} does not exist"}) from error
    except DocumentAlreadyIndexingError as error:
        raise HTTPException(status_code=409, detail={"error_code": "DOCUMENT_ALREADY_INDEXING", "message": f"Document {error} is already indexing"}) from error
    except QdrantDimensionMismatchError as error:
        raise HTTPException(status_code=422, detail={"error_code": "VECTOR_DIMENSION_MISMATCH", "message": str(error)}) from error
    except Exception as error:
        raise HTTPException(status_code=422, detail={"error_code": "DOCUMENT_PARSE_FAILED", "message": str(error)}) from error


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
def document_status(document_id: str, request: Request) -> DocumentStatusResponse:
    try:
        return DocumentStatusResponse(**request.app.state.document_service.status(document_id))
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "DOCUMENT_NOT_FOUND", "message": f"Document {error} does not exist"}) from error
