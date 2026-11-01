"""BFCL through Ún's agent loop (ticket 42): the runner and the scorer, with a scripted model.

The model is a script (calls taken from BFCL's own ground truth), so no GPU and no Ollama. The
tests that need the BFCL clone skip without it; the last one also needs bfcl-venv and runs the
real scorer on what the runner wrote, which is the check that matters: the state the loop
executed is the state BFCL's replay reaches, so a run that makes the ground truth's calls
scores full marks.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.services.agent_service import AgentService
from scripts import bfcl_run
from scripts.agent_eval import UsageRecordingRouter

CLONE = bfcl_run.DEFAULT_CLONE
BFCL_PYTHON = Path(r"C:\Users\dungbt06\tools\bfcl-venv\Scripts\python.exe")
SCORER = Path(bfcl_run.BACKEND) / "scripts" / "bfcl_score.py"
needs_clone = pytest.mark.skipif(not (CLONE / "bfcl_eval" / "data").is_dir(), reason="no BFCL clone")


def bfcl_venv_can_score() -> bool:
    """bfcl-venv exists and imports the checker (which imports every vendor's handler, and so
    qwen_agent, and so soundfile)."""
    if not BFCL_PYTHON.is_file():
        return False
    probe = subprocess.run([str(BFCL_PYTHON), "-c", "import soundfile, bfcl_eval.model_handler.base_handler"], capture_output=True, text=True, timeout=120)
    return probe.returncode == 0


needs_scorer = pytest.mark.skipif(not bfcl_venv_can_score(), reason="bfcl-venv cannot import the checker (soundfile missing?)")


class Scripted:
    """A model that answers from a queue; each queued round is calls or an answer. Remembers the
    tool names and the messages it was shown on every round."""

    def __init__(self, rounds: list[Any]) -> None:
        self.rounds, self.tools_seen, self.messages_seen = list(rounds), [], []

    def chat_tools(self, role, messages, tools):
        self.tools_seen.append([tool["function"]["name"] for tool in tools])
        self.messages_seen.append(list(messages))
        round_ = self.rounds.pop(0)
        if isinstance(round_, str):
            return {"content": round_, "tool_calls": [], "raw_tool_calls": []}, "fake"
        calls = [{"name": name, "arguments": arguments} for name, arguments in round_]
        return {"content": "", "tool_calls": calls, "raw_tool_calls": [{"function": call} for call in calls]}, "fake"

    def chat(self, role, messages, options=None):
        return "xong", "fake"


def agent_factory(recording: UsageRecordingRouter):
    return lambda registry: AgentService(recording, None, None, registry=registry)


def parse_call(text: str, docs: dict[str, list[str]] | None = None) -> tuple[str, dict[str, Any]]:
    """A ground-truth call string back into (name, arguments). The ground truth writes some
    arguments by position; a model calls by name, so `docs` (function -> parameter names in
    order) names them."""
    call = ast.parse(text, mode="eval").body
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name), text
    names = (docs or {}).get(call.func.id, [])
    arguments = {names[index]: ast.literal_eval(value) for index, value in enumerate(call.args)}
    arguments.update({keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords})
    return call.func.id, arguments


def parameter_names(entry: dict[str, Any]) -> dict[str, list[str]]:
    return {doc["name"]: list(doc["parameters"]["properties"]) for doc in entry["function"]}


def ground_truth(category: str, entry_id: str) -> Any:
    path = CLONE / "bfcl_eval" / "data" / "possible_answer" / f"BFCL_v4_{category}.json"
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["id"] == entry_id:
            return row["ground_truth"]
    raise KeyError(entry_id)


def oracle_multi_turn(entry_id: str) -> list[Any]:
    """Per turn: one round with every call of the ground truth, then an answer."""
    docs = parameter_names(bfcl_run.Bfcl(CLONE).load_entries("multi_turn_base", [entry_id])[0])
    rounds: list[Any] = []
    for turn in ground_truth("multi_turn_base", entry_id):
        rounds.append([parse_call(call, docs) for call in turn])
        rounds.append("xong")
    return rounds


def oracle_single_turn(category: str, entry_id: str) -> list[Any]:
    """The first allowed value of each parameter, an optional one (the empty string allowed) left out."""
    calls = []
    for expected in ground_truth(category, entry_id):
        (name, options), = expected.items()
        arguments = {key: values[0] for key, values in options.items() if values[0] != ""}
        calls.append((name.replace(".", "_"), arguments))
    return [calls, "xong"]


def run_one(category: str, entry_id: str, rounds: list[Any], tag: str = "test-run") -> tuple[dict[str, Any], Scripted]:
    bfcl = bfcl_run.Bfcl(CLONE)
    model = Scripted(rounds)
    recording = UsageRecordingRouter(model)
    entry = bfcl.load_entries(category, [entry_id])[0]
    return bfcl_run.run_entry(bfcl, entry, category, recording, agent_factory(recording), tag), model


# ── pure: no clone ───────────────────────────────────────────────────────


def test_a_call_is_spelled_the_way_bfcls_decode_execute_spells_it():
    arguments = {"count": 3, "ratio": 0.5, "items": [1, "a"], "flag": True, "text": "it's \"x\"", "nothing": None}
    recorded = json.dumps(arguments, ensure_ascii=False)
    assert bfcl_run.call_string("fn", recorded) == (
        "fn(count=3,ratio=0.5,items=[1, 'a'],flag=True,text='it\\'s \"x\"',nothing=None)"
    )
    name, parsed = parse_call(bfcl_run.call_string("fn", recorded))
    assert (name, parsed) == ("fn", arguments), "what is executed round-trips to what the model sent"


def test_the_ids_file_is_the_33_tasks_of_the_design():
    ids = bfcl_run.load_ids()
    assert {category: len(members) for category, members in ids.items()} == {
        "simple_python": 10, "multiple": 8, "irrelevance": 7, "multi_turn_base": 5, "multi_turn_miss_func": 3,
    }
    assert sum(len(members) for members in ids.values()) == 33
    assert all(member.rsplit("_", 1)[0] == category for category, members in ids.items() for member in members)


def test_only_narrows_the_ids_and_refuses_one_that_is_not_there():
    ids = bfcl_run.load_ids()
    assert bfcl_run.select(ids, "simple_python_6,multi_turn_base_77") == {"simple_python": ["simple_python_6"], "multi_turn_base": ["multi_turn_base_77"]}
    with pytest.raises(ValueError, match="simple_python_7"):
        bfcl_run.select(ids, "simple_python_7")


def test_the_seam_the_runner_relies_on_takes_the_tasks_own_registry():
    registry = bfcl_run.ToolRegistry()
    assert AgentService(None, None, None, registry=registry).registry is registry


# ── the clone ────────────────────────────────────────────────────────────


@needs_clone
def test_the_runner_reads_the_clone_without_writing_to_it():
    bfcl = bfcl_run.Bfcl(CLONE)
    assert bfcl.commit().startswith(bfcl_run.CLONE_COMMIT)
    assert sys.dont_write_bytecode is True


@needs_clone
def test_a_function_doc_becomes_the_openai_style_tool_bfcl_sends():
    bfcl = bfcl_run.Bfcl(CLONE)
    entry = bfcl.load_entries("simple_python", ["simple_python_14"])[0]
    doc = entry["function"][0]
    assert doc["description"].endswith(bfcl_run.HINT)
    tool = bfcl.to_tool({**doc, "name": "math.factorial", "response": {"type": "dict"}})
    function = tool["function"]
    assert tool["type"] == "function" and function["name"] == "math_factorial"
    assert function["parameters"]["type"] == "object" and "response" not in function
    assert all(value["type"] != "dict" for value in function["parameters"]["properties"].values())
    assert "response" not in doc and doc["parameters"]["type"] == "dict", "the entry's own doc is not edited"


@needs_clone
def test_a_task_that_runs_nothing_keeps_the_answer_text_and_a_task_that_calls_keeps_the_calls():
    line, model = run_one("irrelevance", "irrelevance_0", ["Không có hàm nào dùng được."])
    assert line["result"] == "Không có hàm nào dùng được."
    assert line["inference_log"][0]["stop_reason"] == "final"

    call = oracle_single_turn("simple_python", "simple_python_6")
    line, _ = run_one("simple_python", "simple_python_6", call)
    name = call[0][0][0]
    assert [list(c) for c in line["result"]] == [[name]]
    assert json.loads(line["result"][0][name]) == call[0][0][1]


# ── multi-turn: the loop's state is BFCL's ───────────────────────────────


@needs_clone
def test_a_multi_turn_task_is_recorded_by_turn_and_round_and_leaves_no_instance_behind():
    entry_id = "multi_turn_base_77"
    docs = parameter_names(bfcl_run.Bfcl(CLONE).load_entries("multi_turn_base", [entry_id])[0])
    rounds = oracle_multi_turn(entry_id)
    line, model = run_one("multi_turn_base", entry_id, rounds)

    truth = ground_truth("multi_turn_base", entry_id)
    assert len(line["result"]) == len(truth), "one list per turn, or BFCL fails the task as force_terminated"
    for turn, expected in zip(line["result"], truth):
        calls, answer = turn[:-1], turn[-1]
        assert answer == "xong"
        assert [bfcl_run.call_string(next(iter(c)), next(iter(c.values()))) for step in calls for c in step] == [
            bfcl_run.call_string(name, json.dumps(arguments, ensure_ascii=False)) for name, arguments in (parse_call(call, docs) for call in expected)
        ]
    assert all(len(line[key]) == len(truth) for key in ("input_token_count", "output_token_count", "latency"))
    errors = [step["error_code"] for turn in line["inference_log"] for step in turn["steps"] if step.get("error_code")]
    assert errors == []
    leftover = [key for key in vars(bfcl_run.Bfcl(CLONE).utils) if key.endswith("_instance") and "test_run" in key]
    assert leftover == []
    # The earlier turns reach the model as text only, as the chat path hands history to the agent.
    last_turn_messages = model.messages_seen[-2]
    assert [m["role"] for m in last_turn_messages if m["role"] in ("assistant", "tool")] == ["assistant"] * (len(truth) - 1)


@needs_clone
def test_the_held_out_function_appears_at_its_turn_with_the_fixed_user_sentence():
    bfcl = bfcl_run.Bfcl(CLONE)
    entry = bfcl.load_entries("multi_turn_miss_func", ["multi_turn_miss_func_143"])[0]
    turn_of_holdout, (name,) = next((int(turn), [doc["name"] for doc in docs]) for turn, docs in entry["missed_function"].items())
    assert entry["question"][turn_of_holdout] == [], "the data's own turn is empty"
    model = Scripted(["xong"] * len(entry["question"]))
    recording = UsageRecordingRouter(model)
    line = bfcl_run.run_entry(bfcl, entry, "multi_turn_miss_func", recording, agent_factory(recording), "test-run")

    assert [name in tools for tools in model.tools_seen] == [index >= turn_of_holdout for index in range(len(entry["question"]))]
    sentence = [m["content"] for m in model.messages_seen[turn_of_holdout] if m["role"] == "user"][-1]
    assert sentence == bfcl.additional_function_prompt
    assert len(line["result"]) == len(entry["question"])


@needs_clone
def test_a_broken_turn_ends_the_task_with_too_few_turns_and_says_why():
    class Broken(Scripted):
        def chat_tools(self, role, messages, tools):
            raise RuntimeError("model down")

    bfcl = bfcl_run.Bfcl(CLONE)
    recording = UsageRecordingRouter(Broken([]))
    entry = bfcl.load_entries("multi_turn_base", ["multi_turn_base_77"])[0]
    line = bfcl_run.run_entry(bfcl, entry, "multi_turn_base", recording, agent_factory(recording), "test-run")
    assert line["result"] == [] and line["error"] == "RuntimeError: model down"


@needs_clone
def test_the_summary_counts_why_turns_ended_and_the_coded_errors(tmp_path):
    bfcl = bfcl_run.Bfcl(CLONE)
    # Four rounds of calls on one turn: the loop allows three, so the turn ends on max_steps.
    rounds: list[Any] = [[("cd", {"folder": "document"})]] * 3 + ["xong"] + [[("no_such_tool", {})], "xong"]
    model = Scripted(rounds + ["xong"] * 10)
    recording = UsageRecordingRouter(model)
    summary = bfcl_run.run_all(
        bfcl, {"multi_turn_base": ["multi_turn_base_77"]}, recording, agent_factory(recording), tmp_path, run_tag="test-run", progress=lambda text: None,
    )
    assert summary["turn_stop_reasons"].get("max_steps", 0) >= 1
    assert summary["per_category"]["multi_turn_base"]["tasks"] == 1
    assert bfcl_run.result_path(tmp_path, "multi_turn_base").is_file()


# ── the scorer, in bfcl-venv ─────────────────────────────────────────────


@needs_clone
@needs_scorer
def test_a_run_that_makes_the_ground_truths_calls_scores_full_marks_through_bfcls_own_checker(tmp_path):
    bfcl = bfcl_run.Bfcl(CLONE)
    plan = {
        "simple_python": ["simple_python_6"],
        "irrelevance": ["irrelevance_0"],
        "multi_turn_base": ["multi_turn_base_77", "multi_turn_base_113"],
    }
    rounds: list[Any] = []
    for category, ids in plan.items():
        for entry_id in ids:
            if category == "multi_turn_base":
                rounds += oracle_multi_turn(entry_id)
            elif category == "irrelevance":
                rounds += ["Không hàm nào dùng được."]
            else:
                rounds += oracle_single_turn(category, entry_id)
    model = Scripted(rounds)
    recording = UsageRecordingRouter(model)
    bfcl_run.run_all(bfcl, plan, recording, agent_factory(recording), tmp_path, run_tag="e2e-run", progress=lambda text: None)

    done = subprocess.run([str(BFCL_PYTHON), "-X", "utf8", str(SCORER), str(tmp_path)], capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    scores = json.loads((tmp_path / "scores.json").read_text(encoding="utf-8"))
    assert {category: (s["correct"], s["total"]) for category, s in scores.items()} == {
        "simple_python": (1, 1), "irrelevance": (1, 1), "multi_turn_base": (2, 2),
    }, scores


@needs_clone
@needs_scorer
def test_a_run_that_does_nothing_fails_a_multi_turn_task_and_an_irrelevance_task_that_calls(tmp_path):
    bfcl = bfcl_run.Bfcl(CLONE)
    plan = {"multi_turn_base": ["multi_turn_base_77"], "irrelevance": ["irrelevance_0"]}
    # Only answers: the state never changes, and one irrelevance task calls a tool it should not.
    rounds: list[Any] = ["xong"] * len(bfcl.load_entries("multi_turn_base", plan["multi_turn_base"])[0]["question"])
    entry = bfcl.load_entries("irrelevance", ["irrelevance_0"])[0]
    rounds += [[(entry["function"][0]["name"].replace(".", "_"), {})], "xong"]
    model = Scripted(rounds)
    recording = UsageRecordingRouter(model)
    bfcl_run.run_all(bfcl, plan, recording, agent_factory(recording), tmp_path, run_tag="e2e-fail", progress=lambda text: None)
    done = subprocess.run([str(BFCL_PYTHON), "-X", "utf8", str(SCORER), str(tmp_path)], capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    scores = json.loads((tmp_path / "scores.json").read_text(encoding="utf-8"))
    assert scores["multi_turn_base"]["correct"] == 0 and scores["irrelevance"]["correct"] == 0, scores
