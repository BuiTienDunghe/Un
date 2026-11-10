"""TEMPORARY (review2 flip proof, 10/11/2026): every review2 xfail case re-run with a
throwaway fix applied by monkeypatch, to show the case turns XPASS(strict) once its bug is
fixed. Guard cases of the same area run under the same fix and must still pass.

No application file is edited: each fix wraps or re-compiles a function in memory for one
test. This file is deleted after the run; a copy is kept in
data/evaluation/results/kept/review2-test-suite-20261110/flip/.

REVIEW2_FLIP_A=bot picks bot-side fixes for A-6 and A-8 instead of the backend one.
"""
from __future__ import annotations

import __future__
import inspect
import json
import os
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from review2_support import r2, v2client  # noqa: F401
from test_auth_api import SECRET, auth_on, factory  # noqa: F401
from test_review2_auth import demoted_admin  # noqa: F401
from test_review2_auth import test_r2_1_a_demoted_admin_with_an_old_token_no_longer_sees_other_peoples_work  # noqa: F401
from test_review2_auth import test_r2_2_a_demoted_admin_with_an_old_token_is_refused_the_user_list  # noqa: F401
from test_review2_auth import test_r5_1_two_admins_demoting_each_other_at_once_leave_one_admin  # noqa: F401
from test_review2_bot_backend import bot  # noqa: F401
from test_review2_bot_backend import test_a5_after_discord_refuses_an_answer_the_next_message_is_answered  # noqa: F401
from test_review2_bot_backend import test_a6_after_the_backend_fails_on_a_message_the_next_message_is_answered  # noqa: F401
from test_review2_bot_backend import test_a7_after_the_bot_stops_waiting_on_a_queued_turn_the_next_message_is_answered  # noqa: F401
from test_review2_bot_backend import test_a8_after_the_bot_dies_mid_turn_and_restarts_the_next_message_is_answered  # noqa: F401
from test_review2_clocks import (test_f0_with_true_clocks_both_stories_behave,  # noqa: F401
                                 test_f1_discord_with_the_app_clock_30s_fast_forgotten_words_stay_out,
                                 test_f2_discord_with_the_app_clock_30s_slow_a_message_after_a_forget_is_answered,
                                 test_f3_search_history_with_discord_30s_off,
                                 test_f4_web_with_the_app_clock_30s_fast_forgotten_words_stay_out,
                                 test_f5_web_with_the_app_clock_30s_slow_what_was_said_after_a_forget_is_kept)
from test_review2_discord_turns import (  # noqa: F401
    test_n2_1_a_reply_to_an_edited_message_does_not_show_its_old_words,
    test_n2_2_a_reply_to_the_answer_of_an_edited_question_shows_neither,
    test_n4_1_retrying_a_forget_turn_tells_the_person_it_forgot,
    test_n4_2_resending_a_saved_forget_answer_returns_that_answer,
    test_n4_3_retrying_a_forget_turn_forgets_only_once,
    test_n4_4_retrying_a_remember_turn_saves_one_source_and_says_so,
    test_r1_1_a_reply_to_something_older_than_the_barrier_is_answered_without_its_words,
    test_r1_2_a_reply_to_something_newer_than_the_barrier_carries_its_words,
    test_r1_3_without_a_barrier_a_reply_is_answered,
    test_r1_4_a_reply_to_a_remembered_message_that_was_deleted_never_shows_its_words,
    test_r3_1_replaying_a_finished_turn_after_its_question_was_edited_does_not_return_the_old_answer,
    test_r3_2_resending_a_saved_answer_after_its_question_was_edited_does_not_return_it,
    test_r3_3_resending_after_the_channel_barrier_moved_does_not_return_the_old_answer,
    test_r3_4_replaying_a_finished_turn,
)
from test_review2_ocr_access import job_of_a  # noqa: F401
from test_review2_ocr_access import test_e1_a_member_cannot_reach_another_members_ocr_job  # noqa: F401
from test_review2_ocr_access import test_e2_the_owner_an_admin_and_the_service_key_open_the_job_and_nobody_else_without_signing_in  # noqa: F401
from test_review2_ocr_jobs import ocr, pdf_service  # noqa: F401
from test_review2_ocr_jobs import (test_c1_a_huge_page_range_is_refused_without_building_it,  # noqa: F401
                                   test_c2_a_page_range_selects_exactly_its_pages_or_is_refused,
                                   test_r6_1_a_job_deleted_while_running_never_comes_back,
                                   test_r6_2_a_finished_job_deleted_is_gone_from_history_and_disk,
                                   test_r7_1_a_job_deleted_right_after_a_restart_leaves_no_folder,
                                   test_r7_2_a_job_opened_after_a_restart_then_deleted_leaves_no_folder,
                                   test_r7_3_a_delete_never_reaches_outside_its_own_job_folder,
                                   test_r7_4_a_stored_root_outside_the_runs_folder_is_never_deleted,
                                   test_r7_5_a_file_held_open_during_a_delete_is_gone_after_a_later_delete,
                                   test_r8_1_an_out_of_range_dpi_never_runs_a_job_at_that_dpi,
                                   test_r8_2_a_dpi_in_range_makes_a_job)
