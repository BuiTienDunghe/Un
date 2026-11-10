"""Shared helpers for the review2 regression suite (second outside review, 10/11/2026).

Every review2 test states one situation a person can cause and the outcome they must see.
A test for a bug that is not fixed yet carries
``@pytest.mark.xfail(strict=True, raises=KnownBug, reason="review2 <code>: ...")``.
``KnownBug`` is raised only by ``known_bug`` on the line that checks the symptom; every
precondition uses a plain ``assert``, so a broken precondition is a real failure, never an
expected one. When the bug is fixed the test passes, ``strict`` turns the run red, and the
person who fixed it removes the mark.

Codes: data/evaluation/results/kept/review2-test-suite-20261110/BRIEF.md.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from test_source_memory_discord import v2client  # noqa: F401  (fixture, re-exported)

REPO_ROOT = Path(__file__).resolve().parents[2]
DISCORD_EPOCH_MS = 1_420_070_400_000
DEFAULT_ANSWER = "Đã xử lý theo nguồn hiện tại."


class KnownBug(AssertionError):
    """The symptom of a known, not yet fixed review2 bug."""


def known_bug(condition: bool, message: str) -> None:
    """The only place a KnownBug is raised: the line that checks the symptom."""
    if not condition:
        raise KnownBug(message)


def prompt_text(messages) -> str:
    return json.dumps(messages, ensure_ascii=False)


# ── The model the backend talks to ──────────────────────────────────────────────

class FakeModel:
    """Stands in for OllamaClient.chat. Records every prompt. Fails the next `failures` calls;
    otherwise answers by the first rule whose marker is in the current (last) message, then
    from the `answers` queue, then with DEFAULT_ANSWER."""

    def __init__(self, calls: list) -> None:
        self.calls = calls
        self.answers: list[str] = []
        self.rules: list[tuple[str, str]] = []
        self.failures = 0

    def __call__(self, messages) -> str:
        self.calls.append(messages)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("review2: model unavailable")
        current = prompt_text(messages[-1:])
        for marker, answer in self.rules:
            if marker in current:
                return answer
        return self.answers.pop(0) if self.answers else DEFAULT_ANSWER

    def prompts_since(self, index: int) -> str:
        return "\n".join(prompt_text(messages) for messages in self.calls[index:])


@pytest.fixture
def r2(v2client, monkeypatch):  # noqa: F811
    """The real app on Postgres in source-memory mode (v2client), with a scriptable model."""
    client, captured, guild = v2client
    fake = FakeModel(captured)
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.chat",
                        lambda self, model, messages, options, keep_alive, think=None: fake(messages))
    return SimpleNamespace(client=client, guild=guild, model=fake,
                           turns=client.app.state.discord_turn_service,
                           memory=client.app.state.source_memory_service)


# ── Discord turns over HTTP ─────────────────────────────────────────────────────

def snowflake(at: datetime | None = None) -> str:
    """A Discord message id stamped at `at` (default: now), unique in its low bits."""
    moment = at or datetime.now(UTC)
    millis = int(moment.timestamp() * 1000)
    return str(((millis - DISCORD_EPOCH_MS) << 22) + int(uuid4().hex[:5], 16))


def session_of(client, guild: str, channel: str) -> str:
    resolved = client.post("/api/discord/sessions/resolve", json={
        "guild_id": guild, "channel_id": channel, "thread_id": None})
    assert resolved.status_code == 200, resolved.text
    return resolved.json()["session_id"]


def enqueue(client, guild: str, channel: str, body: str, *, reply_to: str | None = None,
            author: str = "alice", message_id: str | None = None) -> tuple[str, str]:
    message_id = message_id or snowflake()
    payload = {"discord_message_id": message_id, "message": body, "author_id": author,
               "author_display_name": author.title()}
    if reply_to:
        payload["reply_to_discord_message_id"] = reply_to
    created = client.post(f"/api/discord/sessions/{session_of(client, guild, channel)}/turns", json=payload)
    assert created.status_code in (200, 201), created.text
    return message_id, created.json()["turn_id"]


def execute(client, turn_id: str):
    return client.post(f"/api/discord/sessions/turns/{turn_id}/execute")


def execute_reply(client, turn_id: str):
    """Execute a reply turn. Review2 R1: today the reply path reads `created_at` from a
    context that has none, and the AttributeError escapes the request; only that error,
    at this call, counts as the known bug."""
    try:
        return execute(client, turn_id)
    except AttributeError as error:
        if "created_at" not in str(error):
            raise
        raise KnownBug(f"review2 R1: the reply turn crashed: {error}") from error


def complete(client, turn_id: str, token: str) -> str:
    response_id = "response-" + uuid4().hex
    done = client.post(f"/api/discord/sessions/turns/{turn_id}/complete", json={
        "execution_token": token, "discord_response_message_ids": [response_id]})
    assert done.status_code == 200, done.text
    return response_id


def fail_delivery(client, turn_id: str, token: str) -> str:
    """The bot reports a failed Discord delivery that may be retried."""
    failed = client.post(f"/api/discord/sessions/turns/{turn_id}/fail", json={
        "execution_token": token, "error": "Discord delivery failed: HTTPException", "retryable": True})
    assert failed.status_code == 200, failed.text
    return failed.json()["status"]


def finished_turn(client, guild: str, channel: str, body: str, *, author: str = "alice") -> SimpleNamespace:
    """One turn asked, answered, and delivered."""
    message_id, turn_id = enqueue(client, guild, channel, body, author=author)
    executed = execute(client, turn_id)
    assert executed.status_code == 200 and executed.json()["answer"], executed.text
    response_id = complete(client, turn_id, executed.json()["execution_token"])
    return SimpleNamespace(message_id=message_id, turn_id=turn_id, response_id=response_id,
                           answer=executed.json()["answer"])


def seed_history_barrier(client, guild: str) -> None:
    """The barrier migration 20261109_39 seeded for every existing guild (same statement)."""
    with client.app.state.postgres_sessions.begin() as db:
        db.execute(text("""INSERT INTO source_memory_states (tenant, audience, epoch, barrier_at)
            VALUES (:t, '__history__', 1, clock_timestamp())
            ON CONFLICT (tenant, audience) DO UPDATE SET epoch = source_memory_states.epoch + 1,
            barrier_at = clock_timestamp()"""), {"t": f"discord:{guild}"})
    time.sleep(0.05)  # rows that must be newer than the barrier start after it, whatever the clock jitter


def turn_by_message(client, message_id: str):
    with client.app.state.postgres_sessions() as db:
        return db.execute(text(
            "SELECT id, status, attempt_count, response_text FROM discord_session_turns WHERE discord_message_id = :m"),
            {"m": str(message_id)}).one_or_none()


def ledger_message(client, guild: str, channel: str, author: str, content: str, *,
                   message_id: str | None = None, bot: bool = False) -> str:
    """The bot ships one heard message to the raw ledger."""
    message_id = message_id or snowflake()
    recorded = client.post("/api/discord/history/messages", json={
        "guild_id": guild, "channel_id": channel, "thread_id": None, "discord_message_id": message_id,
        "author_id": author, "author_display_name": author, "is_bot": bot, "content": content,
        "reply_to_message_id": None})
    assert recorded.status_code == 200 and recorded.json()["recorded"], recorded.text
    return message_id


def expire_lease(client, turn_id: str) -> None:
    """The bot holding this turn stopped heartbeating long enough for its lease to run out."""
    with client.app.state.postgres_sessions.begin() as db:
        db.execute(text("UPDATE discord_session_turns SET lease_expires_at = clock_timestamp() - interval '1 second' "
                        "WHERE id = :i"), {"i": UUID(str(turn_id))})


def active_notes(memory, guild: str, channel: str, actor: str = "alice") -> list[str]:
    from app.services.source_memory import MemoryReader
    return [note["content"] for note in memory.list_notes(MemoryReader.discord(guild, channel, None, actor))]


def channel_barrier(client, guild: str, channel: str):
    from app.services.source_memory import MemoryReader
    return client.app.state.source_memory_service.snapshot(MemoryReader.discord(guild, channel, None, "alice"))[1]


def edit_unledgered(client, guild: str, channel: str, message_id: str, content: str = "đã sửa") -> None:
    """A person edits a message the ledger never stored and nobody asked to remember: its
    tombstone lands under "__deleted__" and the channel barrier stays where it was."""
    before = channel_barrier(client, guild, channel)
    edited = client.post(f"/api/discord/history/messages/{message_id}/edit", json={"content": content})
    assert edited.status_code == 200, edited.text
    assert client.app.state.source_memory_service.is_retracted(f"discord:{message_id}"), "the edit left no tombstone"
    assert channel_barrier(client, guild, channel) == before, "the edit moved the channel barrier"


def age_open_turns(client, guild: str) -> list[str]:
    """What a long-dead bot leaves behind: every lease on this guild's open turns runs out,
    the backend's own recovery runs, then every time column of the still-open turns is moved
    one hour back. Returns the ids of the turns still open."""
    sessions = client.app.state.postgres_sessions
    scope = ("FROM discord_session_turns t JOIN discord_conversation_sessions s ON s.id = t.session_id "
             "WHERE s.guild_id = :g AND t.status IN ('queued', 'running')")
    with sessions.begin() as db:
        db.execute(text(f"UPDATE discord_session_turns SET lease_expires_at = clock_timestamp() - interval '1 second' "
                        f"WHERE lease_expires_at IS NOT NULL AND id IN (SELECT t.id {scope})"), {"g": guild})
    client.app.state.discord_turn_service.recover_stale()
    with sessions.begin() as db:
        open_ids = [str(row[0]) for row in db.execute(text(f"SELECT t.id {scope}"), {"g": guild})]
        hour = "interval '1 hour'"
        db.execute(text(
            f"UPDATE discord_session_turns SET created_at = created_at - {hour}, updated_at = updated_at - {hour}, "
            f"available_at = available_at - {hour}, started_at = started_at - {hour}, "
            f"heartbeat_at = heartbeat_at - {hour}, lease_expires_at = lease_expires_at - {hour}, "
            f"completed_at = completed_at - {hour} WHERE id IN (SELECT t.id {scope})"), {"g": guild})
    return open_ids


# ── Clocks ──────────────────────────────────────────────────────────────────────

def app_clock(monkeypatch, seconds: float) -> None:
    """Only the application's clock runs `seconds` off; Postgres (where every barrier is
    stamped) keeps true time. Barriers are never written by hand."""
    shift = timedelta(seconds=seconds)
    real = datetime

    class SkewedDatetime(real):
        @classmethod
        def now(cls, tz=None):
            return real.now(tz) + shift

    monkeypatch.setattr("app.discord.repositories.datetime", SkewedDatetime)
    monkeypatch.setattr("app.services.chat_service.datetime", SkewedDatetime)
    monkeypatch.setattr("app.stores.postgres_auxiliary_store._utc_now", lambda: real.now(UTC) + shift)


# ── OCR without containers ──────────────────────────────────────────────────────

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class MemoryOcrStore:
    """The four OCR-run methods of the auxiliary store, in memory."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def save_ocr_run(self, run_id, filename, status, model, result_json) -> None:
        with self._lock:
            self.runs[run_id] = {"id": run_id, "filename": filename, "status": status, "model": model,
                                 "result_json": result_json}

    def list_ocr_runs(self):
        with self._lock:
            return list(self.runs.values())

    def delete_ocr_run(self, run_id) -> None:
        with self._lock:
            self.runs.pop(run_id, None)


