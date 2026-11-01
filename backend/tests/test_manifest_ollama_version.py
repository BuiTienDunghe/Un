"""The eval manifests say which Ollama they ran on, and the context-budget switches of agent_eval.

Ollama updates itself, and the same commit scored 58 on 29/10 and 55 on 02/11: two runs compare
only on one version. No Ollama here: httpx.get is replaced, and agent_eval.main stops where
run_eval would start.
"""
from __future__ import annotations

import json

import httpx
import pytest

import scripts.agent_eval as agent_eval
from scripts import bfcl_run
from app.services.context_budget import ContextBudget


class Reply:
    def __init__(self, body):
        self.body = body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


def serve(monkeypatch, routes: dict):
    """httpx.get answers each path from `routes`: a body, or an exception to raise."""
    def get(url, timeout=None):
        for path, body in routes.items():
            if url.endswith(path):
                if isinstance(body, httpx.HTTPError):
                    raise body
                return Reply(body)
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "get", get)


def test_the_version_is_read_off_the_server(monkeypatch):
    serve(monkeypatch, {"/api/version": {"version": "0.34.2"}})
    assert agent_eval.ollama_version("http://127.0.0.1:11434/") == "0.34.2"


@pytest.mark.parametrize("body", [
    httpx.ConnectError("down"), httpx.ReadTimeout("slow"), ValueError("not json"),
    ["version"], {"version": None}, {"version": ""}, {"version": 34}, {},
])
def test_a_server_that_does_not_answer_properly_gives_none_and_never_raises(monkeypatch, body):
    serve(monkeypatch, {"/api/version": body})
    assert agent_eval.ollama_version("http://127.0.0.1:9") is None


def test_the_bfcl_manifest_keeps_the_version_when_the_model_list_fails(monkeypatch):
    serve(monkeypatch, {"/api/tags": httpx.ReadTimeout("slow"), "/api/version": {"version": "0.34.2"}})
    assert bfcl_run.ollama_facts("http://x", "qwen3.5:9b") == {"digest": None, "ollama_version": "0.34.2"}
    serve(monkeypatch, {"/api/tags": {"models": [{"name": "qwen3.5:9b", "digest": "abc"}]}, "/api/version": {"version": "0.34.2"}})
    assert bfcl_run.ollama_facts("http://x", "qwen3.5:9b") == {"digest": "abc", "ollama_version": "0.34.2"}
    serve(monkeypatch, {})
    assert bfcl_run.ollama_facts("http://x", "qwen3.5:9b") == {"digest": None, "ollama_version": None}


def captured_main(tmp_path, monkeypatch, *flags):
    """What agent_eval.main hands run_eval for these flags, from an empty .env of its own."""
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    seen = {}

    class Stop(Exception):
        pass

    def capture(*args, **kwargs):
        seen.update(kwargs)
        raise Stop

    monkeypatch.setattr(agent_eval, "run_eval", capture)
    with pytest.raises(Stop):
        agent_eval.main(["--env-file", str(env), "--out", str(tmp_path / "runs"), *flags])
    return seen


def test_the_agent_eval_manifest_gets_the_ollama_version_without_the_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_eval, "ollama_version", lambda base_url: "0.34.2")
    assert captured_main(tmp_path, monkeypatch)["run_meta"]["ollama_version"] == "0.34.2"
    monkeypatch.setattr(agent_eval, "ollama_version", lambda base_url: None)
    assert captured_main(tmp_path, monkeypatch)["run_meta"]["ollama_version"] is None


def test_the_context_budget_is_off_in_agent_eval_until_asked_for(tmp_path, monkeypatch):
    assert captured_main(tmp_path, monkeypatch)["agent_config"]["context_budget"] is None
    on = captured_main(tmp_path, monkeypatch, "--context-budget")["agent_config"]["context_budget"]
    assert on == ContextBudget(ceiling_tokens=None, keep_recent=2)
    low = captured_main(tmp_path, monkeypatch, "--context-ceiling", "6000")["agent_config"]["context_budget"]
    assert low == ContextBudget(ceiling_tokens=6000, keep_recent=2), "a ceiling alone turns it on"


def test_the_manifest_records_the_budget_the_agents_ran_with(tmp_path):
    from tests.test_agent_eval import DOC_FIXTURE, DOC_TASK, ScriptedRouter, _run, final

    runs = []

    def manifest(**agent_config):
        runs.append(tmp_path / f"arm{len(runs)}")
        out_dir, _ = _run(runs[-1], [DOC_TASK], [DOC_FIXTURE], ScriptedRouter([final("12 ngày.")]), agent_config=agent_config)
        return json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest()["context_budget"] is None
    assert manifest(context_budget=ContextBudget(keep_recent=3), inline_max_tokens=12_288)["context_budget"] == {"ceiling_tokens": 12_288, "keep_recent": 3}
    assert manifest(context_budget=ContextBudget(ceiling_tokens=6000), inline_max_tokens=12_288)["context_budget"] == {"ceiling_tokens": 6000, "keep_recent": 2}
