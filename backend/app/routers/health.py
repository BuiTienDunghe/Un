from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    return request.app.state.operational_service.health()


@router.get("/metrics")
def metrics(request: Request) -> dict[str, object]:
    return request.app.state.operational_service.metrics()