from test_review2_ocr_reader import (test_r9_1_asking_for_phone_and_email_offers_both,  # noqa: F401
                                     test_r9_2_a_phone_number_written_another_way_reaches_the_model,
                                     test_r9_3_a_question_about_a_phone_model_is_not_a_phone_number_question,
                                     test_r9_3_asking_for_an_e_mail_the_document_lacks_is_answered_missing,
                                     test_r9_4_a_phone_question_without_a_phone_number_is_answered_missing,
                                     test_r9_5_a_field_question_offers_its_field_and_nothing_else)


def recompile(monkeypatch, owner, name, edits, **extra):
    """Replace owner.name with a copy of its source with `edits` applied; the copy keeps the
    real module as its globals, and `extra` names are added to that module for this test."""
    function = inspect.getattr_static(owner, name)
    function = getattr(function, "__func__", function)
    source = inspect.getsource(function)  # edits are written with the file's own indentation
    for old, new in edits:
        assert source.count(old) == 1, (name, old)
        source = source.replace(old, new)
    source = textwrap.dedent(source)
    module = sys.modules[function.__module__]
    for key, value in extra.items():
        monkeypatch.setattr(module, key, value, raising=False)
    local: dict[str, object] = {}
    exec(compile(source, f"<review2 flip {name}>", "exec", flags=__future__.annotations.compiler_flag,
                 dont_inherit=True), vars(module), local)
    patched = local[name]
    if isinstance(inspect.getattr_static(owner, name), staticmethod):
        patched = staticmethod(patched)
    monkeypatch.setattr(owner, name, patched)


# ── one throwaway fix per code ──────────────────────────────────────────────────

def fix_r1(monkeypatch, request):
    """Each reply target carries the creation time of the turn it came from."""
    from app.discord.speaker_context import BotReplyTargetContext, ReplyTargetContext
    from app.discord.turn_service import DiscordTurnService
    never = datetime.max.replace(tzinfo=UTC)

    @dataclass(frozen=True)
    class Dated(ReplyTargetContext):
        created_at: datetime = never

    @dataclass(frozen=True)
    class DatedBot(BotReplyTargetContext):
        created_at: datetime = never

    original = DiscordTurnService._resolve_reply_target

    def dated(repository, turn):
        target = original(repository, turn)
        if target is None:
            return None
        if isinstance(target, BotReplyTargetContext):
            _, origin = repository.find_bot_response_delivery(
                turn.session_id, target.discord_response_message_id, before_sequence=turn.sequence_number)
            return DatedBot(**{f.name: getattr(target, f.name) for f in fields(BotReplyTargetContext)},
                            created_at=origin.created_at)
        row = repository.find_reply_target_turn(turn.session_id, target.discord_message_id,
                                                before_sequence=turn.sequence_number)
        return Dated(**{f.name: getattr(target, f.name) for f in fields(ReplyTargetContext)},
                     created_at=row.created_at if row is not None else never)

    monkeypatch.setattr(DiscordTurnService, "_resolve_reply_target", staticmethod(dated))


def fix_n2(monkeypatch, request):
    """A reply target whose message (or whose question) was edited or deleted is dropped."""
    from app.discord.speaker_context import BotReplyTargetContext
    from app.discord.turn_service import DiscordTurnService
    memory = request.getfixturevalue("r2").memory
    original = DiscordTurnService._resolve_reply_target

    def undeleted(repository, turn):
        target = original(repository, turn)
        if target is None:
            return None
        if isinstance(target, BotReplyTargetContext):
            _, origin = repository.find_bot_response_delivery(
                turn.session_id, target.discord_response_message_id, before_sequence=turn.sequence_number)
            key = f"discord:{origin.discord_message_id}"
        else:
            key = f"discord:{target.discord_message_id}"
        return None if memory.is_retracted(key) else target

    monkeypatch.setattr(DiscordTurnService, "_resolve_reply_target", staticmethod(undeleted))


