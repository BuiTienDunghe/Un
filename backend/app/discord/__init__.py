"""Discord: the bot's sessions, turns, channel history and the memory it extracts (ticket 22).

The core (agent, RAG, documents, web memory) imports nothing from here; this package
imports the core and plugs into it. Models stay in app.postgres.models, one metadata
for Alembic, so no table or migration moved with the code.

main.py plugs it in at two points, because FastAPI has two: register_routes() when the
app object is built, so the routes exist whether or not the lifespan runs (tests often
skip it), and register_services() as the last step of the lifespan, once the chat,
memory and agent services it builds on exist. Both import lazily, so loading the
package's name loads none of its services. register_services() also plugs the agent's
search_history tool into the running agent's ToolRegistry (agent_tools.py, C4).

Imports are always absolute (`app.discord`): the bot's `discord` library from pip is a
different package, and a script run with cwd=backend/app would shadow it.
"""
from __future__ import annotations

from typing import Any


def register_routes(app: Any, *, admin_guard: list[Any]) -> None:
    """The five Discord routers, all behind the admin guard. Their prefixes
    (/api/bot, /api/condensations, /api/memory-review, /api/discord/...) overlap no
    core route, so where they are included does not change which route answers."""
    from app.discord.routers import bot, condensations, history, memory_review, message_labels, sessions

    for module in (bot, memory_review, message_labels, condensations, sessions, history):
        app.include_router(module.router, dependencies=admin_guard)


def register_services(app: Any, settings: Any, postgres_sessions: Any, *, project_root: Any) -> None:
    """Build the Discord services onto app.state. Needs app.state.memory_service,
    chat_service and agent_service, so main.py calls it last in the lifespan."""
    from app.discord import agent_tools
    from app.discord.bot_control_service import BotControlService
    from app.discord.condensation_service import DiscordCondensationService
    from app.discord.history_service import DiscordHistoryService
    from app.discord.memory_completion_service import DiscordMemoryCompletionService
    from app.discord import remember_tool
    from app.discord.message_labels import MessageLabelService
    from app.discord.memory_review_service import DiscordMemoryReviewService
    from app.discord.session_service import DiscordSessionService
    from app.discord.turn_progress import TurnProgress
    from app.discord.turn_service import DiscordTurnService

    state = app.state
    state.discord_session_service = DiscordSessionService(postgres_sessions)
    state.memory_review_service = DiscordMemoryReviewService(postgres_sessions, state.memory_service)
    # Tier 3 (§7): the API only READS condensations and manages them from the
    # dashboard — the writing (and the only Gemini call) belongs to the
    # background worker, so no condenser client is constructed here.
    state.condensation_service = DiscordCondensationService(
        postgres_sessions,
        None,
        min_batch=settings.discord_condensation_min_batch,
        max_batch=settings.discord_condensation_max_batch,
        silence_gap_minutes=settings.discord_condensation_silence_gap_minutes,
    )
    # Ticket 20 #4: what a running turn is doing, for GET .../turns/{id}/progress.
    state.discord_turn_progress = TurnProgress()
    state.discord_turn_service = DiscordTurnService(
        postgres_sessions,
        state.discord_session_service,
        state.chat_service,
        progress=state.discord_turn_progress,
        memory_completion_service=DiscordMemoryCompletionService(
            enabled=settings.discord_memory_ingestion_enabled,
            extractor_schema_version=(
                settings.discord_memory_extractor_schema_version
            ),
            max_attempts=settings.job_max_attempts,
        ),
        agent_tools_enabled=settings.discord_agent_tools_enabled,
        # "*" = every guild (the pre-allowlist behavior, opted into
        # EXPLICITLY); anything else is a comma-separated allowlist and an
        # empty/garbled value fails closed (no guild gets tools).
        agent_tools_guild_allowlist=(
            None
            if settings.discord_agent_tools_guild_allowlist.strip() == "*"
            else frozenset(
                value.strip()
                for value in settings.discord_agent_tools_guild_allowlist.split(",")
                if value.strip()
            )
        ),
        condensation_service=(
            state.condensation_service
            if settings.discord_condensation_enabled
            else None
        ),
        recap_limit=settings.discord_condensation_recap_limit,
    )
    # Job 1+2 (28/08): sổ gốc writes + guild-scoped verbatim history search.
    state.discord_history_service = DiscordHistoryService(postgres_sessions)
    # The agent's search_history tool, plugged into the running agent's registry at the
    # place it always had in the tool list (C4): the core declares no Discord tool.
    agent_tools.register(state.agent_service.registry, state.discord_history_service)
    # Ticket 35: remember, through the same approval path as every memory.
    remember_tool.register(state.agent_service.registry, postgres_sessions, state.memory_review_service)
    # Ticket 36: decided's suggestions, and the jokes a person approved.
    state.message_label_service = MessageLabelService(postgres_sessions)
    agent_tools.register_jokes(state.agent_service.registry, state.message_label_service)
    state.discord_turn_service.message_labels = state.message_label_service
    # P3-2: dashboard start/stop for the compose-managed Discord bot.
    state.bot_control_service = BotControlService(project_root)
