import base64
import binascii

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger

from app.schemas.voice_schema import VoiceTranscribeRequest, VoiceTranscribeResponse
from app.security.api_key import require_api_key

router = APIRouter(prefix="/voice", tags=["voice"])

# Ticket 49. The speech model lives in its own local service (tools/voice_server.py, VOICE_URL), which
# the Docker bot cannot reach on loopback: it asks here, as it does for images. Nothing is kept.
MAX_AUDIO_BYTES = 8 * 1024 * 1024
# A cold start of the speech model is part of the first request.
REQUEST_TIMEOUT_SECONDS = 170.0


def _refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": message})


@router.post("/transcribe", dependencies=[Depends(require_api_key)], response_model=VoiceTranscribeResponse)
def transcribe(payload: VoiceTranscribeRequest, request: Request) -> dict[str, str]:
    url = request.app.state.settings.voice_url
    if not url:
        raise _refuse(501, "VOICE_NOT_ENABLED", "No speech service is configured: VOICE_URL is not set.")
    try:
        audio = base64.b64decode(payload.audio_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise _refuse(422, "AUDIO_INVALID", "audio_base64 is not valid base64.") from error
    if len(audio) > MAX_AUDIO_BYTES:
        raise _refuse(413, "AUDIO_TOO_LARGE", "The recording is too large.")
    try:
        response = httpx.post(f"{url.rstrip('/')}/transcribe", content=audio, timeout=REQUEST_TIMEOUT_SECONDS)
    except httpx.HTTPError as error:
        # The service being down is normal: it shares the GPU and may be closed. Only the type is logged.
        logger.warning("voice service not reached: {}", type(error).__name__)
        raise _refuse(502, "VOICE_UNAVAILABLE", "The speech service did not answer.") from error
    if response.status_code != 200:
        logger.warning("voice service refused: {}", response.status_code)
        if response.status_code in (413, 422):
            raise _refuse(response.status_code, "AUDIO_REJECTED", "The speech service could not take this recording.")
        raise _refuse(502, "VOICE_FAILED", "The speech service could not hear this recording.")
    try:
        text = response.json()["text"]
    except (ValueError, KeyError, TypeError) as error:
        raise _refuse(502, "VOICE_FAILED", "The speech service sent an unreadable answer.") from error
    if not isinstance(text, str):
        raise _refuse(502, "VOICE_FAILED", "The speech service sent an unreadable answer.")
    return {"text": text.strip()}
