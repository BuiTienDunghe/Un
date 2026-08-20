from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
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
