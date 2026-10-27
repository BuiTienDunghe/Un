"""What an agent turn is doing, shown while it runs (ticket 20 #4).

The agent tells an on_step listener each kind of work as it starts: thinking, a tool by its
own label, the answer check's retry, the forced answer. Events carry no argument, result or
answer, and a listener that breaks is ignored. The web stream runs the turn on a worker
thread, in a copy of the request's context, so the turn's 90 s deadline still bounds every
model call there. Discord's progress store forgets a turn when it ends, and anything older
than its cap. No database, no model.
"""
from __future__ import annotations

import contextvars
import json
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.routers.chat as chat_router
from app import discord
from app.config.settings import PROJECT_ROOT, Settings
from app.discord import agent_tools
from app.discord.routers import sessions as discord_sessions
from app.discord.turn_progress import TurnProgress
from app.llm_clients.deadline import request_timeout
from app.postgres.database import create_postgres_engine, create_session_factory
from app.security.api_key import require_api_key
from app.services.agent_service import (
    ANSWER_CHECK_LABEL,
    ANSWERING_LABEL,
    REVIEWING_LABEL,
    THINKING_LABEL,
    TOOL_LABEL,
    AgentService,
    core_tools,
)
from app.services.chat_service import ConversationNotFoundError

QUERY = "phụ cấp lưu trú bí mật"
ANSWER = "Phụ cấp lưu trú là 300.000 đồng/người/ngày."


def call(name: str, arguments: dict) -> dict:
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}], "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


class Router:
    def __init__(self, rounds, forced: str = "hết lượt"):
        self.rounds, self.forced, self.timeouts = list(rounds), forced, []

    def chat_tools(self, role, messages, tools):
        # What the turn's deadline leaves this call, read the way the Ollama client reads it.
        self.timeouts.append(request_timeout(120.0))
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        self.timeouts.append(request_timeout(120.0))
        return self.forced, "fake"


class Retrieval:
    def retrieve(self, query, top_k, document_id=None):
        return [{"filename": "quy_dinh_cong_tac_phi_2026.pdf", "page": 2, "content": "Phụ cấp lưu trú: 300.000 đồng/người/ngày.", "score": 0.9}]


def run(rounds, max_steps=3, **kwargs):
    events: list[dict] = []
    agent = AgentService(Router(rounds, kwargs.pop("forced", "hết lượt")), Retrieval(), None, max_steps=max_steps)
    answer, _, steps = agent.run([{"role": "user", "content": "Phụ cấp lưu trú?"}], on_step=events.append, **kwargs)
    return answer, steps, events


def test_a_turn_tells_each_kind_of_work_as_it_starts():
    _, _, events = run([call("search_documents", {"query": QUERY}), final(ANSWER)])
    assert [(e["kind"], e["round"]) for e in events] == [("thinking", 1), ("tool_call", 1), ("tool_result", 1), ("thinking", 2), ("final", 2)]
    assert events[0]["label"] == THINKING_LABEL and events[3]["label"] == REVIEWING_LABEL
    assert events[1]["tool"] == "search_documents" and events[1]["label"] == "Đang tra tài liệu…", "the tool brings its own label"
    assert events[2]["ok"] is True and events[-1]["stop_reason"] == "final"


def test_events_carry_no_argument_result_or_answer():
    _, _, events = run([call("search_documents", {"query": QUERY}), final(ANSWER)])
    text = json.dumps(events, ensure_ascii=False)
    assert QUERY not in text and "300.000" not in text and ANSWER not in text


def test_the_retry_and_the_forced_answer_are_told_too():
    _, _, events = run([final("Mức là 999.999 đồng."), final("Mình chưa tra được.")])
    assert [e["kind"] for e in events] == ["thinking", "answer_check", "thinking", "final"]
    assert events[1]["label"] == ANSWER_CHECK_LABEL

    _, _, events = run([call("search_documents", {"query": QUERY})], max_steps=1, forced=ANSWER)
    assert [e["kind"] for e in events][-2:] == ["answering", "final"] and events[-2]["label"] == ANSWERING_LABEL


def test_an_invented_tool_is_named_nowhere_and_gets_the_generic_label():
    _, _, events = run([call("ghi_vao_he_thong_bi_mat", {}), final("xong")])
    told = next(e for e in events if e["kind"] == "tool_call")
    assert told["tool"] is None and told["label"] == TOOL_LABEL


