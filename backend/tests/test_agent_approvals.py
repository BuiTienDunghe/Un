"""Ticket 46: tools that wait for a person's yes before they run, checked without PostgreSQL.

The model is scripted, the real AgentService runs, and the approval table is real SQL on in-memory
SQLite (that table alone; SQLite ignores row locks, so the claim race stays for PostgreSQL). The
last test needs POSTGRES_TEST_URL: the real cascade and the real forget_member script.
"""
from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import discord
from app.config.settings import PROJECT_ROOT, Settings
from app.discord import agent_tools
from app.discord import approvals as policy
from app.discord.approvals import ApprovalService, SqlApprovalStore, TurnIdentity
from app.discord.routers import approvals as approval_routes
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import DiscordApproval
from app.services.agent_service import (
    STOP_FINAL, AgentService, AgentTool, ToolRegistry, core_tools,
)
from app.services.approvals import (
    APPROVAL_PENDING, APPROVAL_REQUIRED, APPROVAL_UNAVAILABLE, STOP_AWAITING_APPROVAL, ApprovalError,
)
from scripts.forget_member import _forget_approvals

NOW = datetime(2026, 11, 2, 3, 0, tzinfo=UTC)
GUILD, OTHER_GUILD = "111", "222"
ME, YOU = "900", "901"
# Not all digits: SQLite gives a UUID column numeric affinity and would read an all-digit one back as a number.
TURN = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class Router:
    """Scripted model: each chat_tools call pops one round and records exactly what it was shown."""

    def __init__(self, rounds):
        self.rounds, self.tools_seen, self.messages_seen, self.plain_chats = list(rounds), [], [], 0

    def chat_tools(self, role, messages, tools):
        self.tools_seen.append([tool["function"]["name"] for tool in tools])
        self.messages_seen.append(json.dumps(messages, ensure_ascii=False, sort_keys=True))
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        self.plain_chats += 1
        return "đã trả lời", "fake"


def calls(name: str, arguments: dict) -> dict:
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}], "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def answer(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


