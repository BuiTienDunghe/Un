from fastapi import APIRouter, Request

from app.schemas.model_schema import ModelsResponse

router = APIRouter(tags=["models"])


@router.get("/models", response_model=ModelsResponse)
def models(request: Request) -> ModelsResponse:
    return ModelsResponse(models=request.app.state.models)
