"""Read-only aggregate statistics for the management dashboard.

The numbers are DashboardService's (app/services/dashboard_service.py); this
router only shapes them into the response schema.
"""
from fastapi import APIRouter, Request

from app.schemas.dashboard_schema import DashboardStats

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/timeseries")
def dashboard_timeseries(request: Request, days: int = 14) -> dict[str, object]:
    """Daily question volume, latency percentiles and error counts (P3-3)."""
    return request.app.state.dashboard_service.timeseries(days)


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(request: Request) -> DashboardStats:
    return DashboardStats.model_validate(request.app.state.dashboard_service.stats())
