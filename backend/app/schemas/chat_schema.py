from pydantic import BaseModel, Field

from app.services.pastes import PASTE_MAX


class ChatRequest(BaseModel):
    # Up to PASTE_MAX in tool mode, where a long paste becomes a document the agent
    # reads (ticket 20 #3); /chat refuses more than PASTE_THRESHOLD without tools.
    message: str = Field(min_length=1, max_length=PASTE_MAX)
    conversation_id: str | None = Field(default=None, max_length=64)
    # API clients such as the Discord gateway can supply their own isolated
    # persona without changing the UI/general-chat prompt on disk.
    system_prompt: str | None = Field(default=None, min_length=1, max_length=20_000)
    use_memory: bool = False
    # Agent mode (P2-2): the model may call in-house tools (documents, memory,
    # system status) before answering; every step is traced.
    use_tools: bool = False
    stream: bool = False


class ChatResponse(BaseModel):
    answer: str
    model_used: str
    conversation_id: str
    latency_ms: int
    # Present only for agent-mode answers: the tool calls/results and final
    # synthesis, in order. The same steps persist in `agent_traces`.
    agent_steps: list[dict[str, object]] | None = None
