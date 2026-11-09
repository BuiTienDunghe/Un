from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger

from app.schemas.vision_schema import VisionChatRequest
from app.security.api_key import require_api_key
from app.services.ocr_service import OcrEvidenceError
import base64
import binascii

router = APIRouter(prefix="/vision", tags=["vision"])


@router.post("/chat", dependencies=[Depends(require_api_key)])
def vision_chat(payload: VisionChatRequest, request: Request) -> dict[str, object]:
    model_router = request.app.state.model_router
    if not payload.image_base64:
        raise HTTPException(status_code=422, detail={"error_code": "IMAGE_REQUIRED", "message": "image_base64 is required."})
    if "vision" not in model_router.models:
        ocr_service = getattr(request.app.state, "ocr_service", None)
        if ocr_service is not None and model_router.models.get("ocr", {}).get("enabled", False):
            try:
                image = base64.b64decode(payload.image_base64, validate=True)
                result = ocr_service.recognize_png(image, int(model_router.models["ocr"].get("dpi", 200)))
            except OcrEvidenceError as error:
                raise HTTPException(502, detail={"error_code": "OCR_EVIDENCE_INVALID", "message": "The OCR output was invalid."}) from error
            except (ValueError, binascii.Error) as error:
                raise HTTPException(422, detail={"error_code": "IMAGE_INVALID", "message": "Cannot read image evidence."}) from error
            except Exception as error:
                logger.warning("image OCR failed: {}", type(error).__name__)
                raise HTTPException(502, detail={"error_code": "OCR_FAILED", "message": "The OCR model did not answer."}) from error
            return {"message": result.text or "Không đọc được chữ trong ảnh; chưa có bằng chứng mô tả nội dung ảnh.",
                    "implemented": True, "model": result.model, "mode": "ocr_evidence",
                    "blocks": [block.payload() for block in result.blocks], "cache_hit": result.cache_hit}
        raise HTTPException(
            status_code=501,
            detail={"error_code": "VISION_NOT_IMPLEMENTED", "message": "No vision version is serving: pick one on the Model screen."},
        )
    try:
        answer, model = model_router.vision(payload.message, payload.image_base64)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"error_code": "IMAGE_INVALID", "message": str(error)}) from error
    except Exception as error:
        logger.warning("vision call failed: {}", type(error).__name__)
        raise HTTPException(status_code=502, detail={"error_code": "VISION_FAILED", "message": "The vision model did not answer."}) from error
    return {"message": answer, "implemented": True, "model": model}
