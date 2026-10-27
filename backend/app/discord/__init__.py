"""Discord: the bot's sessions, turns, channel history and the memory it extracts (ticket 22).

The core (agent, RAG, documents, web memory) imports nothing from here; this package
imports the core and plugs into it. Models stay in app.postgres.models, one metadata
for Alembic, so no table or migration moved with the code.

Imports are always absolute (`app.discord`): the bot's `discord` library from pip is a
different package, and a script run with cwd=backend/app would shadow it.
"""
