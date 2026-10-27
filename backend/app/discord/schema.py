from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DiscordSessionResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guild_id: str = Field(min_length=1, max_length=64)
    channel_id: str = Field(min_length=1, max_length=64)
    thread_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("guild_id", "channel_id", "thread_id", mode="before")
    @classmethod
    def strip_identifiers(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("guild_id", "channel_id", "thread_id")
    @classmethod
    def reject_empty_identifiers(cls, value: str | None) -> str | None:
        if value is not None and not value:
            raise ValueError("Discord identifiers cannot be empty.")
        return value


class DiscordSessionResolveResponse(BaseModel):
    session_id: UUID
    backend_conversation_id: UUID
    created: bool
    status: Literal["active"]


class DiscordTurnEnqueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discord_message_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=10_000)
    author_id: str = Field(min_length=1, max_length=64)
    author_display_name: str = Field(min_length=1, max_length=256)
    reply_to_discord_message_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )
    system_prompt: str | None = Field(default=None, min_length=1, max_length=20_000)

    @field_validator(
        "discord_message_id",
        "author_id",
        "author_display_name",
        "reply_to_discord_message_id",
        mode="before",
    )
    @classmethod
    def strip_metadata(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class DiscordTurnEnqueueResponse(BaseModel):
    turn_id: UUID
    session_id: UUID
    sequence_number: int
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    created: bool


class DiscordTurnExecuteResponse(BaseModel):
    turn_id: UUID
    session_id: UUID
    sequence_number: int
    status: Literal["queued", "running", "completed", "failed", "cancelled", "requeued"]
    answer: str | None = None
    model_used: str | None = None
    execution_token: str | None = None
    replacement_turn_id: UUID | None = None


class DiscordTurnOwnershipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_token: str = Field(min_length=1, max_length=128)


class DiscordTurnCompleteRequest(DiscordTurnOwnershipRequest):
    discord_response_message_ids: list[str] = Field(
        min_length=1,
        max_length=16,
    )

    @field_validator("discord_response_message_ids", mode="before")
    @classmethod
    def normalize_response_message_ids(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [item.strip() if isinstance(item, str) else item for item in value]

    @field_validator("discord_response_message_ids")
    @classmethod
    def validate_response_message_ids(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 64 for item in value):
            raise ValueError(
                "Discord response message IDs must be non-empty and at most "
                "64 characters."
            )
        if len(set(value)) != len(value):
            raise ValueError("Discord response message IDs must be unique.")
        return value


class DiscordTurnFailRequest(DiscordTurnOwnershipRequest):
    error: str = Field(min_length=1, max_length=4_000)
    retryable: bool = True


class DiscordTurnStateResponse(BaseModel):
    turn_id: UUID
    status: Literal["queued", "running", "completed", "failed", "cancelled"]


class DiscordTurnOperatorStopResponse(BaseModel):
    cancelled_turns: int = Field(ge=0)
