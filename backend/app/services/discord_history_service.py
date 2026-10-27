"""Temporary shim (ticket 22, C2 to C4): the module moved to app.discord.history_service.

The agent's search_history tool still imports history_hit_payload from here; C4 moves
that tool into the Discord package and deletes this file. Nothing else imports it, and
tests/test_discord_boundary.py allows exactly this one core file to import app.discord.
"""
from app.discord.history_service import history_hit_payload

__all__ = ["history_hit_payload"]
