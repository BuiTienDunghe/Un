"""The promise check (03/11): the speaker asked for something only a tool does ("nhắc tôi 5 phút nữa
...") and the model answered without calling it. On Discord it said "Ún sẽ nhắc lúc 13:53" and
nothing was scheduled. The turn is sent back once to call the tool. No model, no GPU."""
from __future__ import annotations

from types import SimpleNamespace

from app.discord.remind_tool import REMIND_RETRY, Remind, TurnFacts, register
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


def wired(rounds, own_text=ASKED):
    """An agent with the real remind tool, its gate reading `own_text` as the speaker's words."""
    service = build()[0]
    registry = core_tools()
    tool = Remind(service, lambda turn_id: TurnFacts(GUILD, "chan", None, ME, own_text))
    from app.discord import remind_tool
    registry.register(AgentTool(remind_tool.REMIND_SCHEMA, tool, "Đang hẹn giờ nhắc…", promised=remind_tool.promised_by(tool.load_turn), promise_retry=REMIND_RETRY), remind_tool.ORDER)
    router = Router(rounds)
    agent = AgentService(router, SimpleNamespace(), SimpleNamespace(), registry=registry)
    return agent, router, service


def run(agent, text=ASKED):
    answer, _, steps = agent.run([{"role": "system", "content": "Bạn là Ún."}, {"role": "user", "content": text}], tool_context={"turn_id": TURN})
    return answer, steps


def kinds(steps):
    return [step["kind"] for step in steps]


REMIND = call("remind", {"text": "uống nước", "in_minutes": 5})


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
    assert tool.promised is not None and tool.promise_retry == REMIND_RETRY


def test_the_cap_grows_by_one_only_when_a_tool_carries_a_promise():
    OVERRUNS.clear()
    agent, _, _ = wired([final(CLAIMED), REMIND, REMIND, REMIND, REMIND])
    run(agent)
    assert not OVERRUNS
    assert agent_call_cap(3, promise_check=True) == agent_call_cap(3) + 1
    plain = AgentService(Router([final("x")]), SimpleNamespace(), SimpleNamespace())
    assert not any(tool.promised for tool in plain.registry.tools())
