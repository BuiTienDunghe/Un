"""The promise check (03/11): the speaker asked for something only a tool does ("nhắc tôi 5 phút nữa
...") and the model answered without calling it. On Discord it said "Ún sẽ nhắc lúc 13:53" and
nothing was scheduled. The model is asked once more, for the tool's arguments alone in a structured
output, and the tool runs; without structured output the turn is sent back in words. No model, no GPU."""
from __future__ import annotations

import json
from types import SimpleNamespace

from app.discord.remind_tool import REMIND_FILL, REMIND_RETRY, Remind, TurnFacts, register
from app.services.agent_service import PROMISE_CHECK_STEP, AgentService, AgentTool, core_tools
from app.services.call_budget import OVERRUNS, agent_call_cap
from tests.test_discord_reminders import GUILD, ME, build

ASKED = "nhắc mình uống nước 5 phút nữa nhé"
# The real answer named an hour; without one the answer check stays out of these tests.
CLAIMED = "Được, Ún sẽ nhắc bạn uống nước."
TURN = "11111111-1111-1111-1111-111111111111"


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def call(name: str, arguments: dict) -> dict:
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}], "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


class Router:
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.prompts: list[list[dict]] = []

    def chat_tools(self, role, messages, tools):
        self.prompts.append([dict(message) for message in messages])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages, options=None):
        self.prompts.append([dict(message) for message in messages])
        return "hết lượt", "fake"


class StructuredRouter(Router):
    """Also serves structured outputs: `filled` is the JSON text, or an exception to raise."""

    def __init__(self, rounds, filled):
        super().__init__(rounds)
        self.filled = filled
        self.schemas: list[dict] = []
        self.structured_prompts: list[list[dict]] = []

    def chat_structured(self, role, messages, schema):
        self.schemas.append(schema)
        self.structured_prompts.append([dict(message) for message in messages])
        if isinstance(self.filled, Exception):
            raise self.filled
        return self.filled, "fake"


def wired(rounds, own_text=ASKED, filled=None):
    """An agent with the real remind tool, its gate reading `own_text` as the speaker's words. With
    `filled`, the router serves structured outputs and the tool carries REMIND_FILL."""
    service = build()[0]
    registry = core_tools()
    tool = Remind(service, lambda turn_id: TurnFacts(GUILD, "chan", None, ME, own_text))
    from app.discord import remind_tool
    registry.register(AgentTool(
        remind_tool.REMIND_SCHEMA, tool, "Đang hẹn giờ nhắc…", promised=remind_tool.promised_by(tool.load_turn), promise_retry=REMIND_RETRY,
        promise_fill=REMIND_FILL if filled is not None else None,
    ), remind_tool.ORDER)
    router = StructuredRouter(rounds, filled) if filled is not None else Router(rounds)
    agent = AgentService(router, SimpleNamespace(), SimpleNamespace(), registry=registry)
    return agent, router, service


def run(agent, text=ASKED):
    answer, _, steps = agent.run([{"role": "system", "content": "Bạn là Ún."}, {"role": "user", "content": text}], tool_context={"turn_id": TURN})
    return answer, steps


def kinds(steps):
    return [step["kind"] for step in steps]


REMIND = call("remind", {"text": "uống nước", "in_minutes": 5})


FILLED = json.dumps({"requested": True, "text": "uống nước", "in_minutes": 5, "at": None})


def test_an_answer_that_claims_a_reminder_it_never_set_has_the_reminder_set_from_a_structured_call():
    agent, router, service = wired([final(CLAIMED), final("Ún sẽ nhắc bạn uống nước lúc 10:05.")], filled=FILLED)
    answer, steps = run(agent)
    assert answer == "Ún sẽ nhắc bạn uống nước lúc 10:05."
    assert len(service.list_for(GUILD, ME)) == 1 and service.list_for(GUILD, ME)[0].text == "uống nước"
    call_step = next(s for s in steps if s["kind"] == "tool_call")
    assert call_step["tool_name"] == "remind" and call_step["constrained"] is True and call_step["arguments"] == {"text": "uống nước", "in_minutes": 5}
    # The model writes the answer having seen the tool's result, and never its own claim.
    last = router.prompts[-1]
    assert last[-1]["role"] == "tool" and "scheduled" in last[-1]["content"]
    assert CLAIMED not in [message.get("content") for message in last]
    assert kinds(steps) == [PROMISE_CHECK_STEP, "tool_call", "tool_result", "final"]


