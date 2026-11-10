"""TEMPORARY (review2 fix4, 10/11/2026): mutations aimed at the four checks added after
Fable's review. Each mutation breaks something the new check guards; the case must FAIL with
the new check's own error (not KnownBug, not XPASS(strict)), except N4-1, which must stay
xfail (KnownBug) or fail, never XPASS.

REVIEW2_FIX4=<mode> picks the mutation. REVIEW2_FIX4_SOURCE=old runs the same mutation on the
test code as it was before the four fixes (copies named *_tmp_old_*), for contrast.

No application file is edited: every mutation is a monkeypatch for one test. This file and
the old copies are deleted after the run; a copy is kept in
data/evaluation/results/kept/review2-test-suite-20261110/fix4/.
"""
from __future__ import annotations

import __future__
import importlib
import inspect
import os
import sys
import textwrap
import threading
from dataclasses import replace

import pytest

MODE = os.environ.get("REVIEW2_FIX4", "")
SOURCE = os.environ.get("REVIEW2_FIX4_SOURCE", "new")
_names = {"new": ("review2_support", "test_review2_bot_backend", "test_review2_auth", "test_review2_discord_turns"),
          "old": ("review2_tmp_old_support", "test_review2_tmp_old_bot_backend", "test_review2_tmp_old_auth",
                  "test_review2_tmp_old_discord_turns")}[SOURCE]
support, bb, au, dt = (importlib.import_module(name) for name in _names)

from test_auth_api import auth_on, factory  # noqa: E402,F401

r2 = support.r2
v2client = support.v2client
bot = bb.bot

test_a5_after_discord_refuses_an_answer_the_next_message_is_answered = \
    bb.test_a5_after_discord_refuses_an_answer_the_next_message_is_answered
test_a6_after_the_backend_fails_on_a_message_the_next_message_is_answered = \
    bb.test_a6_after_the_backend_fails_on_a_message_the_next_message_is_answered
test_a7_after_the_bot_stops_waiting_on_a_queued_turn_the_next_message_is_answered = \
    bb.test_a7_after_the_bot_stops_waiting_on_a_queued_turn_the_next_message_is_answered
test_a8_after_the_bot_dies_mid_turn_and_restarts_the_next_message_is_answered = \
    bb.test_a8_after_the_bot_dies_mid_turn_and_restarts_the_next_message_is_answered
test_r5_1_two_admins_demoting_each_other_at_once_leave_one_admin = \
    au.test_r5_1_two_admins_demoting_each_other_at_once_leave_one_admin
test_r3_1_replaying_a_finished_turn_after_its_question_was_edited_does_not_return_the_old_answer = \
    dt.test_r3_1_replaying_a_finished_turn_after_its_question_was_edited_does_not_return_the_old_answer
test_r3_2_resending_a_saved_answer_after_its_question_was_edited_does_not_return_it = \
    dt.test_r3_2_resending_a_saved_answer_after_its_question_was_edited_does_not_return_it
test_n4_1_retrying_a_forget_turn_tells_the_person_it_forgot = \
    dt.test_n4_1_retrying_a_forget_turn_tells_the_person_it_forgot


# ── copied from flip/test_review2_tmp_flip.py (the N4 throwaway fix) ────────────

def recompile(monkeypatch, owner, name, edits, **extra):
    function = inspect.getattr_static(owner, name)
    function = getattr(function, "__func__", function)
    source = inspect.getsource(function)
    for old, new in edits:
        assert source.count(old) == 1, (name, old)
        source = source.replace(old, new)
    source = textwrap.dedent(source)
    module = sys.modules[function.__module__]
    for key, value in extra.items():
        monkeypatch.setattr(module, key, value, raising=False)
    local: dict[str, object] = {}
    exec(compile(source, f"<review2 fix4 {name}>", "exec", flags=__future__.annotations.compiler_flag,
                 dont_inherit=True), vars(module), local)
    patched = local[name]
    if isinstance(inspect.getattr_static(owner, name), staticmethod):
        patched = staticmethod(patched)
    monkeypatch.setattr(owner, name, patched)


def fix_n4(monkeypatch, request):
    import app.discord.source_memory as discord_memory
    from app.discord.turn_service import DiscordTurnService
    from app.services.agent_service import IMAGE_NOTE
    from app.services.source_memory import explicit_forget
    original = discord_memory.prepare_turn

    def prepare_turn(memory, session, turn):
        if explicit_forget(turn.request_text.split(IMAGE_NOTE, 1)[0]) and turn.attempt_count > 1:
            return discord_memory.reader_for(session, turn), "Backend đã quên các nguồn về người đang nói ở lần thử trước."
        return original(memory, session, turn)

    monkeypatch.setattr(discord_memory, "prepare_turn", prepare_turn)
    recompile(monkeypatch, DiscordTurnService, "execute", [(
        "if barrier and response_text is not None and turn.created_at <= barrier:",
        "if barrier and response_text is not None and turn.created_at <= barrier and stale:")])


# ── the mutations ───────────────────────────────────────────────────────────────

def a_msg2(monkeypatch, request):
    """The bot crashes on something unrelated right after message 2 was queued."""
    from discord_bot.api_client import LocalAgentClient
    original = LocalAgentClient.enqueue_discord_turn

    async def enqueue(self, session_id, discord_message_id, message, **kwargs):
        turn = await original(self, session_id, discord_message_id, message, **kwargs)
        if "tin thứ hai" in message:
            raise RuntimeError("review2 fix4 mutation: unrelated bot crash after message 2 was queued")
        return turn

    monkeypatch.setattr(LocalAgentClient, "enqueue_discord_turn", enqueue)


