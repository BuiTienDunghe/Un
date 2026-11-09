"""Runner contracts use fake local clients; never call a model."""
import copy
import json

import pytest

from app.llm_clients.ollama_client import OllamaClient
from scripts import tool_state_eval as runner


class ScriptedClient(OllamaClient):
    def __init__(self, replies):
        self.replies, self.inputs = list(replies), []
    def chat_tools(self, **kwargs):
        self.inputs.append(copy.deepcopy(kwargs["messages"]))
        reply = self.replies.pop(0)
        if isinstance(reply, tuple):
            name, arguments = reply
            return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}],
                    "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}]}
        return {"content": reply, "tool_calls": [], "raw_tool_calls": []}
    def chat(self, **kwargs):
        self.inputs.append(copy.deepcopy(kwargs["messages"]))
        return "fallback"


def write_cases(tmp_path, case=None):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([case or {"id": "new-case", "surface": "web", "turns": [
        {"message": "hi", "expect": {"no_tools": True}}]}]), encoding="utf-8")
    return path


def test_prepare_never_constructs_a_model_client_and_refuses_overwrite(tmp_path, monkeypatch):
    cases, out = write_cases(tmp_path), tmp_path / "run"
    monkeypatch.setattr(runner, "OllamaClient", lambda *a, **kw: pytest.fail("prepare must never construct client"))
    args = ["--cases", str(cases), "--out", str(out)]
    assert runner.main(args) == 0
    manifest = (out / "manifest.json").read_bytes()
    saved = json.loads(manifest)
    assert saved["executed"] is False
    assert {job["model"] for job in saved["plan"]["jobs"]} == set(runner.DEFAULT_MODELS)
    assert {job["enabled"] for job in saved["plan"]["jobs"]} == {False, True}
    with pytest.raises(FileExistsError):
        runner.main(args)
    assert (out / "manifest.json").read_bytes() == manifest
    assert runner.main(args + ["--resume"]) == 0
    cases.write_text(cases.read_text() + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen"):
        runner.main(args + ["--resume"])


@pytest.mark.parametrize("surface", ["web", "discord"])
def test_real_service_smoke_keeps_turn_state_and_reports_actual_input_chars(surface):
    case = {"id": "cpu-smoke", "surface": surface, "documents": [{"id": "doc", "version": "v1", "content": "value 77"}],
            "turns": [{"message": "lookup", "expect": {"required_tools": ["search_documents"]}},
                      {"message": "follow up", "expect": {"no_tools": True}}]}
    outputs = []
    for enabled in [False, True]:
        client = ScriptedClient([("search_documents", {"query": "doc"}), "found", "follow up"])
        result = runner.run_case(case, client, "fake", enabled, 0, 42)
        assert result["pass"] and len(client.inputs) == 3
        assert any(row.get("role") == "tool" for row in client.inputs[-1]) is enabled
        assert result["envelopes"] == int(enabled)
        outputs.append(result["turns"][-1]["calls"][0]["message_chars"])
    assert outputs[1] > outputs[0]  # overhead is measured, not hidden


def test_pending_approval_stays_unexecuted_in_real_loop():
    case = {"id": "cpu-approval", "surface": "web", "approval": True, "expected_actions": 0,
        "turns": [{"message": "request deletion", "expect": {"contains": ["chưa"], "required_tools": ["delete_record"]}},
                  {"message": "status", "expect": {"contains": ["chưa"], "no_tools": True}}]}
    client = ScriptedClient([("delete_record", {"document_id": "doc"}), "chưa duyệt"])
    result = runner.run_case(case, client, "fake", True, 0, 42)
    assert result["pass"] and result["actions"] == []
    assert any('pending' in row.get("content", "") for row in client.inputs[-1] if row.get("role") == "tool")


def test_failed_jobs_are_retried_and_completed_jobs_skipped(tmp_path, monkeypatch):
    import httpx
    cases, out = write_cases(tmp_path), tmp_path / "run"
    options = ["--cases", str(cases), "--models", "fake", "--out", str(out)]
    # One failing branch and one good branch; no actual HTTP or inference.
    monkeypatch.setattr(runner, "jobs", lambda cases, models: iter([
        {"model": "fake", "temperature": 0, "seed": 42, "case_id": "new-case", "enabled": enabled}
        for enabled in [False, True]]))
    class Response:
        def raise_for_status(self):
            return self
        def json(self):
            return {"models": [{"name": "fake", "digest": "fixed"}]}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: Response())
    monkeypatch.setattr(runner, "OllamaClient", lambda *a, **kw: object())
    seen = []
    def result(*args):
        enabled = args[3]
        seen.append(enabled)
        if enabled and seen.count(True) == 1:
            raise RuntimeError("interrupted")
        return {"pass": True, "turns": []}
    monkeypatch.setattr(runner, "run_case", result)
    assert runner.main(options + ["--execute"]) == 1
    assert runner.main(options + ["--execute", "--resume"]) == 0
    assert seen == [False, True, True]
    assert len((out / "results.jsonl").read_text().splitlines()) == 3


def test_grader_does_not_pass_empty_answers_or_reject_allowed_number_formats():
    assert not runner.grade("  ", [], {"no_tools": True})["pass"]
    assert runner.grade("Ngân sách 725.000 đồng", [], {"contains_any": [["725000", "725.000"]]})["pass"]
    assert not runner.grade("Ngân sách 700000 đồng", [], {"contains_any": [["725000", "725.000"]]})["pass"]
