"""The bot's side of approvals (ticket 46): what a member has waiting, and their yes or no.

A call is kept by the agent's gate from the member's own turn, never here. `actor_id` is the member
whose click the bot is relaying: the API key says the bot may speak for them, the service checks it is
the member the call belongs to."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.discord.approvals import approval_payload
from app.security.api_key import require_api_key
from app.services.approvals import ApprovalError

router = APIRouter(prefix="/api/discord/approvals", tags=["discord-approvals"], dependencies=[Depends(require_api_key)])

_STATUS = {
    "APPROVALS_DISABLED": 409,
    "GUILD_NOT_ALLOWED": 403,
    "APPROVAL_NOT_YOURS": 403,
    "APPROVAL_NOT_FOUND": 404,
    "APPROVAL_EXPIRED": 410,
    "APPROVAL_NOT_PENDING": 409,
}


class DecisionRequest(BaseModel):
    guild_id: str = Field(min_length=1, max_length=64)
    actor_id: str = Field(min_length=1, max_length=64)


def _service(request: Request):
    return request.app.state.approval_service


def _refuse(error: ApprovalError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(error.code, 422), detail={"error_code": error.code, "message": error.message})


def _decide(approval_id: str, payload: DecisionRequest, request: Request, *, approve: bool) -> dict[str, object]:
    try:
        decision = _service(request).decide(approval_id, guild_id=payload.guild_id, actor_id=payload.actor_id, approve=approve)
    except ApprovalError as error:
        raise _refuse(error) from error
    return {"status": decision.status, "tool_name": decision.tool_name, "text": decision.text, "code": decision.code}


@router.get("")
def listing(guild_id: str, author_id: str, request: Request) -> list[dict[str, object]]:
    try:
        return [approval_payload(item) for item in _service(request).list_for(guild_id, author_id)]
    except ApprovalError as error:
        raise _refuse(error) from error


@router.post("/{approval_id}/approve")
def approve(approval_id: str, payload: DecisionRequest, request: Request) -> dict[str, object]:
    return _decide(approval_id, payload, request, approve=True)


@router.post("/{approval_id}/deny")
def deny(approval_id: str, payload: DecisionRequest, request: Request) -> dict[str, object]:
    return _decide(approval_id, payload, request, approve=False)
