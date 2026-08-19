"""Human review of Discord memory candidates (P1-4/P1-5)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.postgres.discord_memory_repositories import DiscordMemoryConflictError
from app.security.api_key import require_api_key
from app.services.discord_memory_review_service import (
    CandidateNotFoundError,
    CandidateNotReviewableError,
    MemoryMirrorError,
)

router = APIRouter(prefix="/api/memory-review", tags=["memory-review"])


def _candidate_uuid(candidate_id: str) -> UUID:
    try:
        return UUID(candidate_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail={"error_code": "CANDIDATE_NOT_FOUND", "message": f"Candidate {candidate_id} does not exist"}) from error


@router.get("/candidates")
def list_candidates(request: Request) -> list[dict[str, object]]:
    return request.app.state.memory_review_service.list_pending()


@router.post("/candidates/{candidate_id}/approve", dependencies=[Depends(require_api_key)])
def approve_candidate(candidate_id: str, request: Request) -> dict[str, object]:
    try:
        return request.app.state.memory_review_service.approve(_candidate_uuid(candidate_id))
    except CandidateNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "CANDIDATE_NOT_FOUND", "message": f"Candidate {error} does not exist"}) from error
    except CandidateNotReviewableError as error:
        raise HTTPException(status_code=422, detail={"error_code": "CANDIDATE_NOT_REVIEWABLE", "message": str(error)}) from error
    except DiscordMemoryConflictError as error:
        raise HTTPException(status_code=409, detail={"error_code": "MEMORY_CONFLICT", "message": str(error)}) from error
    except MemoryMirrorError as error:
        # The Discord memory is applied; only the web mirror failed. Approving
        # again retries just the mirror.
        raise HTTPException(status_code=502, detail={"error_code": "MEMORY_MIRROR_FAILED", "message": str(error)}) from error


@router.post("/candidates/{candidate_id}/reject", dependencies=[Depends(require_api_key)])
def reject_candidate(candidate_id: str, request: Request) -> dict[str, object]:
    try:
        return request.app.state.memory_review_service.reject(_candidate_uuid(candidate_id))
    except CandidateNotFoundError as error:
        raise HTTPException(status_code=404, detail={"error_code": "CANDIDATE_NOT_FOUND", "message": f"Candidate {error} does not exist"}) from error
    except CandidateNotReviewableError as error:
        raise HTTPException(status_code=422, detail={"error_code": "CANDIDATE_NOT_REVIEWABLE", "message": str(error)}) from error
