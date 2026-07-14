from pydantic import BaseModel, Field


class CodeChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    code_context: str | None = Field(default=None, max_length=50_000)
    repo_context: str | None = Field(default=None, max_length=10_000)
    stream: bool = False


class CodeChatResponse(BaseModel):
    answer: str
    model_used: str
    latency_ms: int
    suggested_patch: str | None = None
