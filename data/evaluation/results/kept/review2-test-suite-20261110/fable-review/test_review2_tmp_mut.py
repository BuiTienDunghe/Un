"""TEMPORARY (Fable review, 10/11/2026): guard cases of the review2 suite re-run with the
behaviour they guard deliberately broken by monkeypatch. Every test collected here must FAIL;
a pass means the guard does not watch what it claims. No application file is edited.
"""
from __future__ import annotations

import __future__
import inspect
import shutil
import sys
import textwrap

import pytest

from review2_support import r2, v2client  # noqa: F401
from test_auth_api import auth_on, factory  # noqa: F401
from test_review2_auth import demoted_admin  # noqa: F401
from test_review2_auth import test_r2_2_a_demoted_admin_with_an_old_token_is_refused_the_user_list  # noqa: F401
from test_review2_discord_turns import (  # noqa: F401
    test_a3_a_bot_returning_after_its_lease_ran_out_gets_the_saved_answer_without_a_second_model_call,
    test_n4_4_retrying_a_remember_turn_saves_one_source_and_says_so,
    test_r1_3_without_a_barrier_a_reply_is_answered,
    test_r3_3_resending_after_the_channel_barrier_moved_does_not_return_the_old_answer,
    test_r3_4_replaying_a_finished_turn,
)
from test_review2_ledger import (  # noqa: F401
    test_b1_the_bot_editing_its_progress_message_leaves_a_queued_turn_and_the_history_alone,
    test_b2_a_person_changing_a_message_in_the_history_keeps_its_old_words_out,
)
from test_review2_ocr_jobs import ocr, pdf_service  # noqa: F401
from test_review2_ocr_jobs import (  # noqa: F401
    test_c2_a_page_range_selects_exactly_its_pages_or_is_refused,
    test_r7_3_a_delete_never_reaches_outside_its_own_job_folder,
)
from test_review2_ocr_reader import (  # noqa: F401
    test_r9_4_a_phone_question_without_a_phone_number_is_answered_missing,
    test_r9_5_a_field_question_offers_its_field_and_nothing_else,
)


def recompile(monkeypatch, owner, name, edits):
    function = inspect.getattr_static(owner, name)
    function = getattr(function, "__func__", function)
    source = inspect.getsource(function)
    for old, new in edits:
        assert source.count(old) == 1, (name, old)
        source = source.replace(old, new)
    module = sys.modules[function.__module__]
    local: dict[str, object] = {}
    exec(compile(textwrap.dedent(source), f"<fable mutation {name}>", "exec",
                 flags=__future__.annotations.compiler_flag, dont_inherit=True), vars(module), local)
    patched = local[name]
    if isinstance(inspect.getattr_static(owner, name), staticmethod):
        patched = staticmethod(patched)
    monkeypatch.setattr(owner, name, patched)


def break_r7(monkeypatch, request):
    """The careless R7 fix: remove runs_path/job_id whatever job_id is."""
    from app.services.ocr_job_service import OcrJobService

    def delete(self, job_id):
        self.jobs.pop(job_id, None)
        shutil.rmtree(self.runs_path / job_id, ignore_errors=True)
        self.store.delete_ocr_run(job_id)

    monkeypatch.setattr(OcrJobService, "delete", delete)


def break_b2(monkeypatch, request):
    """A person's edit or delete no longer revokes anything."""
    from app.services.source_memory import SourceMemoryService
    monkeypatch.setattr(SourceMemoryService, "invalidate_in", lambda self, database, key, reader=None: None)


def break_b1(monkeypatch, request):
    """Undo the uncommitted fix B: a bot's own edit moves the channel barrier again."""
    from app.discord.history_service import DiscordHistoryService
    recompile(monkeypatch, DiscordHistoryService, "record_edit", [
        ("if self.source_memory and not row.is_bot:", "if self.source_memory:")])


def break_r9(monkeypatch, request):
    """The careless R9 fix: no label needed, any run of digits is a phone number, and every rule is unioned."""
    import app.services.ocr_reader as ocr_reader
    wide = ((ocr_reader.FIELD_RULES[0][0], r"", r"\d[\d ./()\-]{4,}\d"), *ocr_reader.FIELD_RULES[1:])
    monkeypatch.setattr(ocr_reader, "FIELD_RULES", wide)


def break_resend(monkeypatch, request):
    """A resend or a replay no longer checks the barrier."""
    from app.discord.turn_service import DiscordTurnService
    recompile(monkeypatch, DiscordTurnService, "execute", [
        ('response_text = "Nguồn trí nhớ đã được sửa hoặc quên. Vui lòng hỏi lại."', "response_text = response_text")])
    monkeypatch.setattr(DiscordTurnService, "_safe_replay", lambda self, result: result)


def break_reply(monkeypatch, request):
    """The reply target never reaches the model."""
    from app.discord.turn_service import DiscordTurnService
    monkeypatch.setattr(DiscordTurnService, "_resolve_reply_target", staticmethod(lambda repository, turn: None))


def break_pages(monkeypatch, request):
    """Out-of-range and malformed page ranges are silently clipped to the document."""
    from app.services.ocr_job_service import OcrJobService

    def select_pages(total, page_range):
        import re
        numbers = [int(n) for n in re.findall(r"\d+", page_range or "")]
        return sorted({n for n in numbers if 1 <= n <= total}) or list(range(1, total + 1))

    monkeypatch.setattr(OcrJobService, "_select_pages", staticmethod(select_pages))


def break_admin(monkeypatch, request):
    """require_admin trusts the token's role instead of the database."""
    import app.security.auth as auth

    def require_admin(request_):
        if auth.auth_enabled(request_) and auth.require_identity(request_).role != "admin":
            raise auth._forbidden()

    monkeypatch.setattr(auth, "require_admin", require_admin)
    app = request.getfixturevalue("client").app
    for route in app.routes:
        for dependency in getattr(getattr(route, "dependant", None), "dependencies", []):
            if getattr(dependency.call, "__name__", "") == "require_admin":
                dependency.call = require_admin


def break_saved_answer(monkeypatch, request):
    """A saved answer is thrown away, so a returning bot makes the model answer again."""
    from app.discord.turn_service import DiscordTurnService
    recompile(monkeypatch, DiscordTurnService, "execute", [
        ("            response_text = turn.response_text\n", "            response_text = None\n")])


def break_remember(monkeypatch, request):
    """A retried remember turn no longer tells the model it saved the source."""
    import app.discord.source_memory as discord_memory
    original = discord_memory.prepare_turn

    def prepare_turn(memory, session, turn):
        reader, receipt = original(memory, session, turn)
        return reader, ("" if turn.attempt_count > 1 else receipt)

    monkeypatch.setattr(discord_memory, "prepare_turn", prepare_turn)


MUTATIONS = [
    ("test_r7_3_", break_r7), ("test_b2_", break_b2), ("test_b1_", break_b1),
    ("test_r9_4_", break_r9), ("test_r9_5_", break_r9),
    ("test_r3_3_", break_resend), ("test_r3_4_", break_resend), ("test_r1_3_", break_reply),
    ("test_c2_", break_pages), ("test_r2_2_", break_admin), ("test_a3_", break_saved_answer),
    ("test_n4_4_", break_remember),
]


@pytest.fixture(autouse=True)
def mutation(request, monkeypatch):
    chosen = [breaker for prefix, breaker in MUTATIONS if request.node.originalname.startswith(prefix)]
    assert len(chosen) == 1, request.node.originalname
    chosen[0](monkeypatch, request)