def fix_r3(monkeypatch, request):
    """A replayed or resent answer is withheld once its question carries a tombstone."""
    from app.discord.turn_service import DiscordTurnService
    from app.postgres.models import DiscordSessionTurn
    memory = request.getfixturevalue("r2").memory
    original = DiscordTurnService.execute

    def execute(self, turn_id):
        result = original(self, turn_id)
        if result.answer:
            with self.sessions() as database:
                turn = database.get(DiscordSessionTurn, turn_id)
            if turn is not None and memory.is_retracted(f"discord:{turn.discord_message_id}"):
                result = replace(result, answer="Nguồn trí nhớ đã được sửa hoặc quên. Vui lòng hỏi lại.")
        return result

    monkeypatch.setattr(DiscordTurnService, "execute", execute)


def fix_n4(monkeypatch, request):
    """A forget turn tried again recognises its own forget: it reports it instead of calling
    itself stale, and a saved answer is resent only when the turn really is stale."""
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


def fix_a_backend(monkeypatch, request):
    """The backend gives up on a queued head nobody has touched for ten minutes."""
    from app.discord.repositories import DiscordSessionRepository
    from app.postgres.models import DiscordSessionTurn
    original = DiscordSessionRepository.claim_turn

    def claim_turn(self, turn_id, worker_id, *, lease_seconds):
        target = self.session.get(DiscordSessionTurn, turn_id)
        if target is not None:
            now = datetime.now(UTC)
            for head in self.session.scalars(select(DiscordSessionTurn).where(
                    DiscordSessionTurn.session_id == target.session_id, DiscordSessionTurn.id != turn_id,
                    DiscordSessionTurn.status == "queued", DiscordSessionTurn.attempt_count >= 1,
                    DiscordSessionTurn.updated_at < now - timedelta(minutes=10))):
                head.status, head.completed_at, head.error, head.updated_at = "failed", now, "abandoned", now
            self.session.flush()
        return original(self, turn_id, worker_id, lease_seconds=lease_seconds)

    monkeypatch.setattr(DiscordSessionRepository, "claim_turn", claim_turn)


def fix_a_bot(monkeypatch, request):
    """The bot keeps asking within its waiting time when the backend answers 5xx."""
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


def fix_a_bot_restart(monkeypatch, request):
    """The bot cancels the turns left open by its previous life when it starts."""
    import discord_bot.main as bot_main
    original = bot_main.create_bot

    def create_bot(api_client, *args, **kwargs):
        bot = original(api_client, *args, **kwargs)
        ready = bot.on_ready

        async def on_ready():
            await api_client._authorized_post("/api/discord/sessions/turns/cancel-open", {}, "Discord turn cleanup")
            await ready()

        bot.on_ready = on_ready
        return bot

    monkeypatch.setattr(bot_main, "create_bot", create_bot)


def _database_now(sessions):
    with sessions() as database:
        return database.scalar(select(func.clock_timestamp()))


def fix_f_discord(monkeypatch, request):
    """A turn is stamped with Postgres time, the clock its barriers use."""
    from app.discord.repositories import DiscordSessionRepository
    original = DiscordSessionRepository.enqueue_turn

    def enqueue_turn(self, *args, **kwargs):
        turn, created = original(self, *args, **kwargs)
        if created:
            turn.created_at = self.session.scalar(select(func.clock_timestamp()))
        return turn, created

    monkeypatch.setattr(DiscordSessionRepository, "enqueue_turn", enqueue_turn)


def fix_f_web(monkeypatch, request):
    """Web messages are stamped with Postgres time, the clock its barriers use."""
    from app.services.chat_service import ChatService
    from app.stores.postgres_auxiliary_store import PostgresAuxiliaryStore
    recompile(monkeypatch, ChatService, "_respond", [("sent_at = datetime.now(UTC)",
                                                      "sent_at = _review2_now(self.source_memory.sessions)")],
              _review2_now=_database_now)
    original = PostgresAuxiliaryStore.add_message

    def add_message(self, conversation_id, role, content, model_used=None, sources=None, *, created_at=None):
        stamp = created_at or _database_now(self._sessions)
        return original(self, conversation_id, role, content, model_used, sources, created_at=stamp)

    monkeypatch.setattr(PostgresAuxiliaryStore, "add_message", add_message)


