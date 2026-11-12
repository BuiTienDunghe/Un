"""The web chat's approval card for file changes (laptop agent, batch 2): see a call that waits,
approve or deny it, undo a change. Only the machine's owner, by the same rule as the /chat mark
(routers/chat.local_files_context); 404 while the write tools are off."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.routers.chat import local_files_context
from app.security.api_key import require_api_key
from app.services.approvals import ApprovalError
from app.services.local_files import Refused

router = APIRouter(prefix="/local-files", tags=["local-files"], dependencies=[Depends(require_api_key)])

_STATUS = {"APPROVAL_NOT_FOUND": 404, "APPROVAL_EXPIRED": 409, "APPROVAL_NOT_PENDING": 409}


class DecisionRequest(BaseModel):
    approve: bool


def _gate(request: Request):
    gate = getattr(request.app.state, "local_file_approvals", None)
    if gate is None:
        raise HTTPException(status_code=404, detail={"error_code": "LOCAL_FILES_WRITE_DISABLED", "message": "Ghi tệp đang tắt."})
    if local_files_context(request) is None:
        raise HTTPException(status_code=403, detail={"error_code": "NOT_OWNER", "message": "Chỉ chủ máy mới duyệt hay hoàn tác được việc ghi tệp."})
    return gate


def _refusal(error: ApprovalError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(error.code, 409), detail={"error_code": error.code, "message": error.message})


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: str, request: Request) -> dict[str, object]:
    gate = _gate(request)
    try:
        return gate.get(approval_id)
    except ApprovalError as error:
        raise _refusal(error) from error


@router.post("/approvals/{approval_id}")
def decide(approval_id: str, payload: DecisionRequest, request: Request) -> dict[str, object]:
    gate = _gate(request)
    try:
        return gate.decide(approval_id, payload.approve)
    except ApprovalError as error:
        raise _refusal(error) from error


@router.get("/conversations/{conversation_id}/cards")
def cards(conversation_id: str, request: Request) -> dict[str, object]:
    """What a reopened conversation shows again: calls still waiting, and changes made in it in the last 3 days."""
    gate = _gate(request)
    return {"approvals": gate.pending_for(conversation_id), "changes": gate.writes.backups.for_conversation(conversation_id)}


@router.post("/changes/{change_id}/undo")
def undo(change_id: str, request: Request) -> dict[str, object]:
    gate = _gate(request)
    try:
        return {"undone": True, "message": gate.writes.undo(change_id)}
    except Refused as refused:
        raise HTTPException(status_code=409, detail={"error_code": "UNDO_REFUSED", "message": refused.message}) from refused
    except OSError as error:
        raise HTTPException(status_code=409, detail={
            "error_code": "UNDO_FAILED", "message": "Chưa hoàn tác được (tệp đang mở ở chương trình khác, hoặc không có quyền).",
        }) from error