@dataclass
class Gated:
    """A tool that requires approval and writes down every time it really runs."""

    ran: list = field(default_factory=list)
    fail: bool = False

    def tool(self, name: str = "send_note") -> AgentTool:
        schema = {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": []}}}

        def run(service, arguments, context):
            self.ran.append((dict(arguments), dict(context or {})))
            if self.fail:
                raise RuntimeError("boom")
            return service._dump({"sent": arguments.get("text")}), None, None

        return AgentTool(schema, run, "Đang gửi…", requires_approval=True)


class World:
    def __init__(self, *, enabled: bool = True, turn: TurnIdentity | None = TurnIdentity(GUILD, "chan", None, ME), allowed=frozenset({GUILD})) -> None:
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        DiscordApproval.__table__.create(engine)
        self.sessions = sessionmaker(engine, expire_on_commit=False)
        self.clock = Clock()
        self.gated = Gated()
        registry = core_tools()
        registry.register(self.gated.tool(), 60)
        self.agent = AgentService(Router([]), None, None, registry=registry)
        self.turn = turn
        self.allowed = allowed
        self.service = self.make_service(enabled=enabled)
        if enabled:
            self.agent.approvals = self.service

    def make_service(self, *, enabled: bool) -> ApprovalService:
        return ApprovalService(
            SqlApprovalStore(self.sessions), enabled=enabled, guild_allowed=lambda guild: self.allowed is None or guild in self.allowed,
            load_turn=lambda turn_id: self.turn, run_approved=self.agent.run_approved, clock=self.clock,
        )

    def turn_with(self, *rounds: dict, tool_context: dict | None = None):
        self.agent.router = Router(rounds)
        result = self.agent.run([{"role": "user", "content": "gửi ghi chú giúp tôi"}], tool_context={"turn_id": TURN, "guild_id": GUILD} if tool_context is None else tool_context)
        return result, self.agent.router

    def rows(self) -> list[DiscordApproval]:
        with self.sessions() as database:
            return list(database.scalars(select(DiscordApproval)))

    def ask(self, text: str = "Họp lúc 9h") -> str:
        """The id of the approval a turn asking to send this note has kept."""
        (_, _, steps), _ = self.turn_with(calls("send_note", {"text": text}))
        assert steps[-1]["stop_reason"] == STOP_AWAITING_APPROVAL
        return str(next(row.id for row in self.rows() if json.loads(row.arguments)["text"] == text))

    def decide(self, approval_id: str, *, actor: str = ME, guild: str = GUILD, approve: bool = True, service: ApprovalService | None = None):
        return (service or self.service).decide(approval_id, guild_id=guild, actor_id=actor, approve=approve)


def code_of(call) -> str:
    with pytest.raises(ApprovalError) as caught:
        call()
    return caught.value.code


# ---- off: the model is shown exactly what it was ----

def test_approvals_are_off_by_default() -> None:
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://x:x@127.0.0.1:1/x")
    assert settings.discord_approvals_enabled is False
    assert all(not tool.requires_approval for tool in core_tools().tools())
    assert AgentTool({"function": {"name": "x"}}, lambda *a: ("", None, None)).requires_approval is False


def test_off_the_model_is_shown_the_same_tools_and_the_same_messages_as_before() -> None:
    """The gated tool is registered but nothing can approve it: the tools list and every message the
    model reads are byte for byte what an agent without that tool sends."""
    plain = AgentService(Router([answer("chào")]), None, None)
    agent_tools.register(plain.registry, None)
    plain.run([{"role": "system", "content": "persona"}, {"role": "user", "content": "chào"}], tool_context={"turn_id": TURN, "guild_id": GUILD})

    world = World(enabled=False)
    agent_tools.register(world.agent.registry, None)
    world.agent.router = Router([answer("chào")])
    world.agent.run([{"role": "system", "content": "persona"}, {"role": "user", "content": "chào"}], tool_context={"turn_id": TURN, "guild_id": GUILD})

    assert "send_note" in world.agent.registry.names()
    assert world.agent.router.tools_seen == plain.router.tools_seen
    assert world.agent.router.messages_seen == plain.router.messages_seen
    assert "send_note" not in world.agent.router.tools_seen[0]


def test_on_the_gated_tool_is_offered_in_its_place_in_the_list() -> None:
    world = World(enabled=True)
    (_, _, _), router = world.turn_with(answer("chào"))
    assert router.tools_seen[0] == ["search_documents", "read_document", "system_status", "current_time", "calculate", "send_note"]


def test_a_gated_tool_the_model_calls_anyway_while_off_does_not_run() -> None:
    world = World(enabled=False)
    (text, _, steps), router = world.turn_with(calls("send_note", {"text": "x"}), answer("Mình chưa làm được."))
    assert world.gated.ran == [] and world.rows() == []
    result = next(step for step in steps if step["kind"] == "tool_result")
    assert result["error_code"] == APPROVAL_UNAVAILABLE and steps[-1]["stop_reason"] == STOP_FINAL and text == "Mình chưa làm được."


def test_no_path_runs_a_gated_tool_without_a_yes() -> None:
    world = World()
    out, code, _ = world.agent._run_tool("send_note", {"text": "x"}, {"turn_id": TURN})
    assert code == APPROVAL_REQUIRED and world.gated.ran == []
    assert world.agent._execute_tool("send_note", {"text": "x"}, {"turn_id": TURN}) == out
    # And the approved path refuses what is not gated: it cannot be used to run any other tool.
    _, code, _ = world.agent.run_approved("calculate", {"expression": "1+1"})
    assert code == "UNKNOWN_TOOL"


# ---- on: the turn stops and waits ----

def test_a_gated_call_stops_the_turn_and_runs_nothing() -> None:
    world = World()
    (reply, model, steps), router = world.turn_with(calls("send_note", {"text": "Họp lúc 9h"}))
    assert world.gated.ran == [] and router.plain_chats == 0 and len(router.tools_seen) == 1
    assert [step["kind"] for step in steps] == ["tool_call", "tool_result", "final"]
    assert steps[1]["error_code"] == APPROVAL_PENDING and steps[1]["content"] is None
    assert steps[2]["stop_reason"] == STOP_AWAITING_APPROVAL and steps[2]["content"] == reply and model == "fake"
    (row,) = world.rows()
    assert (row.status, row.requester_id, row.guild_id, row.tool_name) == ("pending", ME, GUILD, "send_note")
    assert json.loads(row.arguments) == {"text": "Họp lúc 9h"}
    assert "send_note" in reply and "Họp lúc 9h" in reply and str(row.id)[:8] in reply and "10 phút" in reply


def test_what_is_shown_is_what_runs_and_a_ping_in_it_does_not_read_as_one() -> None:
    world = World()
    (reply, _, _), _ = world.turn_with(calls("send_note", {"text": "@everyone họp", "n": 3}))
    assert "@everyone" not in reply and "@​everyone" in reply
    world.decide(str(world.rows()[0].id))
    assert world.gated.ran == [({"text": "@everyone họp", "n": 3}, {"guild_id": GUILD, "turn_id": TURN})]


def test_the_same_call_in_a_turn_the_worker_runs_again_asks_once() -> None:
    world = World()
    world.ask("Họp lúc 9h")
    world.ask("Họp lúc 9h")
    assert len(world.rows()) == 1
    world.ask("Họp lúc 10h")
    assert len(world.rows()) == 2


def test_one_member_cannot_pile_up_requests() -> None:
    world = World()
    for number in range(policy.MAX_PENDING_PER_MEMBER):
        world.turn = TurnIdentity(GUILD, "chan", None, ME)
        world.agent.router = Router([calls("send_note", {"text": f"việc {number}"})])
        world.agent.run([{"role": "user", "content": "x"}], tool_context={"turn_id": str(uuid4()), "guild_id": GUILD})
    assert len(world.rows()) == policy.MAX_PENDING_PER_MEMBER
    (_, _, steps), _ = world.turn_with(calls("send_note", {"text": "thêm"}), answer("Bạn duyệt bớt đã nhé."), tool_context={"turn_id": str(uuid4()), "guild_id": GUILD})
    assert next(step for step in steps if step["kind"] == "tool_result")["error_code"] == "TOO_MANY_PENDING"
    assert len(world.rows()) == policy.MAX_PENDING_PER_MEMBER and world.gated.ran == []


@pytest.mark.parametrize("context, turn, code", [
    ({}, TurnIdentity(GUILD, "chan", None, ME), "NOT_A_DISCORD_TURN"),
    ({"turn_id": TURN}, None, "NO_SPEAKER"),
    ({"turn_id": TURN}, TurnIdentity(OTHER_GUILD, "chan", None, ME), "GUILD_NOT_ALLOWED"),
])
def test_a_call_with_nobody_to_approve_it_is_refused_to_the_model_and_not_kept(context, turn, code) -> None:
    world = World(turn=turn)
    (_, _, steps), _ = world.turn_with(calls("send_note", {"text": "x"}), answer("Chưa làm được."), tool_context=context)
    assert next(step for step in steps if step["kind"] == "tool_result")["error_code"] == code
    assert world.rows() == [] and world.gated.ran == []


def test_arguments_too_long_to_be_shown_are_refused_not_kept() -> None:
    world = World()
    (_, _, steps), _ = world.turn_with(calls("send_note", {"text": "x" * (policy.ARGUMENTS_MAX_CHARS + 1)}), answer("Chưa làm được."))
    assert next(step for step in steps if step["kind"] == "tool_result")["error_code"] == "ARGUMENTS_TOO_LONG"
    assert world.rows() == [] and world.gated.ran == []


def test_a_gate_that_breaks_costs_the_tool_not_the_turn() -> None:
    world = World()
    world.agent.approvals = SimpleNamespace(request=lambda *args: (_ for _ in ()).throw(RuntimeError("database down")))
    (text, _, steps), _ = world.turn_with(calls("send_note", {"text": "x"}), answer("Chưa gửi đi xin duyệt được."))
    assert next(step for step in steps if step["kind"] == "tool_result")["error_code"] == "TOOL_FAILED" and text == "Chưa gửi đi xin duyệt được."
    assert world.gated.ran == []


def test_calls_before_the_gated_one_ran_and_calls_after_it_did_not() -> None:
    world = World()
    two = {"content": "", "tool_calls": [{"name": "calculate", "arguments": {"expression": "2+2"}}, {"name": "send_note", "arguments": {"text": "x"}}, {"name": "calculate", "arguments": {"expression": "3+3"}}], "raw_tool_calls": []}
    (_, _, steps), _ = world.turn_with(two)
    assert [step["tool_name"] for step in steps if step["kind"] == "tool_call"] == ["calculate", "send_note"]
    assert steps[-1]["stop_reason"] == STOP_AWAITING_APPROVAL and world.gated.ran == []


# ---- who may say yes ----

def test_only_the_member_it_belongs_to_approves_and_nothing_runs_before() -> None:
    world = World()
    approval_id = world.ask()
    assert world.gated.ran == []
    assert code_of(lambda: world.decide(approval_id, actor=YOU)) == "APPROVAL_NOT_YOURS"
    assert code_of(lambda: world.decide(approval_id, actor=YOU, approve=False)) == "APPROVAL_NOT_YOURS"
    assert code_of(lambda: world.decide(approval_id, guild=OTHER_GUILD)) == "APPROVAL_NOT_FOUND"
    assert code_of(lambda: world.decide("not-a-uuid")) == "APPROVAL_NOT_FOUND"
    assert code_of(lambda: world.decide(str(uuid4()))) == "APPROVAL_NOT_FOUND"
    assert world.gated.ran == [] and world.rows()[0].status == "pending"  # another member could not even cancel it
    decision = world.decide(approval_id)
    assert (decision.status, decision.code) == ("done", None) and json.loads(decision.text) == {"sent": "Họp lúc 9h"}
    assert len(world.gated.ran) == 1 and world.rows()[0].status == "done"


def test_a_second_yes_does_not_run_it_again() -> None:
    world = World()
    approval_id = world.ask()
    world.decide(approval_id)
    assert code_of(lambda: world.decide(approval_id)) == "APPROVAL_NOT_PENDING"
    assert code_of(lambda: world.decide(approval_id, approve=False)) == "APPROVAL_NOT_PENDING"
    assert len(world.gated.ran) == 1


def test_a_no_means_it_never_runs() -> None:
    world = World()
    approval_id = world.ask()
    decision = world.decide(approval_id, approve=False)
    assert decision.status == "denied" and decision.text is None
    assert code_of(lambda: world.decide(approval_id)) == "APPROVAL_NOT_PENDING"
    assert world.gated.ran == [] and world.rows()[0].status == "denied"


def test_it_waits_ten_minutes_and_then_is_cancelled_without_running() -> None:
    world = World()
    first, second = world.ask("một"), world.ask("hai")
    world.clock.now = NOW + timedelta(minutes=9, seconds=59)
    # SQLite stamps created_at to the second, so two asks inside one second tie: the order is not what this test checks.
    assert sorted(a.id for a in world.service.list_for(GUILD, ME)) == sorted([first, second])
    world.clock.now = NOW + timedelta(minutes=10, seconds=1)
    assert code_of(lambda: world.decide(first)) == "APPROVAL_EXPIRED"
    assert code_of(lambda: world.decide(second, approve=False)) == "APPROVAL_EXPIRED"
    assert world.service.list_for(GUILD, ME) == []
    assert world.gated.ran == [] and {row.status for row in world.rows()} == {"expired"}


def test_the_clock_is_checked_at_the_moment_of_the_yes_even_if_nothing_swept() -> None:
    """The row still says pending (no sweep ran): the yes is refused all the same."""
    world = World()
    approval_id = world.ask()
    world.clock.now = NOW + timedelta(minutes=11)
    world.service.expire_due = lambda: 0  # no tidying at all
    assert world.rows()[0].status == "pending"
    assert code_of(lambda: world.decide(approval_id)) == "APPROVAL_EXPIRED"
    assert world.gated.ran == [] and world.rows()[0].status == "expired"


def test_a_yes_that_arrives_after_the_deadline_is_refused_by_the_update_itself() -> None:
    """The service read the row just before the deadline (a stale read); the conditional update, made
    after it, is what says no."""
    world = World()
    approval_id = world.ask()
    real_get = world.service.store.get
    world.service.store.get = lambda key: dataclasses.replace(real_get(key), expires_at=NOW + timedelta(days=1))
    world.clock.now = NOW + timedelta(minutes=11)
    world.service.expire_due = lambda: 0
    assert code_of(lambda: world.decide(approval_id)) == "APPROVAL_EXPIRED"
    assert world.gated.ran == [] and world.rows()[0].status == "expired"


def test_switched_off_after_asking_nothing_runs_and_nothing_new_is_kept() -> None:
    world = World()
    approval_id = world.ask()
    off = world.make_service(enabled=False)
    assert code_of(lambda: world.decide(approval_id, service=off)) == "APPROVALS_DISABLED"
    assert code_of(lambda: off.list_for(GUILD, ME)) == "APPROVALS_DISABLED"
    assert code_of(lambda: off.request("send_note", {}, {"turn_id": TURN})) == "APPROVALS_DISABLED"
    assert world.gated.ran == [] and len(world.rows()) == 1


def test_a_server_that_leaves_the_allowlist_gets_nothing_run() -> None:
    world = World()
    approval_id = world.ask()
    world.allowed = frozenset()
    assert code_of(lambda: world.decide(approval_id)) == "GUILD_NOT_ALLOWED"
    assert world.gated.ran == [] and world.rows()[0].status == "pending"


def test_a_tool_that_breaks_after_the_yes_is_reported_and_never_run_twice() -> None:
    world = World()
    world.gated.fail = True
    approval_id = world.ask()
    decision = world.decide(approval_id)
    assert (decision.status, decision.code) == ("failed", "TOOL_FAILED")
    assert code_of(lambda: world.decide(approval_id)) == "APPROVAL_NOT_PENDING"
    assert len(world.gated.ran) == 1 and world.rows()[0].result_code == "TOOL_FAILED"


def test_a_tool_that_is_no_longer_gated_is_not_run_by_an_old_yes() -> None:
    world = World()
    approval_id = world.ask()
    world.agent.registry._tools["send_note"] = (60, AgentTool(world.agent.registry.get("send_note").schema, world.agent.registry.get("send_note").run))
    decision = world.decide(approval_id)
    assert decision.status == "failed" and decision.code == "UNKNOWN_TOOL" and world.gated.ran == []


def test_a_row_stuck_running_is_failed_after_the_lease_and_never_run_again() -> None:
    world = World()
    approval_id = world.ask()
    assert world.service.store.move(approval_id, "pending", "running", NOW, before_expiry=True)  # the process died here
    world.clock.now = NOW + policy.RUNNING_LEASE - timedelta(seconds=1)
    assert world.service.expire_due() == 0 and world.rows()[0].status == "running"
    world.clock.now = NOW + policy.RUNNING_LEASE + timedelta(seconds=1)
    assert world.service.expire_due() == 1
    assert (world.rows()[0].status, world.rows()[0].result_code) == ("failed", "interrupted")
    assert code_of(lambda: world.decide(approval_id)) == "APPROVAL_NOT_PENDING" and world.gated.ran == []


def test_a_failure_to_close_the_row_still_hands_back_the_result_once() -> None:
    world = World()
    approval_id = world.ask()
    real = world.service.store.move

    def move(approval_id, from_status, to_status, *args, **kwargs):
        if from_status == "running":
            raise RuntimeError("database went away")
        return real(approval_id, from_status, to_status, *args, **kwargs)

    world.service.store.move = move
    decision = world.decide(approval_id)
    assert decision.status == "done" and len(world.gated.ran) == 1
    assert world.rows()[0].status == "running"  # swept to failed later, never run again
    assert code_of(lambda: world.decide(approval_id)) == "APPROVAL_NOT_PENDING"


def test_a_tool_that_outlives_its_lease_still_returns_what_it_returned_and_is_not_run_again() -> None:
    """expire_due marked the row failed (interrupted) while the tool ran: the row cannot be closed, the member
    still gets the result, and a second yes finds nothing pending."""
    world = World()
    approval_id = world.ask()
    real = world.service.store.move

    def move(approval_id, from_status, to_status, *args, **kwargs):
        if from_status == "running":
            real(approval_id, "running", "failed", NOW, result_code="interrupted", stamp=False)  # the sweep got there first
        return real(approval_id, from_status, to_status, *args, **kwargs)

    world.service.store.move = move
    decision = world.decide(approval_id)
    assert decision.status == "done" and json.loads(decision.text) == {"sent": "Họp lúc 9h"}
    assert world.rows()[0].status == "failed" and world.rows()[0].result_code == "interrupted"
    assert code_of(lambda: world.decide(approval_id)) == "APPROVAL_NOT_PENDING"
    assert len(world.gated.ran) == 1


def test_the_reply_points_at_the_buttons_and_the_listing_names_the_turn_the_call_came_from() -> None:
    world = World()
    (reply, _, steps), _ = world.turn_with(calls("send_note", {"text": "Họp lúc 9h"}))
    assert steps[-1]["stop_reason"] == STOP_AWAITING_APPROVAL and "/approvals" in reply and "Mã duyệt:" in reply
    (item,) = api(world).get("/api/discord/approvals", params={"guild_id": GUILD, "author_id": ME}).json()
    assert item["source_turn_id"] == TURN and item["id"] != item["short_id"] and item["id"].startswith(item["short_id"])


# ---- the HTTP surface ----

def api(world: World) -> TestClient:
    app = FastAPI()
    app.include_router(approval_routes.router)
    app.state.approval_service = world.service
    return TestClient(app)


def test_the_routes_carry_the_decisions_and_the_refusals_with_their_codes() -> None:
    world = World()
    approval_id = world.ask()
    client = api(world)
    listed = client.get("/api/discord/approvals", params={"guild_id": GUILD, "author_id": ME}).json()
    assert [item["id"] for item in listed] == [approval_id] and listed[0]["tool_name"] == "send_note"
    assert client.get("/api/discord/approvals", params={"guild_id": GUILD, "author_id": YOU}).json() == []
    body = {"guild_id": GUILD, "actor_id": YOU}
    response = client.post(f"/api/discord/approvals/{approval_id}/approve", json=body)
    assert response.status_code == 403 and response.json()["detail"]["error_code"] == "APPROVAL_NOT_YOURS"
    assert client.post(f"/api/discord/approvals/{approval_id}/deny", json=body).status_code == 403
    assert client.post(f"/api/discord/approvals/{uuid4()}/approve", json={**body, "actor_id": ME}).status_code == 404
    assert world.gated.ran == []
    response = client.post(f"/api/discord/approvals/{approval_id}/approve", json={**body, "actor_id": ME})
    assert response.status_code == 200 and response.json()["status"] == "done" and json.loads(response.json()["text"]) == {"sent": "Họp lúc 9h"}
    assert client.post(f"/api/discord/approvals/{approval_id}/approve", json={**body, "actor_id": ME}).status_code == 409
    other = world.ask("việc khác")
    world.clock.now = NOW + timedelta(hours=1)
    assert client.post(f"/api/discord/approvals/{other}/approve", json={**body, "actor_id": ME}).status_code == 410
    assert len(world.gated.ran) == 1


def test_the_routes_say_plainly_when_approvals_are_off() -> None:
    world = World(enabled=False)
    client = api(world)
    response = client.get("/api/discord/approvals", params={"guild_id": GUILD, "author_id": ME})
    assert response.status_code == 409 and response.json()["detail"]["error_code"] == "APPROVALS_DISABLED"
    response = client.post(f"/api/discord/approvals/{uuid4()}/approve", json={"guild_id": GUILD, "actor_id": ME})
    assert response.status_code == 409 and world.gated.ran == []


# ---- start-up and the schema ----

def test_the_default_wiring_gives_the_agent_no_gate_and_the_switch_gives_it() -> None:
    def wire(**flags):
        settings = Settings(_env_file=None, database_url="postgresql+psycopg://test:test@127.0.0.1:1/none", **flags)
        sessions = create_session_factory(create_postgres_engine(str(settings.database_url)))  # never connects here
        agent = SimpleNamespace(registry=core_tools(), approvals=None)
        app = SimpleNamespace(state=SimpleNamespace(memory_service=object(), chat_service=object(), agent_service=agent))
        discord.register_services(app, settings, sessions, project_root=PROJECT_ROOT)
        return app, agent

    app, agent = wire()
    assert agent.approvals is None and app.state.approval_service.enabled is False
    app, agent = wire(discord_approvals_enabled=True, discord_approval_ttl_seconds=900)
    assert agent.approvals is app.state.approval_service and app.state.approval_service.ttl == timedelta(minutes=15)


def test_the_migration_adds_one_table_with_a_way_back_and_the_row_follows_its_turn() -> None:
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20261102_38_discord_approvals.py"
    migration = path.read_text(encoding="utf-8")
    assert 'revision = "20261102_38"' in migration and 'down_revision = "20261101_37"' in migration
    assert 'op.create_table(\n        "discord_approvals"' in migration and 'op.drop_table("discord_approvals")' in migration
    assert 'ForeignKey("discord_session_turns.id", ondelete="CASCADE")' in migration
    (key,) = DiscordApproval.__table__.c.source_turn_id.foreign_keys
    assert key.target_fullname == "discord_session_turns.id" and key.ondelete == "CASCADE"
    heads = [p.name for p in path.parent.glob("2026*.py") if p.name > path.name]
    assert heads == ["20261109_39_source_memory.py"], "recheck the migration chain"


# ---- forgetting a member ----

def add_row(database, *, requester: str, guild: str, turn: UUID | None = None, status: str = "pending") -> None:
    database.add(DiscordApproval(
        guild_id=guild, channel_id="chan", requester_id=requester, tool_name="send_note", arguments='{"text": "lời của tôi"}',
        status=status, expires_at=NOW + timedelta(minutes=10), source_turn_id=turn,
    ))


def test_forget_member_deletes_every_approval_asked_of_them_in_every_state_and_only_theirs() -> None:
    engine = create_engine("sqlite://")
    DiscordApproval.__table__.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as database:
        for status in ("pending", "running", "done", "failed", "denied", "expired"):
            add_row(database, requester=ME, guild=GUILD, status=status)
        add_row(database, requester=ME, guild=OTHER_GUILD)
        add_row(database, requester=YOU, guild=GUILD)
    with sessions.begin() as database:
        assert _forget_approvals(database, ME, GUILD) == 6  # the guild where they asked
    with sessions() as database:
        assert sorted((row.requester_id, row.guild_id) for row in database.scalars(select(DiscordApproval))) == [(ME, OTHER_GUILD), (YOU, GUILD)]
    with sessions.begin() as database:
        assert _forget_approvals(database, ME, None) == 1  # every guild
    with sessions() as database:
        assert [row.requester_id for row in database.scalars(select(DiscordApproval))] == [YOU]


def test_forget_member_counts_and_deletes_approvals_in_the_script_itself() -> None:
    """The script's own lists name approvals in all three places (guilds, counts, delete), so a member
    who has only an approval is found, shown in the dry run and cleared by --apply."""
    source = (Path(__file__).parents[1] / "scripts" / "forget_member.py").read_text(encoding="utf-8")
    assert "select(DiscordApproval.guild_id).where(DiscordApproval.requester_id == author_id)" in source
    assert '"approvals": count(DiscordApproval, DiscordApproval.requester_id == author_id)' in source
    assert "_forget_approvals(database, author_id, scope)" in source


URL = os.getenv("POSTGRES_TEST_URL")


@pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")
def test_postgres_deleting_the_turn_takes_its_approval_and_forget_member_clears_the_rest(monkeypatch) -> None:
    from app.postgres.models import DiscordConversationSession, DiscordSessionTurn
    from scripts.forget_member import forget

    factory = create_session_factory(create_postgres_engine(str(URL)))
    tag = uuid4().hex[:8]
    guild, author, bystander = f"guild-{tag}", f"a-{tag}", f"b-{tag}"
    session_id, turn_a = uuid4(), uuid4()
    with factory.begin() as database:
        database.add(DiscordConversationSession(id=session_id, guild_id=guild, channel_id="c1", backend_conversation_id=uuid4()))
        database.flush()
        database.add(DiscordSessionTurn(
            id=turn_a, session_id=session_id, discord_message_id=f"t1{tag}", sequence_number=1,
            request_text="Gửi ghi chú", response_text="Cần duyệt.", author_id=author, author_display_name="Lan", status="completed",
        ))
        database.flush()
        add_row(database, requester=author, guild=guild, turn=turn_a)
        add_row(database, requester=author, guild=guild)  # no turn behind it: only the script can reach it
        add_row(database, requester=bystander, guild=guild)

    def count(who: str) -> int:
        with factory() as database:
            return int(database.scalar(select(func.count()).select_from(DiscordApproval).where(DiscordApproval.guild_id == guild, DiscordApproval.requester_id == who)))

    try:
        with factory.begin() as database:
            database.execute(delete(DiscordSessionTurn).where(DiscordSessionTurn.id == turn_a))
        assert count(author) == 1  # the turn took its approval with it
        monkeypatch.setenv("DATABASE_URL", str(URL))
        report = forget(guild, author, apply=True)
        assert report["planned"]["approvals"] == 1 and report["remaining"]["approvals"] == 0
        assert count(author) == 0 and count(bystander) == 1
    finally:
        with factory.begin() as database:
            database.execute(delete(DiscordApproval).where(DiscordApproval.guild_id == guild))
            database.execute(delete(DiscordConversationSession).where(DiscordConversationSession.id == session_id))
