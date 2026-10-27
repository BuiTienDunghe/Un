"""Operator surface for tier-3 condensations (memory_design.md §9.7).

Summaries are used without human approval — unlike facts — so §9.7's demand
is the opposite one: they must be VISIBLE and REVOCABLE. This router lists
what the condenser wrote, drops a batch (which frees its span so the worker
can rebuild it), and marks a batch stale for regeneration.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.security.api_key import require_api_key

router = APIRouter(prefix="/api/condensations", tags=["condensations"])


@router.get("")
def list_condensations(
    request: Request,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, object]]:
    return request.app.state.condensation_service.list_batches(
        limit=limit, offset=offset
    )


@router.delete(
    "/{batch_id}",
    status_code=204,
    dependencies=[Depends(require_api_key)],
)
def delete_condensation(batch_id: int, request: Request) -> None:
    if not request.app.state.condensation_service.delete_batch(batch_id):
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "CONDENSATION_NOT_FOUND",
                "message": f"Condensation batch {batch_id} does not exist",
            },
        )


@router.post(
    "/{batch_id}/regenerate",
    dependencies=[Depends(require_api_key)],
)
def regenerate_condensation(batch_id: int, request: Request) -> dict[str, object]:
    """Drop the batch and free its messages; the worker rebuilds the span on
    its next pass (a regenerate that ran here would put a cloud call on an
    HTTP request — the one thing tier 3 must never do)."""
    if not request.app.state.condensation_service.delete_batch(batch_id):
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "CONDENSATION_NOT_FOUND",
                "message": f"Condensation batch {batch_id} does not exist",
            },
        )
    return {"batch_id": batch_id, "status": "queued_for_rebuild"}
