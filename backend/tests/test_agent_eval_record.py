"""Agent Eval baseline plumbing (ticket 07): the probed registry, recording real
retrieval once, and refusing to replay what was never recorded.

No stack, no GPU: probes are fakes behind the registry's Probes protocol, and
the API is an httpx.MockTransport speaking /models and /rag/search.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.services.injection_defense import InjectionDefense
from scripts import agent_eval
from scripts.agent_eval import build_settings, load_dataset, probe_refusal, resolve_registry, run_eval
from scripts.agent_eval_grader import summarize
from scripts.agent_eval_record_retrieval import record


class FakeProbes:
    """Only `tags` decides the general role; everything else answers 'could not tell'."""

    def __init__(self, tags):
        self.tags = tags

    def ollama_tags(self):
        return self.tags

    def ollama_embed_dimension(self, model):
        return None

    def ollama_ocr_stops(self, model, prompt):
        return None

    def qdrant_dimension(self, collection):
        return None

    def qdrant_point_count(self, collection):
        return 0

    def postgres_counts(self):
        return None


def test_a_probed_run_is_verified_and_refuses_a_general_model_that_is_not_served():
    settings = build_settings(None, probe=False)

    served = resolve_registry(settings, FakeProbes({"qwen3.5:9b": "sha256:d"})).roles["general"]
    assert served.verified is True and probe_refusal(served, probed=True) is None

    missing = resolve_registry(settings, FakeProbes({})).roles["general"]
    assert probe_refusal(missing, probed=True).startswith("general missing")

    silent = resolve_registry(settings, FakeProbes(None)).roles["general"]
    assert probe_refusal(silent, probed=True).startswith("general unverified"), "Ollama silent: nothing was verified"

    # The 06 smoke mode: pointer only, never refused, never claims verification.
    pointer = resolve_registry(settings, None).roles["general"]
    assert pointer.verified is False and probe_refusal(pointer, probed=False) is None


def test_main_refuses_before_any_model_call_when_the_probe_finds_no_general_model(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql+psycopg://u@localhost/real\n", encoding="utf-8")
    monkeypatch.setattr("app.config.model_registry.ProductionProbes", lambda settings: FakeProbes({}))

    def no_model(*args, **kwargs):
        raise AssertionError("a refused run must not reach the model")

    monkeypatch.setattr(agent_eval, "run_eval", no_model)

    assert agent_eval.main(["--probe", "--env-file", str(env), "--out", str(tmp_path / "runs")]) == 2
    assert "refusing to run: general missing" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()


def test_settings_read_the_env_file_a_worktree_points_at(tmp_path, monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text("OLLAMA_BASE_URL=http://ollama.example:11434\n", encoding="utf-8")
    assert build_settings(env, probe=False).ollama_base_url == "http://ollama.example:11434"


# ── recording ────────────────────────────────────────────────────────────


TASKS = [
    {"id": "doc-r1", "category": "documents", "input": "Backup chạy mấy giờ?", "expect": {"must_mention": [r"\b2\s*(h|giờ)"]}},
    {"id": "doc-r2", "category": "documents", "input": "Giữ bao nhiêu bản?", "expect": {"must_mention": [r"\b7 bản"]}},
    {"id": "doc-h1", "category": "documents", "input": "Phép năm?", "expect": {"must_mention": ["12"]}},
]
FIXTURES = [
    {"task_id": "doc-r1", "source": "pending", "query": "giờ chạy backup tự động", "chunks": []},
    {"task_id": "doc-r2", "source": "pending", "query": "số bản backup được giữ lại", "chunks": []},
    {"task_id": "doc-h1", "source": "handwritten", "query": "phép năm", "chunks": [{"filename": "q.pdf", "page": 3, "content": "12 ngày", "score": 0.9}]},
]


def write_dataset(directory: Path, fixtures=FIXTURES) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    meta = {"version": "t", "guild": {"guild_id": "1", "now": "2026-10-20T12:00:00+07:00", "messages": []}, "status_snapshots": {"healthy": {}}}
    (directory / "dataset.json").write_text(json.dumps(meta), encoding="utf-8")
    (directory / "tasks.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in TASKS), encoding="utf-8")
    (directory / "retrieval.jsonl").write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in fixtures), encoding="utf-8")
    return directory


def source(content: str, chunk_id: str, score: float) -> dict:
    # The /rag/search RagSource shape, trimmed to what a recorder sees.
    return {
        "document_id": "doc-1", "filename": "backup_restore.md", "chunk_id": chunk_id, "chunk_index": 2, "index_version": 1,
        "page": None, "heading_path": "Backup > Lịch", "score": score, "excerpt": content[:300], "content": content,
        "extraction_method": "markdown",
    }


def fake_api(answers: dict[str, list[dict]], fail_on: str | None = None):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/models":
            return httpx.Response(200, json={"models": {"embedding": {"name": "qwen3-embedding:0.6b"}, "general": {"name": "qwen3.5:9b"}}, "registry": {}, "rag": {"reranker": True, "retrieval_mode": "hybrid", "contextual_retrieval": True}})
        body = json.loads(request.content)
        seen.append(body)
        if body["message"] == fail_on:
            return httpx.Response(503, json={"detail": {"error_code": "QDRANT_UNAVAILABLE"}})
        return httpx.Response(200, json={"latency_ms": 42, "sources": answers[body["message"]]})

    return httpx.Client(base_url="http://lab.test", transport=httpx.MockTransport(handler)), seen


def test_recording_fills_only_pending_fixtures_with_what_the_api_served(tmp_path):
    dataset = write_dataset(tmp_path / "ds")
    client, seen = fake_api({
        "giờ chạy backup tự động": [source("Backup tự động chạy lúc 2 giờ sáng mỗi ngày.", "c1", 0.93)],
        "số bản backup được giữ lại": [source("Lịch backup hằng tuần.", "c2", 0.51)],
    })

    manifest = record(dataset, client, max_context_chunks=5, commit="abc", progress=lambda line: None)

    assert [body["top_k"] for body in seen] == [8, 8], "asks for the agent's maximum; the API clips to max_context_chunks"
    fixtures = {f["task_id"]: f for f in map(json.loads, (dataset / "retrieval.jsonl").read_text(encoding="utf-8").splitlines())}
    assert fixtures["doc-r1"]["source"] == "recorded"
    assert fixtures["doc-r1"]["chunks"] == [{
        "filename": "backup_restore.md", "page": None, "content": "Backup tự động chạy lúc 2 giờ sáng mỗi ngày.", "score": 0.93,
        "document_id": "doc-1", "chunk_id": "c1", "chunk_index": 2, "index_version": 1, "heading_path": "Backup > Lịch",
    }]
    assert fixtures["doc-h1"] == FIXTURES[2], "hand-written traps are never re-recorded"

    assert manifest["max_context_chunks"] == 5 and manifest["top_k_requested"] == 8
    assert manifest["rag"]["reranker"] is True and manifest["models"]["embedding"]["name"] == "qwen3-embedding:0.6b"
    # The second query's chunks miss the answer: reported, not hidden.
    assert manifest["tasks"]["doc-r1"]["answer_in_chunks"] is True
    assert manifest["tasks"]["doc-r2"]["answer_in_chunks"] is False
    assert json.loads((dataset / "retrieval_manifest.json").read_text(encoding="utf-8")) == manifest
    # The recorded dataset loads and hashes like any other.
    assert load_dataset(dataset).retrieval["doc-r1"]["source"] == "recorded"


def test_a_failed_query_writes_nothing(tmp_path):
    dataset = write_dataset(tmp_path / "ds")
    before = (dataset / "retrieval.jsonl").read_bytes()
    client, _ = fake_api({"giờ chạy backup tự động": [source("x", "c1", 0.9)]}, fail_on="số bản backup được giữ lại")

    with pytest.raises(httpx.HTTPStatusError):
        record(dataset, client, progress=lambda line: None)

    assert (dataset / "retrieval.jsonl").read_bytes() == before
    assert not (dataset / "retrieval_manifest.json").exists()


def test_the_runner_refuses_to_replay_a_pending_fixture(tmp_path):
    dataset = load_dataset(write_dataset(tmp_path / "ds"))
    with pytest.raises(ValueError, match="chưa ghi truy xuất cho: doc-r1, doc-r2"):
        run_eval(
            dataset, router=None, out_dir=tmp_path / "run", agent_config={"max_steps": 3, "tool_result_max_chars": 2400},
            defense=InjectionDefense(enabled=False), system_prompt="", run_meta={}, progress=lambda line: None,
        )
    assert not (tmp_path / "run").exists()


def test_summary_splits_document_results_by_retrieval_source():
    def result(task_id, source, passed):
        return {"task_id": task_id, "category": "documents", "passed": passed, "retrieval_source": source, "grade": {"checks": []}}

    summary = summarize([result("a", "recorded", True), result("b", "recorded", False), result("c", "handwritten", True), result("d", None, True)])
    assert summary["by_retrieval_source"] == {
        "handwritten": {"passed": 1, "total": 1, "rate": 1.0},
        "recorded": {"passed": 1, "total": 2, "rate": 0.5},
    }
