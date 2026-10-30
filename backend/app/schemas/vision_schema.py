from pydantic import BaseModel, Field


class VisionChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    # 12 MB of base64: the bot's limit on one attachment is 8 MB of bytes.
    image_base64: str | None = Field(default=None, max_length=12_000_000)


class VisionChatResponse(BaseModel):
    message: str
    implemented: bool
