from fastapi import APIRouter, HTTPException

from app.schemas.vision_schema import VisionChatRequest

router = APIRouter(prefix="/vision", tags=["vision"])


@router.post("/chat", status_code=501)
def vision_chat(_: VisionChatRequest) -> None:
    raise HTTPException(
        status_code=501,
        detail={"error_code": "VISION_NOT_IMPLEMENTED", "message": "vision module is not fully implemented yet"},
    )
