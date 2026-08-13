from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.llm_clients.ollama_client import OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError
from app.schemas.rag_schema import RagChatRequest, RagChatResponse, RagSource
from app.services.rag_service import InsufficientContextError
from app.services.reranker_service import RerankerUnavailableError
from app.stores.qdrant_store import QdrantUnavailableError
from app.utils.sse import sse_event

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/chat", response_model=RagChatResponse)
def rag_chat(payload: RagChatRequest, request: Request) -> RagChatResponse | StreamingResponse:
    try:
        document_scope = payload.document_ids or ([payload.document_id] if payload.document_id else None)
        if payload.stream:
            tokens, model_used, sources = request.app.state.rag_service.stream_response(payload.message, payload.top_k, document_scope)
            response_sources = [
                {"document_id": str(source["document_id"]), "filename": str(source["filename"]), "chunk_id": str(source.get("chunk_id", source.get("chunk_index", ""))), "chunk_index": int(source.get("chunk_index", 0)), "index_version": int(source.get("index_version", 0)), "page": source.get("page"), "page_start": source.get("page_start"), "page_end": source.get("page_end"), "locations": source.get("locations", []), "heading_path": source.get("heading_path"), "section_title": source.get("section_title"), "block_type": str(source.get("block_type", "paragraph")), "source_available": bool(source.get("source_available", False)), "verifiable": bool(source.get("verifiable", False)), "score": float(source["score"]), "excerpt": str(source["content"])[:300], "content": str(source["content"]), "extraction_method": str(source.get("extraction_method", "native"))}
                for source in sources
            ]

            def events():
                yield sse_event("meta", {"model_used": model_used, "sources": response_sources})
                try:
                    for token in tokens:
                        yield sse_event("token", {"content": token})
                    yield sse_event("done", {})
                except (OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError) as error:
                    yield sse_event("error", {"error_code": "STREAM_FAILED", "message": str(error)})

            return StreamingResponse(events(), media_type="text/event-stream")
        answer, model_used, latency_ms, sources = request.app.state.rag_service.respond(payload.message, payload.top_k, document_scope)
        response_sources = [
            RagSource(
                document_id=str(source["document_id"]),
                filename=str(source["filename"]),
                chunk_id=str(source.get("chunk_id", source.get("chunk_index", ""))),
                chunk_index=int(source.get("chunk_index", 0)),
                index_version=int(source.get("index_version", 0)),
                page=source.get("page"),
                page_start=source.get("page_start"),
                page_end=source.get("page_end"),
                locations=source.get("locations", []),
                heading_path=source.get("heading_path"),
                section_title=source.get("section_title"),
                block_type=str(source.get("block_type", "paragraph")),
                source_available=bool(source.get("source_available", False)),
                verifiable=bool(source.get("verifiable", False)),
                score=float(source["score"]),
                excerpt=str(source["content"])[:300],
                content=str(source["content"]),
                extraction_method=str(source.get("extraction_method", "native")),
            )
            for source in sources
        ]
        return RagChatResponse(answer=answer, model_used=model_used, latency_ms=latency_ms, sources=response_sources)
    except InsufficientContextError as error:
        request.app.state.logging_service.log_request("/rag/chat", None, 0, "error", "INSUFFICIENT_CONTEXT")
        raise HTTPException(status_code=422, detail={"error_code": "INSUFFICIENT_CONTEXT", "message": str(error)}) from error
    except QdrantUnavailableError as error:
        request.app.state.logging_service.log_request("/rag/chat", None, 0, "error", "QDRANT_UNAVAILABLE")
        raise HTTPException(status_code=503, detail={"error_code": "QDRANT_UNAVAILABLE", "message": str(error)}) from error
    except OllamaModelNotLoadedError as error:
        raise HTTPException(status_code=502, detail={"error_code": "MODEL_NOT_LOADED", "message": str(error)}) from error
    except OllamaTimeoutError as error:
        raise HTTPException(status_code=504, detail={"error_code": "MODEL_TIMEOUT", "message": str(error)}) from error
    except OllamaUnavailableError as error:
        raise HTTPException(status_code=502, detail={"error_code": "OLLAMA_UNAVAILABLE", "message": str(error)}) from error
    except RerankerUnavailableError as error:
        raise HTTPException(status_code=503, detail={"error_code": "RERANKER_UNAVAILABLE", "message": str(error)}) from error
