"""Discord bot control from the dashboard (P3-2): status, start, stop."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.security.api_key import require_api_key
from app.services.bot_control_service import BotControlError, BotTokenMissingError

router = APIRouter(prefix="/api/bot", tags=["bot"])


@router.get("/status")
def bot_status(request: Request) -> dict[str, object]:
    return request.app.state.bot_control_service.status()


@router.post("/start", dependencies=[Depends(require_api_key)])
def bot_start(request: Request) -> dict[str, object]:
    try:
        return request.app.state.bot_control_service.start()
    except BotTokenMissingError as error:
        raise HTTPException(status_code=409, detail={"error_code": "DISCORD_TOKEN_MISSING", "message": str(error)}) from error
    except BotControlError as error:
        raise HTTPException(status_code=502, detail={"error_code": "BOT_CONTROL_FAILED", "message": str(error)}) from error


@router.post("/stop", dependencies=[Depends(require_api_key)])
def bot_stop(request: Request) -> dict[str, object]:
    try:
        return request.app.state.bot_control_service.stop()
    except BotControlError as error:
        raise HTTPException(status_code=502, detail={"error_code": "BOT_CONTROL_FAILED", "message": str(error)}) from error
