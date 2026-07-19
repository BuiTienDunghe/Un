from time import perf_counter

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.llm_clients.ollama_client import OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError
from app.schemas.chat_schema import ChatRequest, ChatResponse
from app.services.chat_service import ConversationNotFoundError
from app.utils.sse import sse_event

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request) -> ChatResponse | StreamingResponse:
    started = perf_counter()
    try:
        if payload.stream:
            tokens, model_used, conversation_id = request.app.state.chat_service.stream_response(payload.message, payload.conversation_id, payload.use_memory, payload.system_prompt)

            def events():
                yield sse_event("meta", {"conversation_id": conversation_id, "model_used": model_used})
                try:
                    for token in tokens:
                        yield sse_event("token", {"content": token})
                    yield sse_event("done", {})
                except (OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError) as error:
                    yield sse_event("error", {"error_code": "STREAM_FAILED", "message": str(error)})

            return StreamingResponse(events(), media_type="text/event-stream")
        answer, model_used, conversation_id, latency_ms = request.app.state.chat_service.respond(
            payload.message, payload.conversation_id, payload.use_memory, payload.system_prompt
        )
        return ChatResponse(answer=answer, model_used=model_used, conversation_id=conversation_id, latency_ms=latency_ms)
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
