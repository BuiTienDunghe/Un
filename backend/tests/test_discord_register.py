"""app.discord plugs into the app at two points (ticket 22, C3), checked without a database.

The suite's lifespan tests need POSTGRES_TEST_URL, so on a machine without one nothing
would show that main.py still builds the Discord services, or builds them after the
services they depend on. These tests build them onto a stand-in app instead.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI

from app import discord
from app.config.settings import PROJECT_ROOT, Settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.services.agent_service import core_tools

MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"
DISCORD_STATE = (
    "discord_session_service", "memory_review_service", "condensation_service",
    "discord_turn_service", "discord_history_service", "bot_control_service",
)


def test_register_services_builds_every_discord_service_and_plugs_search_history_into_the_agent():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://test:test@127.0.0.1:1/none")
    sessions = create_session_factory(create_postgres_engine(str(settings.database_url)))  # never connects here
    agent = SimpleNamespace(registry=core_tools())
    chat = object()
    app = SimpleNamespace(state=SimpleNamespace(memory_service=object(), chat_service=chat, agent_service=agent))

    discord.register_services(app, settings, sessions, project_root=PROJECT_ROOT)

    assert [name for name in DISCORD_STATE if not hasattr(app.state, name)] == []
    # The agent's Discord tool, in the place it always had (ticket 22, C4), reading this guild history.
    assert agent.registry.names() == ("search_documents", "read_document", "search_history", "system_status")
    assert agent.registry.get("search_history").run.history_service is app.state.discord_history_service
    assert app.state.discord_turn_service.chat_service is chat


def test_register_routes_mounts_the_five_routers_behind_the_admin_guard():
    app = FastAPI()
    discord.register_routes(app, admin_guard=[])
    prefixes = {path.split("/")[2] if not path.startswith("/api/discord") else "/".join(path.split("/")[2:4])
                for path in app.openapi()["paths"]}
    assert prefixes == {"bot", "condensations", "memory-review", "discord/sessions", "discord/history"}


def test_main_builds_the_discord_services_after_the_agent_and_includes_the_routes_once():
    source = MAIN.read_text(encoding="utf-8")
    lifespan = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan")
    body = ast.get_source_segment(source, lifespan)
    assert body.index("discord.register_services(") > body.index("app.state.agent_service = AgentService(")
    assert source.count("discord.register_routes(") == 1 and source.count("discord.register_services(") == 1
