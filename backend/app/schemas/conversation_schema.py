from pydantic import BaseModel


class ConversationSummary(BaseModel):
    id: str
    created_at: str
    updated_at: str
    message_count: int


class ConversationMessage(BaseModel):
    role: str
    content: str
    model_used: str | None = None
    created_at: str


class ConversationDetail(BaseModel):
    id: str
    created_at: str
    updated_at: str
    messages: list[ConversationMessage]
