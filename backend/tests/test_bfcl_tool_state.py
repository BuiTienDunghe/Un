"""Production state transport on official BFCL backends; fake generation only."""
import copy
import json
import subprocess
from types import SimpleNamespace

import pytest

from app.services.context_budget import calls_have_results
from app.services.input_metrics import measure_input
from scripts import bfcl_run
from scripts import prepare_tool_state_bfcl as prepare
from scripts.eval_state_store import MemoryStore
from tests.test_bfcl_run import (
    BFCL_PYTHON, CLONE, SCORER, Scripted, agent_factory, needs_clone, needs_scorer,
    oracle_multi_turn, run_one,
)


@needs_clone
def test_bounded_path_uses_production_restore_not_legacy_carry(monkeypatch):
    def forbidden(*args):
        pytest.fail("bounded state must not use legacy tool_traffic")
    monkeypatch.setattr(bfcl_run, "tool_traffic", forbidden)
    entry_id = "multi_turn_base_77"
    baseline, off = run_one("multi_turn_base", entry_id, oracle_multi_turn(entry_id))
    bounded, on = run_one("multi_turn_base", entry_id, oracle_multi_turn(entry_id), bounded_tool_state=True)
    assert off.messages_seen[0] == on.messages_seen[0]
    assert bounded["result"] == baseline["result"]
    stats = [turn["tool_state"] for turn in bounded["inference_log"]]
    assert stats[0]["groups"] == 0 and any(row["groups"] > 0 for row in stats[1:])
    assert all(row["groups"] <= 8 and row["chars"] <= 8000 for row in stats)
    assert all(calls_have_results(messages) for messages in on.messages_seen)
    assert on.messages_seen[-2] != off.messages_seen[-2]
    assert not bounded.get("error")


@needs_clone
def test_state_budget_is_the_production_budget_and_can_exclude_all_history():
    entry_id = "multi_turn_base_77"
    model = Scripted(oracle_multi_turn(entry_id))
    model.models = {"general": {"context": 1}}
    recording = bfcl_run.UsageRecordingRouter(model)
    bfcl = bfcl_run.Bfcl(CLONE)
    entry = bfcl.load_entries("multi_turn_base", [entry_id])[0]
    line = bfcl_run.run_entry(bfcl, entry, "multi_turn_base", recording, agent_factory(recording),
                              bfcl_run.RUN_TAG, bounded_tool_state=True)
    assert all(turn["tool_state"]["groups"] == 0 for turn in line["inference_log"])
    assert all(calls_have_results(messages) for messages in model.messages_seen)


@needs_clone
def test_inputs_are_measured_per_actual_round_without_content_in_metrics():
    class Measured(Scripted):
        def chat_tools(self, role, messages, tools):
            measure_input("tools", messages, tools)
            return super().chat_tools(role, messages, tools)
    entry_id = "multi_turn_base_77"
    model = Measured(oracle_multi_turn(entry_id))
    recording = bfcl_run.UsageRecordingRouter(model)
    bfcl = bfcl_run.Bfcl(CLONE)
    entry = bfcl.load_entries("multi_turn_base", [entry_id])[0]
    line = bfcl_run.run_entry(bfcl, entry, "multi_turn_base", recording, agent_factory(recording),
                              bfcl_run.RUN_TAG, bounded_tool_state=True, measure_inputs=True)
    rows = [row for turn in line["inference_log"] for row in turn["input_measurements"]]
    assert len(rows) == len(model.messages_seen)
    assert all(set(row) == {"kind", "message_chars", "schema_chars"} for row in rows)
    assert all(row["message_chars"] > 0 and row["schema_chars"] > 0 for row in rows)


@needs_clone
def test_bounded_rejects_single_turn_and_mixed_history_modes():
    with pytest.raises(ValueError, match="multi-turn"):
        run_one("simple_python", "simple_python_6", [], bounded_tool_state=True)
    with pytest.raises(ValueError, match="legacy"):
        run_one("multi_turn_base", "multi_turn_base_77", [], bounded_tool_state=True, carry_tool_traffic=True)
    with pytest.raises(SystemExit):
        bfcl_run.parse_args(["--carry-tool-traffic", "--bounded-tool-state"])


