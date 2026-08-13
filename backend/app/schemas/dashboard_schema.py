from pydantic import BaseModel


class WebAgentStats(BaseModel):
    conversation_count: int
    message_count: int
    last_activity_at: str | None = None


class DiscordSessionSummary(BaseModel):
    session_id: str
    guild_id: str
    channel_id: str
    thread_id: str | None = None
    status: str
    turn_count: int
    last_active_at: str | None = None


class DiscordAgentStats(BaseModel):
    session_count: int
    active_session_count: int
    turn_counts: dict[str, int]
    delivery_count: int
    last_activity_at: str | None = None
    recent_sessions: list[DiscordSessionSummary]


class DashboardStats(BaseModel):
    web: WebAgentStats
    discord: DiscordAgentStats
