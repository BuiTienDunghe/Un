import contextvars
import ipaddress
import logging
import queue
import threading
from collections.abc import Callable
from time import perf_counter
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.llm_clients.ollama_client import OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError
from app.schemas.chat_schema import ChatRequest, ChatResponse
from app.services.chat_service import ConversationNotFoundError
from app.services.pastes import PASTE_MAX, PASTE_THRESHOLD
from app.utils.sse import sse_event

from app.security.api_key import require_api_key
from app.security.auth import auth_enabled, ensure_conversation_access, resolve_identity

router = APIRouter(tags=["chat"])
# local_files.LOCAL_FILES_KEY, spelled here so this module does not import the file tools.
LOCAL_FILES_KEY = "local_files"


LOCAL_HOST_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_loopback(host: str | None) -> bool:
    try:
        return host is not None and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _host_name(netloc: str | None) -> str | None:
    try:
        return urlsplit(f"//{netloc}").hostname if netloc else None
    except ValueError:  # "[::1" and the like: not a name, so not this machine
        return None


def _from_this_machine(request: Request) -> bool:
    """The connection comes from this machine, and the page asked for this machine by name. A connection
    from 127.0.0.1 alone is not enough: a foreign page whose name was rebound to 127.0.0.1 (DNS
    rebinding) connects from here too, but its Host and Origin still carry the foreign name."""
    if not _is_loopback(request.client.host if request.client else None):
        return False
    if _host_name(request.headers.get("host")) not in LOCAL_HOST_NAMES:
        return False
    origin = request.headers.get("origin")
    return origin is None or _host_name(urlsplit(origin).netloc) in LOCAL_HOST_NAMES


def local_files_context(request: Request) -> dict[str, object] | None:
    """The tool context that lets this turn see the tools for files on this machine (local_files.py), or
    None. Only for the machine's owner: with accounts on, an admin or the API key; with accounts off
    (the API trusts whoever reaches it, and the LAN guide shares one API key), only a caller on this
    machine itself, key or not. Nothing is set unless AGENT_LOCAL_FILES_ENABLED is on, so with it off
    every turn is exactly as before.

    The Discord bot also calls /chat (for /ask) with the API key from this machine; it is not marked
    only because it never sends use_tools, and the route marks agent turns alone."""
    settings = getattr(request.app.state, "settings", None)
    if not getattr(settings, "agent_local_files_enabled", False):
        return None
    if auth_enabled(request):
        identity = resolve_identity(request)
        allowed = identity.is_service or (identity.is_user and identity.role == "admin")
    else:
        allowed = _from_this_machine(request)
    return {LOCAL_FILES_KEY: True} if allowed else None


def _marked(tool_context: dict[str, object] | None) -> dict[str, object]:
    """The keyword for chat_service.respond, only when there is a mark: with the file tools off the
    call stays exactly as before."""
    return {"tool_context": tool_context} if tool_context else {}
_LOG = logging.getLogger(__name__)
_TURN_DONE = object()


def start_in_request_context(work: Callable[[], None]) -> threading.Thread:
    """Run `work` on a new thread inside a copy of the caller's context. A new thread starts
    with an empty context, and the turn's deadline (llm_clients/deadline.py) and token counts
    (llm_clients/usage.py) are ContextVars; the copy keeps whatever the request set, and the
    agent sets its own deadline inside it."""
    thread = threading.Thread(target=contextvars.copy_context().run, args=(work,), daemon=True, name="agent-turn")
    thread.start()
    return thread


def _stream_failure(request: Request, error: Exception, started: float) -> dict[str, str]:
    """A turn that failed after its stream began: the codes the JSON path answers with."""
    if isinstance(error, ConversationNotFoundError):
        return {"error_code": "CONVERSATION_NOT_FOUND", "message": f"Conversation {error} does not exist"}
    for kind, code in ((OllamaModelNotLoadedError, "MODEL_NOT_LOADED"), (OllamaTimeoutError, "MODEL_TIMEOUT"), (OllamaUnavailableError, "OLLAMA_UNAVAILABLE")):
        if isinstance(error, kind):
            request.app.state.logging_service.log_request("/chat", None, int((perf_counter() - started) * 1000), "error", code)
            return {"error_code": code, "message": str(error)}
    _LOG.error("agent turn failed after its stream began", exc_info=error)
    return {"error_code": "INTERNAL_ERROR", "message": "An unexpected server error occurred"}


def _agent_stream(request: Request, payload: ChatRequest, owner: str | None, started: float, tool_context: dict[str, object] | None = None) -> StreamingResponse:
    """Agent mode over SSE (ticket 20 #4, W1): the turn runs on a worker thread and its
    progress goes out as `progress` events while it runs, then meta → steps → answer → done
    as before. The chat service opens a database session per store call, so the thread
    shares none with the request. A client that leaves early leaves the turn running: it is
    persisted as the JSON path would persist it."""
    events: queue.Queue = queue.Queue()
    outcome: dict[str, object] = {}

    def work() -> None:
        try:
            outcome["result"] = request.app.state.chat_service.respond(
                payload.message, payload.conversation_id, payload.use_memory, payload.system_prompt,
                payload.use_tools, user_id=owner, on_step=events.put, **_marked(tool_context),
            )
        except Exception as error:  # reported as an SSE error event
            outcome["error"] = error
        finally:
            events.put(_TURN_DONE)

    start_in_request_context(work)

    def stream():
        while (event := events.get()) is not _TURN_DONE:
            if event.get("label"):
                yield sse_event("progress", {key: event[key] for key in ("kind", "round", "tool", "label") if event.get(key) is not None})
        if "error" in outcome:
            yield sse_event("error", _stream_failure(request, outcome["error"], started))
            return
        answer, model_used, conversation_id, _latency_ms, agent_steps = outcome["result"]
        yield sse_event("meta", {"conversation_id": conversation_id, "model_used": model_used})
        if agent_steps:
            yield sse_event("steps", {"steps": agent_steps})
        yield sse_event("token", {"content": answer})
        yield sse_event("done", {})

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
def chat(payload: ChatRequest, request: Request) -> ChatResponse | StreamingResponse:
    if not payload.use_tools and len(payload.message) > PASTE_THRESHOLD:
        # Only the agent can open a long paste (ticket 20 #3); plain chat keeps the old limit.
        raise HTTPException(status_code=422, detail={
            "error_code": "INPUT_TOO_LONG",
            "message": f"Tin nhắn dài {len(payload.message)} ký tự; chat thường nhận tối đa {PASTE_THRESHOLD}. "
                       f"Bật chế độ công cụ để dán văn bản dài (tối đa {PASTE_MAX}).",
        })
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
        # Laptop agent: None unless the file tools are on and this is the machine's owner.
        tool_context = local_files_context(request) if payload.use_tools else None
        if payload.stream:
            # Agent mode has no token stream (the loop runs whole rounds), but SSE clients
            # keep one code path; what the turn is doing streams ahead of it (ticket 20 #4).
            return _agent_stream(request, payload, owner, started, tool_context)
        answer, model_used, conversation_id, latency_ms, agent_steps = request.app.state.chat_service.respond(
            payload.message, payload.conversation_id, payload.use_memory, payload.system_prompt, payload.use_tools, user_id=owner,
            **_marked(tool_context),
        )
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
