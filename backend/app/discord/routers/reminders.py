"""The bot's side of reminders (ticket 48): what is due, that it was sent or failed, the list and the cancel.

A reminder is created by the agent's `remind` tool from the member's own words, never here."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.discord.reminders import ReminderError, reminder_payload
from app.security.api_key import require_api_key

router = APIRouter(prefix="/api/discord/reminders", tags=["discord-reminders"], dependencies=[Depends(require_api_key)])

_STATUS = {
    "REMINDERS_DISABLED": 409,
    "GUILD_NOT_ALLOWED": 403,
    "REMINDER_NOT_YOURS": 403,
    "REMINDER_NOT_FOUND": 404,
    "REMINDER_AMBIGUOUS": 409,
    "REMINDER_NOT_CANCELLABLE": 409,
}


class SentRequest(BaseModel):
    discord_message_id: str | None = Field(default=None, max_length=64)


class FailedRequest(BaseModel):
    error: str = Field(max_length=2_000)
    retryable: bool


class CancelRequest(BaseModel):
    guild_id: str = Field(min_length=1, max_length=64)
    requester_id: str = Field(min_length=1, max_length=64)


def _service(request: Request):
    return request.app.state.reminder_service


def _uuid(reminder_id: str) -> str:
    try:
        return str(UUID(reminder_id))
    except ValueError as error:
        raise HTTPException(status_code=404, detail={"error_code": "REMINDER_NOT_FOUND", "message": "No such reminder."}) from error


def _refuse(error: ReminderError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(error.code, 422), detail={"error_code": error.code, "message": error.message})


@router.post("/claim")
def claim(request: Request) -> list[dict[str, object]]:
    """Reminders whose hour has come. Claiming marks them as being sent, so ask again only after sending."""
    try:
        return [reminder_payload(item.reminder, late_seconds=item.late_seconds) for item in _service(request).claim_due()]
    except ReminderError as error:
        raise _refuse(error) from error


@router.post("/{reminder_id}/sent")
def sent(reminder_id: str, payload: SentRequest, request: Request) -> dict[str, str]:
    try:
        _service(request).mark_sent(_uuid(reminder_id), payload.discord_message_id)
    except ReminderError as error:
        raise _refuse(error) from error
    return {"status": "sent"}


@router.post("/{reminder_id}/failed")
def failed(reminder_id: str, payload: FailedRequest, request: Request) -> dict[str, str]:
    try:
        return {"status": _service(request).mark_failed(_uuid(reminder_id), payload.error, retryable=payload.retryable)}
    except ReminderError as error:
        raise _refuse(error) from error


@router.get("")
def listing(guild_id: str, author_id: str, request: Request) -> list[dict[str, object]]:
    try:
        return [reminder_payload(item) for item in _service(request).list_for(guild_id, author_id)]
    except ReminderError as error:
        raise _refuse(error) from error


@router.post("/{reminder_ref}/cancel")
def cancel(reminder_ref: str, payload: CancelRequest, request: Request) -> dict[str, object]:
    try:
        return reminder_payload(_service(request).cancel(reminder_ref, guild_id=payload.guild_id, requester_id=payload.requester_id)) | {"status": "cancelled"}
    except ReminderError as error:
        raise _refuse(error) from error