def test_the_structured_call_holds_every_key_and_lets_the_optional_ones_be_null():
    agent, router, _ = wired([final(CLAIMED), final("Ún sẽ nhắc bạn.")], filled=FILLED)
    run(agent)
    schema = router.schemas[0]
    assert schema["required"] == ["requested", "text", "in_minutes", "at"] and schema["properties"]["requested"]["type"] == "boolean"
    assert schema["properties"]["text"]["type"] == "string" and schema["properties"]["in_minutes"]["type"] == ["integer", "null"]
    asked = router.structured_prompts[0][-1]["content"]
    assert REMIND_FILL in asked and "Lịch:" in asked and "(hôm nay)" in asked


def test_arguments_the_tool_refuses_are_refused_as_the_models_own_would_be():
    filled = json.dumps({"requested": True, "text": "đi ăn tối với sếp", "in_minutes": 5, "at": None})
    agent, _, service = wired([final(CLAIMED), final("Mình chưa hẹn được.")], filled=filled)
    _, steps = run(agent)
    assert service.list_for(GUILD, ME) == []
    assert next(s for s in steps if s["kind"] == "tool_result")["error_code"] == "BAD_ARGUMENTS"


def test_a_structured_reply_that_is_not_an_object_falls_back_to_the_retry_in_words():
    agent, router, service = wired([final(CLAIMED), REMIND, final("Ún sẽ nhắc bạn.")], filled="không phải JSON")
    run(agent)
    assert router.prompts[1][-1] == {"role": "system", "content": REMIND_RETRY}
    assert len(service.list_for(GUILD, ME)) == 1


def test_a_provider_without_structured_output_falls_back_to_the_retry_in_words():
    agent, router, _ = wired([final(CLAIMED), REMIND, final("Ún sẽ nhắc bạn.")], filled=NotImplementedError("not ollama"))
    run(agent)
    assert router.prompts[1][-1] == {"role": "system", "content": REMIND_RETRY}


def test_an_answer_that_claims_a_reminder_it_never_set_is_sent_back_and_the_reminder_is_set():
    agent, router, service = wired([final(CLAIMED), REMIND, final("Ún sẽ nhắc bạn uống nước.")])
    answer, steps = run(agent)
    assert answer == "Ún sẽ nhắc bạn uống nước."
    assert kinds(steps)[0] == PROMISE_CHECK_STEP and "remind" in [s["tool_name"] for s in steps if s["kind"] == "tool_call"]
    assert router.prompts[1][-1] == {"role": "system", "content": REMIND_RETRY}
    assert len(service.list_for(GUILD, ME)) == 1


def test_the_rejected_answer_reaches_no_one():
    agent, _, _ = wired([final(CLAIMED), REMIND, final("Ún sẽ nhắc bạn.")])
    _, steps = run(agent)
    assert next(s for s in steps if s["kind"] == PROMISE_CHECK_STEP)["content"] is None


def test_it_goes_back_once_and_a_request_still_not_kept_is_said_by_the_code():
    agent, router, service = wired([final(CLAIMED), final(CLAIMED)])
    answer, steps = run(agent)
    assert answer.startswith(CLAIMED) and "chưa thực hiện được" in answer and "remind" in answer
    assert kinds(steps).count(PROMISE_CHECK_STEP) == 1
    assert service.list_for(GUILD, ME) == []
    assert CLAIMED not in [message.get("content") for message in router.prompts[1]], "the model does not reread its own claim"


def test_a_turn_that_called_the_tool_is_left_alone():
    agent, router, _ = wired([REMIND, final("Ún sẽ nhắc bạn.")])
    _, steps = run(agent)
    assert PROMISE_CHECK_STEP not in kinds(steps) and len(router.prompts) == 2


def test_no_request_no_check():
    agent, router, _ = wired([final("Uống nước nhiều là tốt.")], own_text="uống nước có tốt không")
    _, steps = run(agent, "uống nước có tốt không")
    assert PROMISE_CHECK_STEP not in kinds(steps) and len(router.prompts) == 1


def test_a_request_with_no_hour_is_for_asking_back_not_for_the_check():
    agent, router, _ = wired([final("Bạn muốn được nhắc lúc nào?")], own_text="nhắc mình uống nước")
    _, steps = run(agent, "nhắc mình uống nước")
    assert PROMISE_CHECK_STEP not in kinds(steps) and len(router.prompts) == 1


