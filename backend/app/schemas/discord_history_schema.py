from __future__ import annotations

from pydantic import BaseModel, Field


class DiscordHistoryMessageRequest(BaseModel):
    guild_id: str = Field(min_length=1, max_length=64)
    channel_id: str = Field(min_length=1, max_length=64)
    thread_id: str | None = Field(default=None, max_length=64)
    discord_message_id: str = Field(min_length=1, max_length=64)
    author_id: str = Field(min_length=1, max_length=64)
    author_display_name: str = Field(min_length=1, max_length=200)
    is_bot: bool = False
    content: str = Field(min_length=1, max_length=8000)
    reply_to_message_id: str | None = Field(default=None, max_length=64)


class DiscordHistoryEditRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class DiscordHistoryDeleteRequest(BaseModel):
    # Optional: when present, a delete that beat the insert leaves a
    # tombstone so the racing insert cannot store the deleted text.
    guild_id: str | None = Field(default=None, max_length=64)
    channel_id: str | None = Field(default=None, max_length=64)


class DiscordHistoryWriteResponse(BaseModel):
    recorded: bool