def a_msg1(monkeypatch, request):
    """The bot crashes on something unrelated while handling message 1, after its execute
    call came back (so the injected backend fault fired, or the model was asked)."""
    from discord_bot.api_client import LocalAgentClient
    original_enqueue, original_execute = LocalAgentClient.enqueue_discord_turn, LocalAgentClient.execute_discord_turn
    first_turns: set[str] = set()

    async def enqueue(self, session_id, discord_message_id, message, **kwargs):
        turn = await original_enqueue(self, session_id, discord_message_id, message, **kwargs)
        if "tin thứ nhất" in message:
            first_turns.add(str(turn.turn_id))
        return turn

    async def execute(self, turn_id):
        try:
            return await original_execute(self, turn_id)
        finally:
            if str(turn_id) in first_turns:
                raise RuntimeError("review2 fix4 mutation: unrelated bot crash while handling message 1")

    monkeypatch.setattr(LocalAgentClient, "enqueue_discord_turn", enqueue)
    monkeypatch.setattr(LocalAgentClient, "execute_discord_turn", execute)


def a5_msg1(monkeypatch, request):
    """A-5: after Discord refused the answer and the bot reported it, the bot crashes on
    something unrelated instead of re-raising Discord's error."""
    from discord_bot.main import DiscordConversationGateway
    original = DiscordConversationGateway.delivery_failed

    async def delivery_failed(self, *args, **kwargs):
        await original(self, *args, **kwargs)
        raise RuntimeError("review2 fix4 mutation: unrelated bot crash after reporting the failed delivery")

    monkeypatch.setattr(DiscordConversationGateway, "delivery_failed", delivery_failed)


def r5_one(monkeypatch, request):
    """One demotion dies on an unrelated error before it starts; the other goes through."""
    from app.services.auth_service import AuthService
    original, lock, calls = AuthService.set_role, threading.Lock(), []

    def set_role(self, user_id, role):
        with lock:
            calls.append(user_id)
            first = len(calls) == 1
        if first:
            raise RuntimeError("review2 fix4 mutation: unrelated error in one demotion")
        return original(self, user_id, role)

    monkeypatch.setattr(AuthService, "set_role", set_role)


def r5_both(monkeypatch, request):
    """Both demotions lose their database connection (a fabricated error; no real
    connection is broken, so no URL reaches the log)."""
    from sqlalchemy.exc import OperationalError
    from app.services.auth_service import AuthService

    def set_role(self, user_id, role):
        raise OperationalError("UPDATE users SET role=...", {},
                               ConnectionResetError("review2 fix4 mutation: connection lost"))

    monkeypatch.setattr(AuthService, "set_role", set_role)


def _r3(status):
    def mutate(monkeypatch, request):
        """The replay or resend of a turn whose question carries a tombstone is answered
        with HTTP `status` (500: the server crashed; 409: a refusal, which is a valid fix)."""
        from fastapi import HTTPException
        from app.discord.turn_service import DiscordTurnService
        from app.postgres.models import DiscordSessionTurn
        memory = request.getfixturevalue("r2").memory
        original = DiscordTurnService.execute

        def execute(self, turn_id):
            with self.sessions() as database:
                turn = database.get(DiscordSessionTurn, turn_id)
            if turn is not None and memory.is_retracted(f"discord:{turn.discord_message_id}"):
                raise HTTPException(status_code=status, detail={"error_code": "REVIEW2_FIX4_MUTATION",
                                                                "message": f"mutation {status}"})
            return original(self, turn_id)

        monkeypatch.setattr(DiscordTurnService, "execute", execute)
    return mutate


def n4_appended(monkeypatch, request):
    """The N4 throwaway fix, but the retried turn's answer is the stale sentence with a
    forget receipt appended."""
    from app.discord.source_memory import STALE_TURN_REPLY
    from app.discord.turn_service import DiscordTurnService
    fix_n4(monkeypatch, request)
    patched = DiscordTurnService.execute

    def execute(self, turn_id):
        result = patched(self, turn_id)
        if result.answer:
            result = replace(result, answer=STALE_TURN_REPLY + " Ún đã quên những gì bạn nhờ nhớ.")
        return result

    monkeypatch.setattr(DiscordTurnService, "execute", execute)


def n4_exact(monkeypatch, request):
    """The N4 throwaway fix (its receipt "đã quên" reaches the model), but the model answers
    exactly the stale sentence."""
    from app.discord.source_memory import STALE_TURN_REPLY
    fix_n4(monkeypatch, request)
    request.getfixturevalue("r2").model.rules.append(("Hãy quên", STALE_TURN_REPLY))


MUTATIONS = {
    "a_msg2": (a_msg2, ("test_a5_", "test_a6_", "test_a7_", "test_a8_")),
    "a_msg1": (a_msg1, ("test_a6_", "test_a7_")),
    "a5_msg1": (a5_msg1, ("test_a5_",)),
    "r5_one": (r5_one, ("test_r5_1",)),
    "r5_both": (r5_both, ("test_r5_1",)),
    "r3_500": (_r3(500), ("test_r3_1", "test_r3_2")),
    "r3_409": (_r3(409), ("test_r3_1", "test_r3_2")),
    "n4_appended": (n4_appended, ("test_n4_1",)),
    "n4_exact": (n4_exact, ("test_n4_1",)),
}


@pytest.fixture(autouse=True)
def mutation(request, monkeypatch):
    mutate, targets = MUTATIONS[MODE]
    name = request.node.originalname
    if not name.startswith(targets):
        pytest.skip(f"{MODE} does not target {name}")
    mutate(monkeypatch, request)