def test_shared_eval_store_is_bounded_idempotent_and_expires():
    clock = SimpleNamespace(now=0)
    store = MemoryStore(clock=lambda: clock.now)
    payload = {"v": 1, "groups": [{"fixture": "not used as a model observation"}]}
    for index in range(10):
        store.save_tool_state("case", index, "actor", payload)
    assert len(store.states) == 8
    store.save_tool_state("case", 9, "actor", payload)
    assert len(store.states) == 8
    payload["groups"][0]["fixture"] = "mutated"
    loaded = store.load_tool_states("case", "actor", message_ids=[9])
    assert loaded[0]["payload"]["groups"][0]["fixture"] != "mutated"
    assert not store.load_tool_states("case", "other", message_ids=[9])
    clock.now = 1801
    assert not store.load_tool_states("case", "actor", message_ids=[9])


class FakeBfcl:
    def load_entries(self, category, ids):
        return [{"id": ident, "question": [[{"role": "user", "content": "fixture"}]]} for ident in ids]


def test_resume_retries_only_error_and_preserves_attempts(tmp_path, monkeypatch):
    seen = []
    def run(*args, **kwargs):
        seen.append(args[1]["id"])
        row = {"id": seen[-1], "result": [["answer"]], "inference_log": []}
        if len(seen) == 1:
            row["error"] = "RuntimeError: unavailable"
        return row
    monkeypatch.setattr(bfcl_run, "run_entry", run)
    options = {"run_tag": "test", "progress": lambda *a: None}
    selection = {"multi_turn_base": ["case_1"]}
    initial = bfcl_run.run_all(FakeBfcl(), selection, None, None, tmp_path, **options)
    assert initial["per_category"]["multi_turn_base"]["errors"] == 1
    resumed = bfcl_run.run_all(FakeBfcl(), selection, None, None, tmp_path, resume=True, **options)
    assert resumed["per_category"]["multi_turn_base"]["errors"] == 0
    bfcl_run.run_all(FakeBfcl(), selection, None, None, tmp_path, resume=True, **options)
    assert seen == ["case_1", "case_1"]
    canonical = bfcl_run.result_path(tmp_path, "multi_turn_base").read_text().splitlines()
    attempts = (tmp_path / "attempts/multi_turn_base.jsonl").read_text().splitlines()
    assert len(canonical) == 1 and len(attempts) == 2
    assert "error" in json.loads(attempts[0]) and "error" not in json.loads(canonical[0])


def test_preflight_all_categories_before_any_write_or_reload(tmp_path):
    old = bfcl_run.result_path(tmp_path, "multi_turn_miss_param")
    old.parent.mkdir(parents=True)
    old.write_text('{"id":"old"}\n', encoding="utf-8")
    before = old.read_bytes()
    reloader = SimpleNamespace(reload=lambda: pytest.fail("no model reload allowed"))
    with pytest.raises(FileExistsError):
        bfcl_run.run_all(FakeBfcl(), {"multi_turn_base": ["new"], "multi_turn_miss_param": ["old"]},
                         None, None, tmp_path, run_tag="test", reloader=reloader)
    assert old.read_bytes() == before
    assert not bfcl_run.result_path(tmp_path, "multi_turn_base").exists()


@pytest.mark.parametrize("content", [
    '{"id":"case_1"}\n{"id":',
    '{"id":"case_1"}\n{"id":"case_1"}\n',
    '{"id":"foreign"}\n',
])
def test_resume_preserves_and_refuses_corrupt_or_foreign_results(tmp_path, content):
    path = bfcl_run.result_path(tmp_path, "multi_turn_base")
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        bfcl_run.run_all(FakeBfcl(), {"multi_turn_base": ["case_1"]}, None, None,
                         tmp_path, run_tag="test", resume=True)
    assert path.read_bytes() == before


def test_frozen_split_is_disjoint_deterministic_and_excludes_used_base(tmp_path):
    for category in bfcl_run.MULTI_TURN:
        (tmp_path / f"BFCL_v4_{category}.json").write_text("\n".join(
            json.dumps({"id": category + "_" + str(i)}) for i in range(200)), encoding="utf-8")
    fake = SimpleNamespace(data=tmp_path)
    first = prepare.cohorts(fake)
    assert first == prepare.cohorts(fake)
    assert set(first["confirmation"]) == set(prepare.CONFIRMATION_CATEGORIES)
    assert sum(map(len, first["confirmation"].values())) == 300
    assert sum(map(len, first["pilot"].values())) == 12
    for category in first["confirmation"]:
        assert not set(first["confirmation"][category]) & set(first["pilot"][category])
    assert set(first["diagnostic"]) == {"multi_turn_base"}