def test_a_broken_listener_costs_nothing():
    def broken(event):
        raise RuntimeError("màn hình đóng rồi")

    rounds = [call("search_documents", {"query": QUERY}), final(ANSWER)]
    quiet = AgentService(Router(list(rounds)), Retrieval(), None).run([{"role": "user", "content": "Phụ cấp lưu trú?"}])
    loud = AgentService(Router(list(rounds)), Retrieval(), None).run([{"role": "user", "content": "Phụ cấp lưu trú?"}], on_step=broken)
    strip = lambda steps: [{k: v for k, v in s.items() if k != "latency_ms"} for s in steps]  # noqa: E731
    assert loud[0] == quiet[0] == ANSWER and strip(loud[2]) == strip(quiet[2])


def test_the_discord_tool_brings_its_label_from_the_package():
    registry = core_tools()
    agent_tools.register(registry, None)
    assert registry.get("search_history").label == "Đang xem lịch sử tin nhắn của server…"


def test_the_worker_thread_keeps_the_requests_context():
    marker: contextvars.ContextVar[str] = contextvars.ContextVar("marker", default="none")
    marker.set("request")
    seen: list[str] = []
    chat_router.start_in_request_context(lambda: seen.append(marker.get())).join(timeout=5)
    assert seen == ["request"]


def test_the_turn_deadline_still_bounds_every_model_call_on_the_worker_thread():
    # 90 s budget, 20 s reserve: a tool round may wait at most 70 s, the forced answer what is
    # left. Run on the worker thread exactly as the web stream runs it.
    router = Router([call("search_documents", {"query": QUERY})], forced=ANSWER)
    agent = AgentService(router, Retrieval(), None, max_steps=1)
    done: list[tuple] = []
    chat_router.start_in_request_context(lambda: done.append(agent.run([{"role": "user", "content": "?"}]))).join(timeout=10)

    assert done and done[0][0] == ANSWER
    tool_round, forced = router.timeouts
    assert 69.0 < tool_round <= 70.0, "the 90 s turn, minus the final reserve"
    assert 89.0 < forced <= 90.0 and request_timeout(120.0) == 120.0, "and nothing leaks back to the caller's thread"


class ChatServiceStub:
    def __init__(self, events=(), error: Exception | None = None):
        self.events, self.error = list(events), error

    def respond(self, message, conversation_id, use_memory, system_prompt, use_tools, user_id=None, on_step=None):
        for event in self.events:
            on_step(event)
        if self.error:
            raise self.error
        return "Câu trả lời.", "fake", "conv-1", 12, [{"kind": "final"}]


