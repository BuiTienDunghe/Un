from pydantic import BaseModel, Field


class MemoryCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    memory_type: str = Field(default="preference", min_length=1, max_length=64)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)


class MemoryUpdateRequest(MemoryCreateRequest):
    pass


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10_000)
    top_k: int = Field(default=5, ge=1, le=20)


class MemoryResponse(BaseModel):
    id: str
    content: str
    memory_type: str
    importance: float
    created_at: str
    updated_at: str


class MemorySearchResult(BaseModel):
    memory_id: str
    content: str
    memory_type: str
    importance: float
    score: float