class BlockingOcr:
    """An OCR model that holds the worker inside recognize_png until released."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def config_hash(self, dpi: int) -> str:
        return f"blocking-{dpi}"

    def recognize_png(self, png: bytes, dpi: int, *, allow_mock: bool = False):
        from app.services.ocr_service import OcrResult
        self.entered.set()
        assert self.release.wait(10), "the test never released the OCR worker"
        return OcrResult("Trang thử.", "blocking-ocr", self.config_hash(dpi), False)


def ocr_router_stub() -> SimpleNamespace:
    return SimpleNamespace(models={"ocr": {"name": "mock-ocr"}, "general": {"name": "text-only"}})


def quiet_ocr(monkeypatch) -> None:
    """MOCK_OCR answers every page; the job's metrics never shell out to nvidia-smi."""
    monkeypatch.setenv("MOCK_OCR", "true")
    monkeypatch.setattr("app.services.ocr_job_service.system_metrics", lambda: {})


def wait_idle(service, timeout: float = 10.0) -> None:
    """Until no OCR worker of `service` is running."""
    deadline = time.monotonic() + timeout
    while service._active is not None or any(
            job.get("status") in {"queued", "running"} for job in list(service.jobs.values())):
        assert time.monotonic() < deadline, "the OCR worker did not stop"
        time.sleep(0.02)