def sse(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        out.append((lines.get("event"), json.loads(lines.get("data", "{}"))))
    return out


def client(chat_service, monkeypatch) -> TestClient:
    monkeypatch.setattr(chat_router, "resolve_identity", lambda request: SimpleNamespace(is_user=False, user_id=None))
    app = FastAPI()
    app.include_router(chat_router.router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.state.chat_service = chat_service
    app.state.logging_service = SimpleNamespace(log_request=lambda *a, **k: None)
    return TestClient(app)


def test_the_web_stream_sends_progress_ahead_of_the_answer(monkeypatch):
    events = [{"kind": "thinking", "round": 1, "label": THINKING_LABEL}, {"kind": "tool_call", "round": 1, "tool": "search_documents", "label": "Đang tra tài liệu…"},
              {"kind": "tool_result", "round": 1, "tool": "search_documents", "ok": True}, {"kind": "final", "round": 2, "stop_reason": "final"}]
    body = client(ChatServiceStub(events), monkeypatch).post("/chat", json={"message": "?", "use_tools": True, "stream": True}).text
    got = sse(body)

    assert [name for name, _ in got] == ["progress", "progress", "meta", "steps", "token", "done"], "only labelled events show"
    assert got[1][1] == {"kind": "tool_call", "round": 1, "tool": "search_documents", "label": "Đang tra tài liệu…"}
    assert got[4][1] == {"content": "Câu trả lời."}


def test_a_turn_that_fails_mid_stream_ends_with_its_error_code(monkeypatch):
    failing = client(ChatServiceStub([{"kind": "thinking", "round": 1, "label": THINKING_LABEL}], ConversationNotFoundError("conv-x")), monkeypatch)
    got = sse(failing.post("/chat", json={"message": "?", "use_tools": True, "stream": True}).text)
    assert [name for name, _ in got] == ["progress", "error"] and got[-1][1]["error_code"] == "CONVERSATION_NOT_FOUND"

    broken = client(ChatServiceStub(error=RuntimeError("đứt")), monkeypatch)
    assert sse(broken.post("/chat", json={"message": "?", "use_tools": True, "stream": True}).text)[-1][1]["error_code"] == "INTERNAL_ERROR"


def test_the_progress_store_forgets_a_turn_when_it_ends_and_after_its_cap():
    now = [0.0]
    store = TurnProgress(clock=lambda: now[0], max_age_seconds=600)
    store.recorder("t1")({"kind": "tool_call", "round": 1, "label": "Đang tra tài liệu…"})
    store.record("t1", {"kind": "tool_result", "round": 1})
    entry = store.get("t1")
    assert entry["label"] == "Đang tra tài liệu…" and entry["steps"] == 2 and entry["kind"] == "tool_result", "an unlabelled event keeps the last label"

    store.finish("t1")
    assert store.get("t1") is None and len(store) == 0

    store.record("old", {"kind": "thinking", "round": 1, "label": THINKING_LABEL})
    now[0] = 601.0
    store.record("new", {"kind": "thinking", "round": 1, "label": THINKING_LABEL})
    assert store.get("old") is None and store.get("new") is not None and len(store) == 1


def test_the_progress_store_takes_writes_from_many_threads():
    store = TurnProgress()
    threads = [threading.Thread(target=lambda i=i: [store.record(f"t{i}", {"kind": "thinking", "round": r, "label": "x"}) for r in range(200)]) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(store) == 8 and all(store.get(f"t{i}")["steps"] == 200 for i in range(8))


def test_the_bot_reads_a_running_turns_progress_and_nothing_once_it_ended():
    app = FastAPI()
    app.include_router(discord_sessions.router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.state.discord_turn_progress = TurnProgress()
    app.state.discord_turn_progress.record("6f1c1d0a-0000-4000-8000-000000000001", {"kind": "tool_call", "round": 1, "label": "Đang tra tài liệu…"})
    api = TestClient(app)

    running = api.get("/api/discord/sessions/turns/6f1c1d0a-0000-4000-8000-000000000001/progress").json()
    assert running["running"] is True and running["label"] == "Đang tra tài liệu…" and running["steps"] == 1
    ended = api.get("/api/discord/sessions/turns/6f1c1d0a-0000-4000-8000-000000000002/progress").json()
    assert ended == {"turn_id": "6f1c1d0a-0000-4000-8000-000000000002", "running": False, "label": None, "kind": None, "round": None, "steps": 0, "updated_at": None}


def test_a_discord_turn_drops_its_progress_however_it_ends():
    from uuid import uuid4

    from app.discord.turn_service import DiscordTurnService

    store = TurnProgress()
    service = DiscordTurnService(None, None, SimpleNamespace(history_limit=12), progress=store)
    turn_id = uuid4()
    with service._tracked(turn_id) as progress:
        progress["on_step"]({"kind": "thinking", "round": 1, "label": THINKING_LABEL})
        assert store.get(str(turn_id))["label"] == THINKING_LABEL
    assert store.get(str(turn_id)) is None

    try:
        with service._tracked(turn_id) as progress:
            progress["on_step"]({"kind": "thinking", "round": 1, "label": THINKING_LABEL})
            raise RuntimeError("model died")
    except RuntimeError:
        pass
    assert store.get(str(turn_id)) is None, "a failed turn leaves nothing behind"

    without = DiscordTurnService(None, None, SimpleNamespace(history_limit=12))
    with without._tracked(turn_id) as progress:
        assert progress == {}, "no store, no on_step keyword: older chat services are called as before"


def test_register_services_gives_the_turn_service_the_store_the_endpoint_reads():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://test:test@127.0.0.1:1/none")
    sessions = create_session_factory(create_postgres_engine(str(settings.database_url)))  # never connects here
    app = SimpleNamespace(state=SimpleNamespace(memory_service=object(), chat_service=object(), agent_service=SimpleNamespace(registry=core_tools())))
    discord.register_services(app, settings, sessions, project_root=PROJECT_ROOT)
    assert app.state.discord_turn_service.progress is app.state.discord_turn_progress
