"""The review queue for decided's suggestions (ticket 36)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.discord.message_labels import LABELS, LabelNotFoundError
from app.security.api_key import require_api_key

router = APIRouter(prefix="/api/message-labels", tags=["message-labels"])


class ApproveRequest(BaseModel):
    label: str | None = None


def _uuid(label_id: str) -> UUID:
    try:
        return UUID(label_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail={"error_code": "LABEL_NOT_FOUND", "message": "No such suggestion."}) from error


def _review(request: Request, label_id: str, **fields: object) -> dict[str, object]:
    try:
        return request.app.state.message_label_service.review(_uuid(label_id), **fields)
    except LabelNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "LABEL_NOT_FOUND", "message": "No such suggestion."}) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"error_code": "LABEL_INVALID", "message": str(error)}) from error


@router.get("")
def pending(request: Request, limit: int = 50, offset: int = 0) -> list[dict[str, object]]:
    return request.app.state.message_label_service.pending(limit=min(max(limit, 1), 200), offset=max(offset, 0))


@router.get("/approved")
def approved(request: Request, label: str | None = None, limit: int = 100) -> list[dict[str, object]]:
    labels = (label,) if label in LABELS else LABELS
    return request.app.state.message_label_service.approved(None, labels, min(max(limit, 1), 200))


@router.get("/stats")
def stats(request: Request) -> dict[str, object]:
    return request.app.state.message_label_service.stats()


@router.post("/{label_id}/approve", dependencies=[Depends(require_api_key)])
def approve(label_id: str, payload: ApproveRequest, request: Request) -> dict[str, object]:
    return _review(request, label_id, status="approved", final_label=payload.label)


@router.post("/{label_id}/reject", dependencies=[Depends(require_api_key)])
def reject(label_id: str, request: Request) -> dict[str, object]:
    return _review(request, label_id, status="rejected")


@router.post("/{label_id}/reopen", dependencies=[Depends(require_api_key)])
def reopen(label_id: str, request: Request) -> dict[str, object]:
    return _review(request, label_id, status="pending")