def fix_f_search(monkeypatch, request):
    """search_history compares the ledger's arrival time (Postgres) with the barrier."""
    from app.discord.source_memory import ScopedSearchHistory
    recompile(monkeypatch, ScopedSearchHistory, "__call__", [(
        "conditions.append(DiscordChannelMessage.sent_at > barrier)",
        "conditions.append(DiscordChannelMessage.created_at > barrier)")])


def fix_r2(monkeypatch, request):
    """The role of a signed-in user is read from the database on every request."""
    import app.security.auth as auth
    from app.postgres.models import User
    original = auth._resolve

    def resolve(request_):
        identity = original(request_)
        if identity.is_user:
            with request_.app.state.postgres_sessions() as database:
                user = database.get(User, UUID(identity.user_id))
            if user is None:
                raise auth._unauthorized("TOKEN_INVALID", "gone")
            identity = replace(identity, role=user.role)
        return identity

    monkeypatch.setattr(auth, "_resolve", resolve)


def fix_r5(monkeypatch, request):
    """set_role takes one advisory lock before it counts the admins."""
    from app.services.auth_service import AuthService
    recompile(monkeypatch, AuthService, "set_role", [(
        "            user = database.get(User, UUID(user_id))\n",
        "            database.execute(select(func.pg_advisory_xact_lock(7_202_611)))\n"
        "            user = database.get(User, UUID(user_id))\n")])


def fix_r6_r7(monkeypatch, request):
    """Delete only ocr_<32 hex> under runs_path; a deleted job is never saved again."""
    from app.services.ocr_job_service import OcrJobService
    original_save = OcrJobService._save

    def delete(self, job_id):
        if not re.fullmatch(r"ocr_[0-9a-f]{32}", job_id):
            return
        with self._lock:
            self.__dict__.setdefault("_review2_deleted", set()).add(job_id)
        self.jobs.pop(job_id, None)
        shutil.rmtree(self.runs_path / job_id, ignore_errors=True)
        self.store.delete_ocr_run(job_id)

    def save(self, job):
        if str(job["id"]) not in self.__dict__.get("_review2_deleted", set()):
            original_save(self, job)

    monkeypatch.setattr(OcrJobService, "delete", delete)
    monkeypatch.setattr(OcrJobService, "_save", save)


def fix_r8(monkeypatch, request):
    """A dpi outside 72-400 is refused before a job exists."""
    from app.services.ocr_job_service import OcrJobService
    original = OcrJobService.create

    async def create(self, file, dpi, page_range, output_format, force_ocr=False):
        if not 72 <= int(dpi) <= 400:
            raise ValueError("DPI must be within 72-400")
        return await original(self, file, dpi, page_range, output_format, force_ocr)

    monkeypatch.setattr(OcrJobService, "create", create)


def fix_c(monkeypatch, request):
    """Each part of a page range is checked against the page count before it is expanded."""
    from app.services.ocr_job_service import OcrJobService

    def select_pages(total, page_range):
        if not page_range:
            return list(range(1, total + 1))
        selected = set()
        for part in page_range.split(","):
            bounds = [int(item.strip()) for item in part.split("-")]
            if len(bounds) > 2:
                raise ValueError("Invalid page range")
            start, end = bounds[0], bounds[-1]
            if start < 1 or end > total or start > end:
                raise ValueError(f"Page range must be within 1-{total}")
            selected.update(range(start, end + 1))
        return sorted(selected)

    monkeypatch.setattr(OcrJobService, "_select_pages", staticmethod(select_pages))


