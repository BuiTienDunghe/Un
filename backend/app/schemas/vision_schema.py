from pydantic import BaseModel, Field


class VisionChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)


class VisionChatResponse(BaseModel):
    message: str
    implemented: bool
