from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    store_ok = request.app.state.store.healthcheck()
    ollama_ok = request.app.state.ollama_client.healthcheck()
    return {
        "status": "ok" if store_ok and ollama_ok else "degraded",
        "service": "local-ai-core",
        "sqlite": "ok" if store_ok else "unavailable",
        "ollama": "ok" if ollama_ok else "unavailable",
    }
