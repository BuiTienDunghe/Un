"""Bot-facing raw-ledger ingest (job 1, memory_design.md §5).

The bot fires one POST per heard message in a listened channel and swallows
every failure on its side — this router must therefore stay boring: parse,
one short service call, typed response. Writes only; the search side is not
an HTTP endpoint, it reaches the model as the `search_history` agent tool
with the guild injected server-side.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.schemas.discord_history_schema import (
    DiscordHistoryDeleteRequest,
    DiscordHistoryEditRequest,
    DiscordHistoryMessageRequest,
    DiscordHistoryWriteResponse,
)
from app.security.api_key import require_api_key

router = APIRouter(
    prefix="/api/discord/history",
    tags=["discord-history"],
    # Every route is a bot-authenticated write; the guard sits on the router.
    dependencies=[Depends(require_api_key)],
)


@router.post("/messages", response_model=DiscordHistoryWriteResponse)
def record_message(
    request: Request,
    payload: DiscordHistoryMessageRequest,
) -> DiscordHistoryWriteResponse:
    recorded = request.app.state.discord_history_service.record_message(
        guild_id=payload.guild_id,
        channel_id=payload.channel_id,
        thread_id=payload.thread_id,
        discord_message_id=payload.discord_message_id,
        author_id=payload.author_id,
        author_display_name=payload.author_display_name,
        is_bot=payload.is_bot,
        content=payload.content,
        reply_to_message_id=payload.reply_to_message_id,
    )
    return DiscordHistoryWriteResponse(recorded=recorded)


@router.post(
    "/messages/{discord_message_id}/edit",
    response_model=DiscordHistoryWriteResponse,
)
def record_edit(
    request: Request,
    discord_message_id: str,
    payload: DiscordHistoryEditRequest,
) -> DiscordHistoryWriteResponse:
    recorded = request.app.state.discord_history_service.record_edit(
        discord_message_id=discord_message_id,
        content=payload.content,
    )
    return DiscordHistoryWriteResponse(recorded=recorded)


@router.post(
    "/messages/{discord_message_id}/delete",
    response_model=DiscordHistoryWriteResponse,
)
def record_delete(
    request: Request,
    discord_message_id: str,
    payload: DiscordHistoryDeleteRequest | None = None,
) -> DiscordHistoryWriteResponse:
    recorded = request.app.state.discord_history_service.record_delete(
        discord_message_id=discord_message_id,
        guild_id=payload.guild_id if payload else None,
        channel_id=payload.channel_id if payload else None,
    )
    return DiscordHistoryWriteResponse(recorded=recorded)
