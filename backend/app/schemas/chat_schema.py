from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    conversation_id: str | None = Field(default=None, max_length=64)
    use_memory: bool = False
    stream: bool = False


class ChatResponse(BaseModel):
    answer: str
    model_used: str
    conversation_id: str
    latency_ms: int
