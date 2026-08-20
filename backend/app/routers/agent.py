"""Review the trace of an agent-mode answer (P2-2).

Read-only: the steps themselves are written by the chat path in the same
breath as the assistant message they explain.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/traces/{message_id}")
def get_traces(message_id: int, request: Request) -> list[dict[str, object]]:
    """All steps behind one assistant message, in execution order. An answer
    that never used tools simply has no rows."""
    return request.app.state.auxiliary_store.get_agent_traces(message_id)


@router.get("/activity")
def activity(request: Request, limit: int = 50) -> list[dict[str, object]]:
    """Timeline of autonomous actions (P2-4): memory decisions, agent answers,
    background jobs — newest first."""
    return request.app.state.operational_service.agent_activity(limit)
