from fastapi import APIRouter, Depends, Request

from app.security.auth import require_admin

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    return request.app.state.operational_service.health()


@router.get("/metrics", dependencies=[Depends(require_admin)])
def metrics(request: Request) -> dict[str, object]:
    """Operational metrics feed the admin dashboard; with accounts on it is
    admin-only (no-op guard while auth is disabled — today's behavior)."""
    return request.app.state.operational_service.metrics()
