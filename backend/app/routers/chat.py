from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.llm_clients.ollama_client import OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError
from app.schemas.chat_schema import ChatRequest, ChatResponse
from app.services.chat_service import ConversationNotFoundError
from app.utils.sse import sse_event

from app.security.api_key import require_api_key
from app.security.auth import ensure_conversation_access, resolve_identity

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
def chat(payload: ChatRequest, request: Request) -> ChatResponse | StreamingResponse:
    started = perf_counter()
    try:
        identity = resolve_identity(request)
        owner = identity.user_id if identity.is_user else None
        if payload.conversation_id:
            # P3-1: appending to someone else's conversation must 404.
            ensure_conversation_access(request, payload.conversation_id)
        if payload.stream and not payload.use_tools:
            tokens, model_used, conversation_id = request.app.state.chat_service.stream_response(payload.message, payload.conversation_id, payload.use_memory, payload.system_prompt, user_id=owner)

            def events():
                yield sse_event("meta", {"conversation_id": conversation_id, "model_used": model_used})
                try:
                    for token in tokens:
                        yield sse_event("token", {"content": token})
                    yield sse_event("done", {})
                except (OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError) as error:
                    yield sse_event("error", {"error_code": "STREAM_FAILED", "message": str(error)})

            return StreamingResponse(events(), media_type="text/event-stream")
        answer, model_used, conversation_id, latency_ms, agent_steps = request.app.state.chat_service.respond(
            payload.message, payload.conversation_id, payload.use_memory, payload.system_prompt, payload.use_tools, user_id=owner
        )
        if payload.stream:
            # Agent mode has no token stream (the loop runs whole rounds), but
            # SSE clients keep one code path: meta → steps → answer → done.
            def agent_events():
                yield sse_event("meta", {"conversation_id": conversation_id, "model_used": model_used})
                if agent_steps:
                    yield sse_event("steps", {"steps": agent_steps})
                yield sse_event("token", {"content": answer})
                yield sse_event("done", {})

            return StreamingResponse(agent_events(), media_type="text/event-stream")
        return ChatResponse(answer=answer, model_used=model_used, conversation_id=conversation_id, latency_ms=latency_ms, agent_steps=agent_steps)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "CONVERSATION_NOT_FOUND", "message": f"Conversation {error} does not exist"}) from error
    except OllamaModelNotLoadedError as error:
        request.app.state.logging_service.log_request("/chat", None, int((perf_counter() - started) * 1000), "error", "MODEL_NOT_LOADED")
        raise HTTPException(status_code=502, detail={"error_code": "MODEL_NOT_LOADED", "message": str(error)}) from error
    except OllamaTimeoutError as error:
        request.app.state.logging_service.log_request("/chat", None, int((perf_counter() - started) * 1000), "error", "MODEL_TIMEOUT")
        raise HTTPException(status_code=504, detail={"error_code": "MODEL_TIMEOUT", "message": str(error)}) from error
    except OllamaUnavailableError as error:
        request.app.state.logging_service.log_request("/chat", None, int((perf_counter() - started) * 1000), "error", "OLLAMA_UNAVAILABLE")
        raise HTTPException(status_code=502, detail={"error_code": "OLLAMA_UNAVAILABLE", "message": str(error)}) from error