def test_prepare_and_frozen_cli_dry_run_never_build_settings_or_call_http(tmp_path, monkeypatch):
    import httpx
    source = tmp_path / "source"
    source.mkdir()
    (source / "multi_turn_func_doc").mkdir()
    for category in bfcl_run.MULTI_TURN:
        (source / f"BFCL_v4_{category}.json").write_text("\n".join(
            json.dumps({"id": category + "_" + str(i)}) for i in range(200)), encoding="utf-8")
    fake = SimpleNamespace(data=source, root=source, commit=lambda: "6ea5797test")
    fake.load_entries = lambda category, ids: [{"id": ident, "question": [[{"role": "user", "content": "fixture"}]],
                                               "function": []} for ident in ids]
    monkeypatch.setattr(bfcl_run, "Bfcl", lambda path: fake)
    monkeypatch.setattr(bfcl_run, "build_settings", lambda *a, **k: pytest.fail("prepare/dry run must not load settings/.env"))
    monkeypatch.setattr(httpx, "get", lambda *a, **k: pytest.fail("prepare must not contact model"))
    out = tmp_path / "prepared"
    assert prepare.main(["--clone", str(source), "--out", str(out)]) == 0
    plan_path = out / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["inference"] is False and len(plan["commands"]) == 18
    assert set(plan["models"]) == {"qwen3.5:9b", "lfm3:1.7b", "qwen3.5:2b"}
    monkeypatch.chdir(bfcl_run.BACKEND)
    for command in plan["commands"]:
        assert bfcl_run.main(command["argv"][4:] + ["--dry-run"]) == 0
    command = plan["commands"][0]["argv"][4:]
    parsed = bfcl_run.parse_args(command)
    run_dir = parsed.out / parsed.run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        bfcl_run.main(command)
    with pytest.raises(ValueError, match="source/selection"):
        bfcl_run.main(command + ["--resume"])
    before = plan_path.read_bytes()
    with pytest.raises(FileExistsError):
        prepare.main(["--clone", str(source), "--out", str(out)])
    assert plan_path.read_bytes() == before
    plan["limits"]["max_steps"] = 4
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        bfcl_run.main(plan["commands"][0]["argv"][4:] + ["--dry-run"])


@pytest.mark.parametrize("field", ["ollama_version", "source_files", "general_config", "prepared_plan_sha256"])
def test_resume_contract_pins_runtime_and_frozen_inputs(field):
    initial = {"runner": bfcl_run.RUNNER_VERSION, field: "old"}
    changed = {**initial, field: "new"}
    assert bfcl_run.resume_contract(initial) != bfcl_run.resume_contract(changed)


@needs_clone
@needs_scorer
def test_bounded_oracle_and_noop_are_scored_by_official_checker(tmp_path):
    bfcl = bfcl_run.Bfcl(CLONE)
    entry_id = "multi_turn_base_77"
    count = len(bfcl.load_entries("multi_turn_base", [entry_id])[0]["question"])
    for label, rounds, expected in [("oracle", oracle_multi_turn(entry_id), 1), ("noop", ["xong"]*count, 0)]:
        directory = tmp_path / label
        model = Scripted(rounds)
        recording = bfcl_run.UsageRecordingRouter(model)
        bfcl_run.run_all(bfcl, {"multi_turn_base": [entry_id]}, recording, agent_factory(recording),
                         directory, run_tag=bfcl_run.RUN_TAG, bounded_tool_state=True, progress=lambda *a: None)
        result = subprocess.run([str(BFCL_PYTHON), "-X", "utf8", str(SCORER), str(directory)],
                                capture_output=True, text=True, encoding="utf-8", timeout=600)
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
        score = json.loads((directory / "scores.json").read_text(encoding="utf-8"))["multi_turn_base"]
        assert (score["correct"], score["total"]) == (expected, 1)
