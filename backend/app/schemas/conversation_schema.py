from pydantic import BaseModel, Field


class ConversationSummary(BaseModel):
    id: str
    title: str | None = None
    created_at: str
    updated_at: str
    message_count: int


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationMessageSource(BaseModel):
    """A citation as it stood when the answer was given, not as re-read today."""

    document_id: str
    chunk_id: str
    filename: str
    page_start: int | None = None
    page_end: int | None = None
    heading_path: str | None = None
    score: float
    excerpt: str


class ConversationMessage(BaseModel):
    role: str
    content: str
    model_used: str | None = None
    created_at: str
    sources: list[ConversationMessageSource] = Field(default_factory=list)


class ConversationDetail(BaseModel):
    id: str
    title: str | None = None
    created_at: str
    updated_at: str
    messages: list[ConversationMessage]
