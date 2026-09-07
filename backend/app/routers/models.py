from fastapi import APIRouter, Request

from app.schemas.model_schema import ModelsResponse

router = APIRouter(tags=["models"])


@router.get("/models", response_model=ModelsResponse)
def models(request: Request) -> ModelsResponse:
    state = request.app.state
    return ModelsResponse(models=state.models, registry=state.model_registry.registry_view(), rag=state.rag_flags)
