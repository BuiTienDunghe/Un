"""Ticket 46: ask_user — one question back when a needed fact is missing. No database, no model: the model is scripted.

Off by default (the tool list and every message the model reads are the ones it always had); on, a call ends the
turn with the question as the reply, at most once per turn.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.services import ask_user
from app.services.agent_service import STOP_ASKED_USER, STOP_FINAL, AgentService, ToolRegistry, core_tools

QUESTION = "Bạn muốn đặt lịch cho ngày nào?"


class Router:
    def __init__(self, rounds):
        self.rounds, self.tools_seen, self.messages_seen, self.plain_chats = list(rounds), [], [], 0

    def chat_tools(self, role, messages, tools):
        self.tools_seen.append([tool["function"]["name"] for tool in tools])
        self.messages_seen.append(json.dumps(messages, ensure_ascii=False, sort_keys=True))
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        self.plain_chats += 1
        return "đã trả lời", "fake"


def calls(*pairs: tuple[str, dict]) -> dict:
    return {
        "content": "",
        "tool_calls": [{"name": name, "arguments": arguments} for name, arguments in pairs],
        "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}} for name, arguments in pairs],
    }


def answer(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def agent_with_ask(*rounds: dict) -> tuple[AgentService, Router]:
    registry = core_tools()
    ask_user.register(registry)
    router = Router(rounds)
    return AgentService(router, None, None, registry=registry), router


def run(agent: AgentService):
    return agent.run([{"role": "user", "content": "đặt lịch họp giúp tôi"}])


def test_it_is_off_unless_its_own_flag_is_set() -> None:
    assert Settings.model_fields["agent_ask_user_enabled"].default is False
    assert "ask_user" not in core_tools().names()
    # main.py registers it only behind the flag, after the Discord tools and next to web_tools.
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "if settings.agent_ask_user_enabled:" in source.replace("\r\n", "\n")


def test_off_the_model_is_shown_the_same_tools_and_the_same_messages_as_before() -> None:
    plain = AgentService(Router([answer("xong")]), None, None)
    registry = core_tools()
    other = AgentService(Router([answer("xong")]), None, None, registry=registry)
    assert core_tools().names() == ("search_documents", "read_document", "system_status", "current_time", "calculate")
    assert plain._offered_schemas() == other._offered_schemas() == core_tools().schemas()
    run(plain), run(other)
    assert plain.router.tools_seen == other.router.tools_seen
    assert plain.router.messages_seen == other.router.messages_seen
    assert "ask_user" not in plain.router.tools_seen[0] and "ask_user" not in plain.router.messages_seen[0]


def test_on_it_is_one_more_tool_and_the_rest_of_the_list_does_not_move() -> None:
    agent, router = agent_with_ask(answer("xong"))
    run(agent)
    assert router.tools_seen[0] == [*core_tools().names(), "ask_user"]


def test_a_call_ends_the_turn_with_the_question_and_the_model_is_not_called_again() -> None:
    agent, router = agent_with_ask(calls(("ask_user", {"question": QUESTION})))
    reply, _, steps = run(agent)
    assert reply == QUESTION
    assert len(router.tools_seen) == 1 and router.plain_chats == 0
    assert steps[-1]["kind"] == "final" and steps[-1]["stop_reason"] == STOP_ASKED_USER
    assert [step["kind"] for step in steps] == ["tool_call", "tool_result", "final"]
    assert steps[1]["content"] is None  # the question is in the final step only, like the other ending


def test_two_questions_in_one_round_ask_one() -> None:
    agent, router = agent_with_ask(calls(("ask_user", {"question": "Câu một?"}), ("ask_user", {"question": "Câu hai?"})))
    reply, _, steps = run(agent)
    assert reply == "Câu một?"
    assert sum(step["kind"] == "tool_call" and step["tool_name"] == "ask_user" for step in steps) == 1
    assert len(router.tools_seen) == 1


def test_a_lookup_before_the_question_still_runs_and_one_after_it_does_not() -> None:
    agent, router = agent_with_ask(calls(
        ("current_time", {}), ("ask_user", {"question": QUESTION}), ("calculate", {"expression": "1+1"}),
    ))
    reply, _, steps = run(agent)
    assert reply == QUESTION
    assert [step["tool_name"] for step in steps if step["kind"] == "tool_call"] == ["current_time", "ask_user"]


def test_an_empty_or_overlong_question_is_a_tool_error_the_model_can_correct_not_a_reply() -> None:
    for bad in ({}, {"question": "   "}, {"question": "x" * (ask_user.QUESTION_MAX_CHARS + 1)}):
        agent, router = agent_with_ask(calls(("ask_user", bad)), answer("Mình tự trả lời."))
        reply, _, steps = run(agent)
        assert reply == "Mình tự trả lời."
        assert steps[-1]["stop_reason"] == STOP_FINAL
        (result,) = [step for step in steps if step["kind"] == "tool_result"]
        assert result["error_code"] == "BAD_ARGUMENTS"


def test_a_mention_in_the_question_cannot_ping() -> None:
    agent, _ = agent_with_ask(calls(("ask_user", {"question": "@everyone, @here và <@123> chọn ngày nào?"})))
    reply, _, _ = run(agent)
    assert "@everyone" not in reply and "@here" not in reply and "<@123>" not in reply
    assert "chọn ngày nào?" in reply


def test_the_question_is_not_the_arguments_content_in_the_summary_trace() -> None:
    from app.services.agent_service import arguments_shape

    registry = core_tools()
    ask_user.register(registry)
    assert arguments_shape("ask_user", {"question": QUESTION}, registry.declared()) == {"question": f"str:{len(QUESTION)}"}


def test_it_is_registered_after_calculate_and_before_the_web_tools() -> None:
    registry = ToolRegistry()
    ask_user.register(registry)
    assert ask_user.ORDER > 50 and ask_user.ORDER < 60
