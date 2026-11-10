"""TEMPORARY (review of review2 fix4, 10/11/2026, claude-fable-5-2): bot-side throwaway fixes
for A-5, A-6 and A-7, with today's fake-Discord numbering and with the numbering before
fix4's fifth change, plus one R5 mutation. No application or test file is edited: every
change is a monkeypatch for one test. REVIEW2_FX=<mode> picks one.

Copied into backend/tests only while it runs, then deleted; this is the kept copy.
"""
from __future__ import annotations

import __future__
import inspect
import os
import sys
import textwrap
from types import SimpleNamespace

import pytest

import review2_support as support
import test_review2_auth as au
import test_review2_tmp_bb135 as bb
from test_auth_api import auth_on, factory  # noqa: F401

MODE = os.environ.get("REVIEW2_FX", "")
r2 = support.r2
v2client = support.v2client
bot = bb.bot

test_a5_after_discord_refuses_an_answer_the_next_message_is_answered = \
    bb.test_a5_after_discord_refuses_an_answer_the_next_message_is_answered
test_a6_after_the_backend_fails_on_a_message_the_next_message_is_answered = \
    bb.test_a6_after_the_backend_fails_on_a_message_the_next_message_is_answered
test_a7_after_the_bot_stops_waiting_on_a_queued_turn_the_next_message_is_answered = \
    bb.test_a7_after_the_bot_stops_waiting_on_a_queued_turn_the_next_message_is_answered
test_r5_1_two_admins_demoting_each_other_at_once_leave_one_admin = \
    au.test_r5_1_two_admins_demoting_each_other_at_once_leave_one_admin


def recompile(monkeypatch, owner, name, edits):
    function = inspect.getattr_static(owner, name)
    function = getattr(function, "__func__", function)
    source = inspect.getsource(function)
    for old, new in edits:
        assert source.count(old) == 1, (name, old)
        source = source.replace(old, new)
    source = textwrap.dedent(source)
    module = sys.modules[function.__module__]
    local: dict[str, object] = {}
    exec(compile(source, f"<review2 fx {name}>", "exec", flags=__future__.annotations.compiler_flag,
                 dont_inherit=True), vars(module), local)
    monkeypatch.setattr(owner, name, local[name])


def old_numbering(monkeypatch):
    """BotOnApp.message as it was before fix4's fifth change: every fake side starts at 1001."""

    def message(self, question):
        source = self.fakes.FakeSource(self.fakes.Discord())
        source.id = int(support.snowflake())
        source.guild = SimpleNamespace(id=self.guild, name="review2", member_count=0, members=[])
        source.question = question
        return source

    monkeypatch.setattr(support.BotOnApp, "message", message)


def report_turns(monkeypatch, request):
    """After each ask, print the status of that message's turn and its delivery rows."""
    from sqlalchemy import text
    original = support.BotOnApp.ask
    client = request.getfixturevalue("r2").client

    async def ask(self, api, source, **kwargs):
        try:
            return await original(self, api, source, **kwargs)
        finally:
            row = support.turn_by_message(client, source.id)
            with client.app.state.postgres_sessions() as db:
                ids = [r[0] for r in db.execute(text(
                    "SELECT discord_message_id FROM discord_turn_deliveries WHERE turn_id = :t"),
                    {"t": row.id if row else None})] if row else []
            print(f"FX turn of {source.question!r}: status={row.status if row else None} "
                  f"reply_ids={ids} source_id={source.id}")

    monkeypatch.setattr(support.BotOnApp, "ask", ask)


# ── bot-side throwaway fixes ────────────────────────────────────────────────────

def a5_bot_retry(monkeypatch, request):
    """A-5: the bot tries Discord once more before it gives up, so message 1 is delivered."""
    import discord
    import discord_bot.main as bot_main
    original = bot_main.send_discord_answer

    async def send_discord_answer(channel, answer, **kwargs):
        try:
            return await original(channel, answer, **kwargs)
        except discord.HTTPException:
            return await original(channel, answer, **kwargs)

    monkeypatch.setattr(bot_main, "send_discord_answer", send_discord_answer)


def a5_bot_terminal(monkeypatch, request):
    """A-5: the bot reports the failed delivery as final, so the turn does not go back to the queue."""
    from discord_bot.main import DiscordConversationGateway
    original = DiscordConversationGateway.delivery_failed

    async def delivery_failed(self, prepared, error, *, retryable):
        await original(self, prepared, error, retryable=False)

    monkeypatch.setattr(DiscordConversationGateway, "delivery_failed", delivery_failed)


def a6_bot(monkeypatch, request):
    """A-6 (copied from flip/): the bot keeps asking within its waiting time on a 5xx."""
    from discord_bot.main import DiscordConversationGateway
    recompile(monkeypatch, DiscordConversationGateway, "prepare", [(
        "                execution = await self.api_client.execute_discord_turn(turn_id)\n",
        "                try:\n"
        "                    execution = await self.api_client.execute_discord_turn(turn_id)\n"
        "                except BackendUnavailableError:\n"
        "                    if monotonic() >= deadline:\n"
        "                        raise\n"
        "                    await asyncio.sleep(0.5)\n"
        "                    continue\n")])


def a7_bot_cancel(monkeypatch, request):
    """A-7: when the bot stops waiting on a turn, it cancels what it left open."""
    from discord_bot.api_client import BackendClientError
    from discord_bot.main import DiscordConversationGateway
    original = DiscordConversationGateway.prepare

    async def prepare(self, *args, **kwargs):
        try:
            return await original(self, *args, **kwargs)
        except BackendClientError as error:
            if "polling deadline" in str(error):
                await self.api_client._authorized_post(
                    "/api/discord/sessions/turns/cancel-open", {}, "Discord turn cleanup")
            raise

    monkeypatch.setattr(DiscordConversationGateway, "prepare", prepare)


def r5_both_refused(monkeypatch, request):
    """R5: a fix that is too strict, both demotions are refused with the service's own error."""
    from app.services.auth_service import AuthConflictError, AuthService

    def set_role(self, user_id, role):
        raise AuthConflictError("review2 fx mutation: refused")

    monkeypatch.setattr(AuthService, "set_role", set_role)


def _with_old(fix):
    def both(monkeypatch, request):
        old_numbering(monkeypatch)
        fix(monkeypatch, request)
    return both


MODES = {
    "a5_bot_retry": (a5_bot_retry, ("test_a5_",)),
    "a5_bot_retry_oldids": (_with_old(a5_bot_retry), ("test_a5_",)),
    "a5_bot_terminal": (a5_bot_terminal, ("test_a5_",)),
    "a6_bot": (a6_bot, ("test_a6_",)),
    "a6_bot_oldids": (_with_old(a6_bot), ("test_a6_",)),
    "a7_bot_cancel": (a7_bot_cancel, ("test_a7_",)),
    "r5_both_refused": (r5_both_refused, ("test_r5_1",)),
}


@pytest.fixture(autouse=True)
def fx(request, monkeypatch):
    fix, targets = MODES[MODE]
    name = request.node.originalname
    if not name.startswith(targets):
        pytest.skip(f"{MODE} does not target {name}")
    if name.startswith("test_a"):
        report_turns(monkeypatch, request)
    fix(monkeypatch, request)