def test_outside_discord_there_is_no_turn_to_read_and_no_check():
    agent, router, _ = wired([final(CLAIMED)])
    answer, _, steps = agent.run([{"role": "user", "content": ASKED}])
    assert answer == CLAIMED and PROMISE_CHECK_STEP not in kinds(steps)


def test_a_gate_that_fails_never_costs_the_answer():
    def broken(turn_id):
        raise RuntimeError("database down")
    service = build()[0]
    registry = core_tools()
    from app.discord import remind_tool
    registry.register(AgentTool(remind_tool.REMIND_SCHEMA, Remind(service, broken), None, promised=remind_tool.promised_by(broken), promise_retry=REMIND_RETRY), remind_tool.ORDER)
    agent = AgentService(Router([final(CLAIMED)]), SimpleNamespace(), SimpleNamespace(), registry=registry)
    answer, steps = run(agent)
    assert answer == CLAIMED and PROMISE_CHECK_STEP not in kinds(steps)


def test_register_wires_the_check_with_the_tool():
    registry = core_tools()
    register(registry, build()[0], sessions=None)
    tool = registry.get("remind")
    assert tool.promised is not None and tool.promise_retry == REMIND_RETRY and tool.promise_fill == REMIND_FILL


def test_the_cap_grows_by_two_only_when_a_tool_carries_a_promise():
    OVERRUNS.clear()
    agent, _, _ = wired([final(CLAIMED), REMIND, REMIND, REMIND, REMIND])
    run(agent)
    agent, _, _ = wired([final(CLAIMED), REMIND, REMIND, REMIND], filled=FILLED)
    run(agent)
    assert not OVERRUNS
    assert agent_call_cap(3, promise_check=True) == agent_call_cap(3) + 2
    plain = AgentService(Router([final("x")]), SimpleNamespace(), SimpleNamespace())
    assert not any(tool.promised for tool in plain.registry.tools())


# ---- review 06/11 ----

def test_when_the_model_says_nothing_was_asked_the_answer_stands_with_no_note():
    # "Sếp bảo: nhắc tôi họp lúc 3 giờ chiều. Câu đó nghĩa là sao?" passes the word gate.
    quoted = "Sếp bảo: nhắc tôi họp lúc 3 giờ chiều. Câu đó nghĩa là sao?"
    explained = "Câu đó là sếp dặn bạn tự nhớ cuộc họp chiều nay."
    declined = json.dumps({"requested": False, "text": None, "in_minutes": None, "at": None})
    agent, router, service = wired([final(explained)], own_text=quoted, filled=declined)
    answer, steps = run(agent, quoted)
    assert answer == explained and "chưa thực hiện" not in answer
    assert service.list_for(GUILD, ME) == [] and len(router.prompts) == 1
    step = next(s for s in steps if s["kind"] == PROMISE_CHECK_STEP)
    assert step["arguments_shape"] == {"declined": True}


def test_a_thank_you_after_a_reminder_is_no_second_request():
    # Read with the request before it, "hôm nay" made the check set the same reminder again.
    service = build()[0]
    registry = core_tools()
    from app.discord import remind_tool
    facts = TurnFacts(GUILD, "chan", None, ME, own_text=f"{ASKED} cảm ơn, hôm nay mệt quá", request_text="cảm ơn, hôm nay mệt quá")
    tool = Remind(service, lambda turn_id: facts)
    registry.register(AgentTool(remind_tool.REMIND_SCHEMA, tool, None, promised=remind_tool.promised_by(tool.load_turn), promise_retry=REMIND_RETRY, promise_fill=REMIND_FILL), remind_tool.ORDER)
    router = StructuredRouter([final("Nghỉ ngơi chút nhé.")], FILLED)
    agent = AgentService(router, SimpleNamespace(), SimpleNamespace(), registry=registry)
    answer, steps = run(agent, "cảm ơn, hôm nay mệt quá")
    assert answer == "Nghỉ ngơi chút nhé." and PROMISE_CHECK_STEP not in kinds(steps)
    assert router.schemas == [] and service.list_for(GUILD, ME) == []


def test_a_remind_call_the_tool_refused_is_not_counted_as_kept():
    bad = call("remind", {"text": "uống nước", "at": "15:00"})
    agent, _, service = wired([bad, final(CLAIMED), final("Ún sẽ nhắc bạn.")], filled=FILLED)
    _, steps = run(agent)
    assert next(s for s in steps if s["kind"] == "tool_result")["error_code"] == "BAD_ARGUMENTS"
    assert PROMISE_CHECK_STEP in kinds(steps) and len(service.list_for(GUILD, ME)) == 1
