from time import perf_counter

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.llm_clients.ollama_client import OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError
from app.schemas.code_schema import CodeChatRequest, CodeChatResponse
from app.utils.sse import sse_event

router = APIRouter(prefix="/code", tags=["code"])


@router.post("/chat", response_model=CodeChatResponse)
def code_chat(payload: CodeChatRequest, request: Request) -> CodeChatResponse | StreamingResponse:
    started = perf_counter()
    try:
        if payload.stream:
            tokens, model_used = request.app.state.code_service.stream_response(payload.message, payload.code_context, payload.repo_context)

            def events():
                yield sse_event("meta", {"model_used": model_used})
                try:
                    for token in tokens:
                        yield sse_event("token", {"content": token})
                    yield sse_event("done", {})
                except (OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError) as error:
                    yield sse_event("error", {"error_code": "STREAM_FAILED", "message": str(error)})

            return StreamingResponse(events(), media_type="text/event-stream")
        answer, model_used, latency_ms = request.app.state.code_service.respond(
            payload.message, payload.code_context, payload.repo_context
        )
        return CodeChatResponse(answer=answer, model_used=model_used, latency_ms=latency_ms)
    except OllamaModelNotLoadedError as error:
        request.app.state.logging_service.log_request("/code/chat", None, int((perf_counter() - started) * 1000), "error", "MODEL_NOT_LOADED")
        raise HTTPException(status_code=502, detail={"error_code": "MODEL_NOT_LOADED", "message": str(error)}) from error
    except OllamaTimeoutError as error:
        request.app.state.logging_service.log_request("/code/chat", None, int((perf_counter() - started) * 1000), "error", "MODEL_TIMEOUT")
        raise HTTPException(status_code=504, detail={"error_code": "MODEL_TIMEOUT", "message": str(error)}) from error
    except OllamaUnavailableError as error:
        request.app.state.logging_service.log_request("/code/chat", None, int((perf_counter() - started) * 1000), "error", "OLLAMA_UNAVAILABLE")
        raise HTTPException(status_code=502, detail={"error_code": "OLLAMA_UNAVAILABLE", "message": str(error)}) from error
