from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger

from app.schemas.vision_schema import VisionChatRequest
from app.security.api_key import require_api_key

router = APIRouter(prefix="/vision", tags=["vision"])


@router.post("/chat", dependencies=[Depends(require_api_key)])
def vision_chat(payload: VisionChatRequest, request: Request) -> dict[str, object]:
    model_router = request.app.state.model_router
    if "vision" not in model_router.models:
        raise HTTPException(
            status_code=501,
            detail={"error_code": "VISION_NOT_IMPLEMENTED", "message": "No vision version is serving: pick one on the Model screen."},
        )
    if not payload.image_base64:
        raise HTTPException(status_code=422, detail={"error_code": "IMAGE_REQUIRED", "message": "image_base64 is required."})
    try:
        answer, model = model_router.vision(payload.message, payload.image_base64)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"error_code": "IMAGE_INVALID", "message": str(error)}) from error
    except Exception as error:
        logger.warning("vision call failed: {}", type(error).__name__)
        raise HTTPException(status_code=502, detail={"error_code": "VISION_FAILED", "message": "The vision model did not answer."}) from error
    return {"message": answer, "implemented": True, "model": model}
