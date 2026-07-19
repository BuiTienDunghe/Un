from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    conversation_id: str | None = Field(default=None, max_length=64)
    # API clients such as the Discord gateway can supply their own isolated
    # persona without changing the UI/general-chat prompt on disk.
    system_prompt: str | None = Field(default=None, min_length=1, max_length=20_000)
    use_memory: bool = False
    stream: bool = False


class ChatResponse(BaseModel):
    answer: str
    model_used: str
    conversation_id: str
    latency_ms: int
