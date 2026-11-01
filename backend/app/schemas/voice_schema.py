from pydantic import BaseModel, Field


class VoiceTranscribeRequest(BaseModel):
    # 12 MB of base64: the bot's limit on one recording is 8 MB of bytes.
    audio_base64: str = Field(min_length=1, max_length=12_000_000)


class VoiceTranscribeResponse(BaseModel):
    text: str
