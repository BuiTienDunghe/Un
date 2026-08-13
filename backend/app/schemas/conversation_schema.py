from pydantic import BaseModel, Field


class ConversationSummary(BaseModel):
    id: str
    title: str | None = None
    created_at: str
    updated_at: str
    message_count: int


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationMessage(BaseModel):
    role: str
    content: str
    model_used: str | None = None
    created_at: str


class ConversationDetail(BaseModel):
    id: str
    title: str | None = None
    created_at: str
    updated_at: str
    messages: list[ConversationMessage]
