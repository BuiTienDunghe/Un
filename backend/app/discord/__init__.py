"""Discord: the bot's sessions, turns, channel history and the memory it extracts (ticket 22).

The core (agent, RAG, documents, web memory) imports nothing from here; this package
imports the core and plugs into it. Models stay in app.postgres.models, one metadata
for Alembic, so no table or migration moved with the code.

main.py plugs it in at two points, because FastAPI has two: register_routes() when the
app object is built, so the routes exist whether or not the lifespan runs (tests often
skip it), and register_services() as the last step of the lifespan, once the chat,
memory and agent services it builds on exist. Both import lazily: the agent still
reaches history_service through a shim until C4, and that must not load the rest.

Imports are always absolute (`app.discord`): the bot's `discord` library from pip is a
different package, and a script run with cwd=backend/app would shadow it.
"""
from __future__ import annotations

from typing import Any


def register_routes(app: Any, *, admin_guard: list[Any]) -> None:
    """The five Discord routers, all behind the admin guard. Their prefixes
    (/api/bot, /api/condensations, /api/memory-review, /api/discord/...) overlap no
    core route, so where they are included does not change which route answers."""
    from app.discord.routers import bot, condensations, history, memory_review, sessions

    for module in (bot, memory_review, condensations, sessions, history):
        app.include_router(module.router, dependencies=admin_guard)


def register_services(app: Any, settings: Any, postgres_sessions: Any, *, project_root: Any) -> None:
    """Build the Discord services onto app.state. Needs app.state.memory_service,
    chat_service and agent_service, so main.py calls it last in the lifespan."""
    from app.discord.bot_control_service import BotControlService
    from app.discord.condensation_service import DiscordCondensationService
    from app.discord.history_service import DiscordHistoryService
    from app.discord.memory_completion_service import DiscordMemoryCompletionService
    from app.discord.memory_review_service import DiscordMemoryReviewService
    from app.discord.session_service import DiscordSessionService
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
    state.discord_turn_service = DiscordTurnService(
        postgres_sessions,
        state.discord_session_service,
        state.chat_service,
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
    # The agent's search_history tool reads this attribute on every call; until C4
    # registers the tool from this package, the package hands the agent its backend.
    state.agent_service.history_service = state.discord_history_service
    # P3-2: dashboard start/stop for the compose-managed Discord bot.
    state.bot_control_service = BotControlService(project_root)
