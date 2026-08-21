from pydantic import BaseModel, Field


class RagChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    document_id: str | None = Field(default=None, max_length=64)
    document_ids: list[str] | None = Field(default=None, max_length=100)
    # None defers to the server-side default from models.yaml (rag.top_k).
    top_k: int | None = Field(default=None, ge=1, le=20)
    # RAG turns persist into an ordinary conversation; omit to start a new one.
    conversation_id: str | None = Field(default=None, max_length=64)
    stream: bool = False


class RagSearchRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    document_id: str | None = Field(default=None, max_length=64)
    document_ids: list[str] | None = Field(default=None, max_length=100)
    # None defers to the server-side default from models.yaml (rag.top_k).
    top_k: int | None = Field(default=None, ge=1, le=20)


class RagSource(BaseModel):
    document_id: str
    filename: str
    # Real ``document_chunks.id`` row identity; ``chunk_index`` is the ordinal
    # position inside the version and is kept for display only.
    chunk_id: str
    chunk_index: int
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
    # Full chunk text as placed in the model context; the excerpt above is a
    # display preview. Consumers verifying citations should use this field.
    content: str
    extraction_method: str


class RagSearchResponse(BaseModel):
    latency_ms: int
    # Empty means nothing indexed matched: for search that is a result, not an
    # error — unlike /rag/chat, which refuses to answer without context.
    sources: list[RagSource]


class RagChatResponse(BaseModel):
    answer: str
    model_used: str
    latency_ms: int
    conversation_id: str | None = None
    # Set when a follow-up was condensed into a standalone question before
    # retrieval; the persisted user message stays the raw input.
    retrieval_question: str | None = None
    sources: list[RagSource]