def fix_e(monkeypatch, request):
    """An outer gate records who made each OCR job; a member reaches only their own."""
    import jwt
    from starlette.responses import JSONResponse
    app = request.getfixturevalue("client").app
    inner = app.middleware_stack
    assert inner is not None
    owners: dict[str, str] = {}

    def caller(scope):
        header = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
        if not header.lower().startswith("bearer "):
            return None, None
        claims = jwt.decode(header[7:], SECRET, algorithms=["HS256"])
        return claims.get("sub"), claims.get("role")

    async def gate(scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/ocr/"):
            return await inner(scope, receive, send)
        user, role = caller(scope)
        member = user is not None and role != "admin"
        parts = scope["path"].split("/")
        if member and len(parts) > 4 and parts[3] == "jobs" and owners.get(parts[4], user) != user:
            return await JSONResponse({"error_code": "OCR_JOB_NOT_FOUND"}, status_code=404)(scope, receive, send)
        if scope["path"] in ("/api/ocr/jobs", "/api/ocr/history") and (member or scope["method"] == "POST"):
            start, chunks = {}, []

            async def hold(message):
                if message["type"] == "http.response.start":
                    start.update(message)
                    return
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = b"".join(chunks)
                if scope["path"] == "/api/ocr/jobs" and start.get("status") == 201:
                    owners[json.loads(body)["id"]] = user
                elif scope["path"] == "/api/ocr/history" and member:
                    data = json.loads(body)
                    data["runs"] = [run for run in data["runs"] if owners.get(run["id"], user) == user]
                    body = json.dumps(data).encode()
                headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
                await send({**start, "headers": [*headers, (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})

            return await inner(scope, receive, hold)
        return await inner(scope, receive, send)

    monkeypatch.setattr(app, "middleware_stack", gate)


R9_RULES = (
    (r"dien thoai|\bsdt\b|\bphone\b(?!\s+model)|telephone",
     r"dien thoai|\bsdt\b|\bdt\b|phone|telephone|\btel\b|di dong|hotline|mobile", r"\+?\(?\d[\d ()+.\-]{6,18}\d"),
    (r"\be-?mail\b|thu dien tu", r"", r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}"),
    (r"so tai khoan|\bstk\b|account number", r"tai khoan|\bstk\b|account", r"(?<!\d)\d[\d .\-]{4,28}\d(?!\d)"),
)


def fix_r9(monkeypatch, request):
    """Every matching field rule counts, with wider phone labels and international numbers."""
    import app.services.ocr_reader as ocr_reader
    import test_review2_ocr_reader as reader_tests
    recompile(monkeypatch, ocr_reader, "read_evidence", [(
        "    field_rule = next((rule for rule in FIELD_RULES if re.search(rule[0], folded(question))), None)\n"
        "    if field_rule:\n"
        "        _, label, value = field_rule\n"
        "        eligible = [block for block in eligible if (not label or re.search(label, folded(block[\"text\"])))\n"
        "                    and re.search(value, block[\"text\"], re.I)]\n",
        "    rules = [rule for rule in _review2_rules if re.search(rule[0], folded(question))]\n"
        "    field_rule = rules[0] if rules else None\n"
        "    if rules:\n"
        "        eligible = [block for block in eligible if any((not label or re.search(label, folded(block[\"text\"])))\n"
        "                    and re.search(value, block[\"text\"], re.I) for _, label, value in rules)]\n")],
        _review2_rules=R9_RULES)
    monkeypatch.setattr(reader_tests, "read_evidence", ocr_reader.read_evidence)


FIXES = [
    ("test_r1_", fix_r1), ("test_n2_", fix_n2), ("test_r3_", fix_r3), ("test_n4_", fix_n4),
    ("test_a5_", fix_a_backend), ("test_a7_", fix_a_backend),
    ("test_a6_", fix_a_bot if os.environ.get("REVIEW2_FLIP_A") == "bot" else fix_a_backend),
    ("test_a8_", fix_a_bot_restart if os.environ.get("REVIEW2_FLIP_A") == "bot" else fix_a_backend),
    ("test_f0_", fix_f_discord), ("test_f1_", fix_f_discord), ("test_f2_", fix_f_discord),
    ("test_f3_", fix_f_search), ("test_f4_", fix_f_web), ("test_f5_", fix_f_web),
    ("test_r2_", fix_r2), ("test_r5_", fix_r5),
    ("test_r6_", fix_r6_r7), ("test_r7_", fix_r6_r7), ("test_r8_", fix_r8), ("test_c1_", fix_c), ("test_c2_", fix_c),
    ("test_e1_", fix_e), ("test_e2_", fix_e), ("test_r9_", fix_r9),
]


@pytest.fixture(autouse=True)
def throwaway_fix(request, monkeypatch):
    name = request.node.originalname
    chosen = [fix for prefix, fix in FIXES if name.startswith(prefix)]
    assert len(chosen) == 1, name
    chosen[0](monkeypatch, request)