# ── The real bot wired to the real app ──────────────────────────────────────────

def progress_fakes():
    """Discord, FakeSource and quick from tests/test_discord_progress_message.py, loaded by
    path: the repo-root tests/ directory is not importable from backend/."""
    name = "review2_progress_fakes"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "tests" / "test_discord_progress_message.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


class BotOnApp:
    """Level T: DiscordConversationGateway + LocalAgentClient + answer_mention, unchanged, with
    every HTTP call served by the real app through httpx.ASGITransport. Discord is the fake
    from test_discord_progress_message.py. A real server answers an exception with 500, so the
    transport does too; the exceptions are recorded for the test to inspect."""

    def __init__(self, client, guild: str, *, budget: float) -> None:
        self.client, self.guild, self.budget = client, guild, budget
        self.fakes = progress_fakes()
        self.server_errors: list[BaseException] = []
        app = client.app

        async def recording(scope, receive, send):
            try:
                await app(scope, receive, send)
            except BaseException as error:
                self.server_errors.append(error)
                raise

        self.app = recording

    def api(self):
        """A fresh bot process's backend client."""
        import httpx
        from discord_bot.api_client import LocalAgentClient, LocalAgentSettings
        transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=False)
        http = httpx.AsyncClient(transport=transport, base_url="http://backend", timeout=self.budget)
        return LocalAgentClient(LocalAgentSettings("http://backend", turn_execute_timeout_seconds=self.budget), http)

    @staticmethod
    async def close(api) -> None:
        await api._http.aclose()

    def message(self, question: str):
        """A new message in channel 20 of this guild, with its own Discord side. Each side
        numbers what it sends from a fresh snowflake: every fake side starts at the same id,
        and the backend links an answer's Discord id to one turn only, so two answered
        messages would otherwise collide when the second is marked delivered."""
        side = self.fakes.Discord()
        source = self.fakes.FakeSource(side)
        source.id = int(snowflake())
        # Set after the question's id, so the answers are stamped later than the question.
        assert "_next_id" in vars(side), "the fake Discord no longer numbers from _next_id"
        side._next_id = int(snowflake())
        source.guild = SimpleNamespace(id=self.guild, name="review2", member_count=0, members=[])
        source.question = question
        return source

    def gateway(self, api, budget: float | None = None):
        from discord_bot.main import DiscordConversationGateway
        return DiscordConversationGateway(api, "Bạn là Ún.", 0, True,
                                          poll_budget_seconds=self.budget if budget is None else budget)

    async def ask(self, api, source, *, budget: float | None = None,
                  allowed: tuple[type[BaseException], ...] = ()):
        """One @mention handled the way on_message hands it over. Returns None, or the
        exception that escaped the handler if the case lists its type in `allowed` (A-5: a
        failed delivery is reported and then re-raised). Any other escape is re-raised, so an
        unrelated crash of the bot fails the case instead of passing for the known bug."""
        from discord_bot.main import answer_mention
        progress = self.fakes.quick(source, first_post_seconds=3600.0)
        try:
            await answer_mention(self.gateway(api, budget), source, source.question, progress)
        except allowed as error:
            return error
        return None

    @staticmethod
    def shown(source) -> list[str]:
        return [content or "" for _, _, content, _ in source.discord_side.writes]
