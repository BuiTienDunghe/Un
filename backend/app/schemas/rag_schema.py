from pydantic import BaseModel, Field


class RagChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    document_id: str | None = Field(default=None, max_length=64)
    document_ids: list[str] | None = Field(default=None, max_length=100)
    top_k: int = Field(default=5, ge=1, le=20)
    stream: bool = False


class RagSource(BaseModel):
    document_id: str
    filename: str
    chunk_id: int
    index_version: int
    page: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    locations: list[dict[str, int | None]] = Field(default_factory=list)
    heading_path: str | None = None
    section_title: str | None = None
    block_type: str = "paragraph"
    source_available: bool = False
    verifiable: bool = False
    score: float
    excerpt: str
    extraction_method: str


class RagChatResponse(BaseModel):
    answer: str
    model_used: str
    latency_ms: int
    sources: list[RagSource]
