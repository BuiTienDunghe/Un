from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.llm_clients.ollama_client import OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError
from app.schemas.rag_schema import GroundingReport, RagChatRequest, RagChatResponse, RagSearchRequest, RagSearchResponse, RagSource
from app.services.answer_grounding import grade_rag_answer
from app.services.chat_service import ConversationNotFoundError
from app.services.rag_service import InsufficientContextError
from app.services.reranker_service import RerankerUnavailableError
from app.stores.qdrant_store import QdrantUnavailableError
from app.utils.sse import sse_event

from app.security.api_key import require_api_key, require_api_key_for_read
from app.security.auth import ensure_conversation_access, resolve_identity

router = APIRouter(prefix="/rag", tags=["rag"])


def _response_sources(sources: list[dict[str, object]]) -> list[RagSource]:
    """One mapping for both branches, so stream and non-stream citations can
    never drift apart, and the SSE payload passes RagSource validation too."""
    return [
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


@router.post("/search", response_model=RagSearchResponse, dependencies=[Depends(require_api_key_for_read)])
def rag_search(payload: RagSearchRequest, request: Request) -> RagSearchResponse:
    try:
        document_scope = payload.document_ids or ([payload.document_id] if payload.document_id else None)
        sources, latency_ms = request.app.state.rag_service.search(payload.message, payload.top_k, document_scope)
        return RagSearchResponse(latency_ms=latency_ms, sources=_response_sources(sources))
    except QdrantUnavailableError as error:
        request.app.state.logging_service.log_request("/rag/search", None, 0, "error", "QDRANT_UNAVAILABLE")
        raise HTTPException(status_code=503, detail={"error_code": "QDRANT_UNAVAILABLE", "message": str(error)}) from error
    except OllamaModelNotLoadedError as error:
        # D4-lite #5: these four branches raised without logging, so an Ollama
        # outage produced zero request_logs rows — 142/142 production rows said
        # "ok" not because nothing failed but because failure had no recorder.
        request.app.state.logging_service.log_request("/rag/search", None, 0, "error", "MODEL_NOT_LOADED")
        raise HTTPException(status_code=502, detail={"error_code": "MODEL_NOT_LOADED", "message": str(error)}) from error
    except OllamaTimeoutError as error:
        request.app.state.logging_service.log_request("/rag/search", None, 0, "error", "MODEL_TIMEOUT")
        raise HTTPException(status_code=504, detail={"error_code": "MODEL_TIMEOUT", "message": str(error)}) from error
    except OllamaUnavailableError as error:
        request.app.state.logging_service.log_request("/rag/search", None, 0, "error", "OLLAMA_UNAVAILABLE")
        raise HTTPException(status_code=502, detail={"error_code": "OLLAMA_UNAVAILABLE", "message": str(error)}) from error
    except RerankerUnavailableError as error:
        request.app.state.logging_service.log_request("/rag/search", None, 0, "error", "RERANKER_UNAVAILABLE")
        raise HTTPException(status_code=503, detail={"error_code": "RERANKER_UNAVAILABLE", "message": str(error)}) from error


@router.post("/chat", response_model=RagChatResponse, dependencies=[Depends(require_api_key)])
def rag_chat(payload: RagChatRequest, request: Request) -> RagChatResponse | StreamingResponse:
    try:
        identity = resolve_identity(request)
        owner = identity.user_id if identity.is_user else None
        if payload.conversation_id:
            # P3-1: appending to someone else's conversation must 404.
            ensure_conversation_access(request, payload.conversation_id)
        document_scope = payload.document_ids or ([payload.document_id] if payload.document_id else None)
        if payload.stream:
            tokens, model_used, sources, conversation_id, retrieval_question = request.app.state.rag_service.stream_response(payload.message, payload.top_k, document_scope, payload.conversation_id, user_id=owner)
            response_sources = [source.model_dump() for source in _response_sources(sources)]

            def events():
                yield sse_event("meta", {"model_used": model_used, "conversation_id": conversation_id, "retrieval_question": retrieval_question, "sources": response_sources})
                answer_parts: list[str] = []
                try:
                    for token in tokens:
                        answer_parts.append(token)
                        yield sse_event("token", {"content": token})
                    # D3a: the self-check needs the whole answer, so it rides on
                    # `done` — zero model calls, milliseconds, report only.
                    yield sse_event("done", {"grounding": grade_rag_answer("".join(answer_parts), sources)})
                except (OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError) as error:
                    yield sse_event("error", {"error_code": "STREAM_FAILED", "message": str(error)})

            return StreamingResponse(events(), media_type="text/event-stream")
        answer, model_used, latency_ms, sources, conversation_id, retrieval_question = request.app.state.rag_service.respond(payload.message, payload.top_k, document_scope, payload.conversation_id, user_id=owner)
        return RagChatResponse(answer=answer, model_used=model_used, latency_ms=latency_ms, conversation_id=conversation_id, retrieval_question=retrieval_question, sources=_response_sources(sources), grounding=GroundingReport(**grade_rag_answer(answer, sources)))
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "CONVERSATION_NOT_FOUND", "message": f"Conversation {error} does not exist"}) from error
    except InsufficientContextError as error:
        request.app.state.logging_service.log_request("/rag/chat", None, 0, "error", "INSUFFICIENT_CONTEXT")
        raise HTTPException(status_code=422, detail={"error_code": "INSUFFICIENT_CONTEXT", "message": str(error)}) from error
    except QdrantUnavailableError as error:
        request.app.state.logging_service.log_request("/rag/chat", None, 0, "error", "QDRANT_UNAVAILABLE")
        raise HTTPException(status_code=503, detail={"error_code": "QDRANT_UNAVAILABLE", "message": str(error)}) from error
    except OllamaModelNotLoadedError as error:
        # D4-lite #5: these four branches raised without logging, so an Ollama
        # outage produced zero request_logs rows — 142/142 production rows said
        # "ok" not because nothing failed but because failure had no recorder.
        request.app.state.logging_service.log_request("/rag/chat", None, 0, "error", "MODEL_NOT_LOADED")
        raise HTTPException(status_code=502, detail={"error_code": "MODEL_NOT_LOADED", "message": str(error)}) from error
    except OllamaTimeoutError as error:
        request.app.state.logging_service.log_request("/rag/chat", None, 0, "error", "MODEL_TIMEOUT")
        raise HTTPException(status_code=504, detail={"error_code": "MODEL_TIMEOUT", "message": str(error)}) from error
    except OllamaUnavailableError as error:
        request.app.state.logging_service.log_request("/rag/chat", None, 0, "error", "OLLAMA_UNAVAILABLE")
        raise HTTPException(status_code=502, detail={"error_code": "OLLAMA_UNAVAILABLE", "message": str(error)}) from error
    except RerankerUnavailableError as error:
        request.app.state.logging_service.log_request("/rag/chat", None, 0, "error", "RERANKER_UNAVAILABLE")
        raise HTTPException(status_code=503, detail={"error_code": "RERANKER_UNAVAILABLE", "message": str(error)}) from error
