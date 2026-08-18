from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.llm_clients.ollama_client import OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError
from app.schemas.memory_schema import MemoryCreateRequest, MemoryResponse, MemorySearchRequest, MemorySearchResult, MemoryUpdateRequest
from app.services.memory_service import MemoryNotFoundError
from app.stores.qdrant_store import QdrantUnavailableError

from app.security.api_key import require_api_key

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/add", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_key)])
def add_memory(payload: MemoryCreateRequest, request: Request) -> MemoryResponse:
    try:
        return MemoryResponse(**request.app.state.memory_service.add(payload.content, payload.memory_type, payload.importance))
    except (OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError, QdrantUnavailableError) as error:
        raise _service_error(error) from error


@router.post("/search", response_model=list[MemorySearchResult])
def search_memory(payload: MemorySearchRequest, request: Request) -> list[MemorySearchResult]:
    try:
        return [MemorySearchResult(**item) for item in request.app.state.memory_service.search(payload.query, payload.top_k)]
    except (OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError, QdrantUnavailableError) as error:
        raise _service_error(error) from error


@router.put("/{memory_id}", response_model=MemoryResponse, dependencies=[Depends(require_api_key)])
def update_memory(memory_id: str, payload: MemoryUpdateRequest, request: Request) -> MemoryResponse:
    try:
        return MemoryResponse(**request.app.state.memory_service.update(memory_id, payload.content, payload.memory_type, payload.importance))
    except MemoryNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "MEMORY_NOT_FOUND", "message": f"Memory {error} does not exist"}) from error
    except (OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError, QdrantUnavailableError) as error:
        raise _service_error(error) from error


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_api_key)])
def delete_memory(memory_id: str, request: Request) -> None:
    try:
        request.app.state.memory_service.delete(memory_id)
    except MemoryNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "MEMORY_NOT_FOUND", "message": f"Memory {error} does not exist"}) from error
    except (OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError, QdrantUnavailableError) as error:
        raise _service_error(error) from error


def _service_error(error: Exception) -> HTTPException:
    if isinstance(error, QdrantUnavailableError):
        return HTTPException(status_code=503, detail={"error_code": "QDRANT_UNAVAILABLE", "message": str(error)})
    if isinstance(error, OllamaTimeoutError):
        return HTTPException(status_code=504, detail={"error_code": "MODEL_TIMEOUT", "message": str(error)})
    if isinstance(error, OllamaModelNotLoadedError):
        return HTTPException(status_code=502, detail={"error_code": "MODEL_NOT_LOADED", "message": str(error)})
    return HTTPException(status_code=502, detail={"error_code": "OLLAMA_UNAVAILABLE", "message": str(error)})
