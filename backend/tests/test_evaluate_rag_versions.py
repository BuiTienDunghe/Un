"""evaluate_rag and the model registry (design §4 "Report writers", invariant #4).

The harness reads /models once and (a) stamps the loaded version ids and the
retrieval flags into every multidoc report and baseline, (b) refuses to record a
baseline while any role serves a fallback, and (c) gates a stamped baseline on the
server's POINTER per role. The server is an httpx.MockTransport: no app, no
database — these are contracts about JSON in and JSON out.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from scripts.evaluate_rag import run_multidoc_mode, served_versions, version_gate

CASES = [{"id": "q1", "group": "single", "question": "needle?", "expected_docs": ["a.txt"], "expected_source_terms": ["needle"]}]
MAPPING = {"a.txt": "doc-a"}
SOURCES = [{"document_id": "doc-a", "content": "the needle is here", "excerpt": "the needle"}]


def row(requested: str, loaded: str | None = None, *, status: str = "active", fallback: bool = False, source: str = "registry") -> dict:
    return {"active": requested, "requested": requested, "loaded": requested if loaded is None else loaded,
            "source": source, "status": status, "reason": None, "verified": True, "name": requested, "digest": None, "fallback": fallback}


def shipped_registry() -> dict:
    return {
        "general": row("general-v0"), "condenser": row("condenser-v0", None, status="off"), "embedding": row("embedding-v0"),
        "vision": {**row("vision-v0", None, status="unconfigured"), "active": None, "requested": None, "loaded": None},
        "ocr": row("ocr-v0"), "reranker": row("reranker-v0"), "extractor": row("extractor-v0", None, status="off"), "verifier": row("verifier-v0", None, status="off"),
    }


def fallback_registry() -> dict:
    registry = shipped_registry()
    registry["reranker"] = {**row("reranker-d2-v1", "reranker-v0", status="fallback", fallback=True), "reason": "reranker-d2-v1 load: no weights; serving reranker-v0"}
    return registry


def server(registry: dict | None, rag: dict | None = None) -> httpx.Client:
    """A fake API: /models with the given registry view, /rag/search always finding the needle."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/models":
            body = {"models": {"embedding": {"name": "qwen3-embedding:0.6b"}}, "tokenizer_version": "pyvi-0.1.1"}
            if registry is not None:
                body["registry"] = registry
                body["rag"] = rag if rag is not None else {"contextual_retrieval": True, "reranker": True, "retrieval_mode": "hybrid"}
            return httpx.Response(200, json=body)
        if request.url.path == "/rag/search":
            return httpx.Response(200, json={"sources": SOURCES, "latency_ms": 5})
        return httpx.Response(404, json={"detail": request.url.path})
    return httpx.Client(transport=httpx.MockTransport(handler))


def run(client: httpx.Client, out: Path, *, baseline: Path | None = None, write: Path | None = None) -> int:
    return run_multidoc_mode(client, "http://eval", CASES, MAPPING, True, out, baseline, 0.02, write)


def saved_report(out: Path) -> dict:
    (path,) = out.glob("rag-multidoc-*.json")
    return json.loads(path.read_text(encoding="utf-8"))


# ── stamps ─────────────────────────────────────────────────────────────────────

def test_report_and_baseline_carry_the_loaded_versions_and_the_flags(tmp_path):
    out, baseline = tmp_path / "out", tmp_path / "baseline.json"
    with server(shipped_registry()) as client:
        assert run(client, out, write=baseline) == 0
    expected = {"general": "general-v0", "embedding": "embedding-v0", "reranker": "reranker-v0"}
    assert saved_report(out)["versions"] == expected
    assert saved_report(out)["flags"] == {"contextual_retrieval": True, "reranker": True}
    recorded = json.loads(baseline.read_text(encoding="utf-8"))
    assert recorded["versions"] == expected and recorded["flags"] == {"contextual_retrieval": True, "reranker": True}
    # The pre-registry stamps stay, so an old reader keeps working.
    assert recorded["embedding_model"] == "qwen3-embedding:0.6b" and recorded["tokenizer_version"] == "pyvi-0.1.1"
    assert recorded["per_case"] == {"q1": 1.0}


def test_served_versions_reads_loaded_not_requested():
    assert served_versions(fallback_registry()) == {"general": "general-v0", "embedding": "embedding-v0", "reranker": "reranker-v0"}
    assert served_versions({}) == {"general": None, "embedding": None, "reranker": None}


# ── --write-baseline refusals ──────────────────────────────────────────────────

def test_write_baseline_refuses_while_any_role_serves_a_fallback(tmp_path, capsys):
    out, baseline = tmp_path / "out", tmp_path / "baseline.json"
    with server(fallback_registry()) as client:
        assert run(client, out, write=baseline) == 1
    assert not baseline.exists(), "a fallback's number must never become the baseline"
    assert "reranker" in capsys.readouterr().out
    # The per-run report is still saved — it is the measurement of a deviating state, labelled as such.
    assert saved_report(out)["versions"]["reranker"] == "reranker-v0"


def test_write_baseline_refuses_a_server_without_a_registry(tmp_path):
    out, baseline = tmp_path / "out", tmp_path / "baseline.json"
    with server(None) as client:
        assert run(client, out, write=baseline) == 1
    assert not baseline.exists()


# ── the gate ───────────────────────────────────────────────────────────────────

def test_gate_compares_embedding_always_and_the_others_only_when_the_baseline_used_them():
    recorded = {"versions": {"general": "general-v0", "embedding": "embedding-v0", "reranker": "reranker-v0"},
                "flags": {"contextual_retrieval": False, "reranker": False}}
    moved = shipped_registry()
    moved["reranker"] = row("reranker-d2-v1")
    moved["general"] = row("general-v1")
    # A bare baseline never measured the reranker or the index annotations: no comparison.
    assert version_gate(recorded, moved, "bare.json") is None
    # The shipped baseline did: each one is a different retrieval stack.
    shipped = {**recorded, "flags": {"contextual_retrieval": True, "reranker": True}}
    assert version_gate(shipped, moved, "b.json") == "Baseline reranker version reranker-v0 != current reranker-d2-v1; re-record the baseline on the final configuration."
    only_general = {**recorded, "flags": {"contextual_retrieval": True, "reranker": False}}
    assert version_gate(only_general, moved, "b.json") == "Baseline general version general-v0 != current general-v1; re-record the baseline on the final configuration."
    # Embedding is compared whatever the flags say.
    swapped = shipped_registry()
    swapped["embedding"] = row("embedding-e5l-v1")
    assert version_gate(recorded, swapped, "bare.json") == "Baseline embedding version embedding-v0 != current embedding-e5l-v1; re-record the baseline on the final configuration."


def test_gate_reads_the_pointer_not_what_serves():
    """A fallback is the nightly's business (exit 94); the gate asks whether the POINTER moved."""
    recorded = {"versions": {"general": "general-v0", "embedding": "embedding-v0", "reranker": "reranker-d2-v1"},
                "flags": {"contextual_retrieval": True, "reranker": True}}
    assert version_gate(recorded, fallback_registry(), "b.json") is None


def test_gate_treats_a_server_without_a_registry_as_a_mismatch_of_a_stamped_baseline():
    recorded = {"versions": {"embedding": "embedding-v0"}, "flags": {}}
    assert version_gate(recorded, {}, "b.json") == "Baseline embedding version embedding-v0 != current None; re-record the baseline on the final configuration."


def test_unstamped_baseline_warns_and_is_gated_on_the_numbers_only(capsys):
    assert version_gate({"embedding_model": "qwen3-embedding:0.6b"}, shipped_registry(), "old.json") is None
    assert "old.json predates version stamping and is NOT version-guarded" in capsys.readouterr().out


def test_multidoc_gate_fails_on_a_moved_embedding_pointer_and_passes_on_the_same_one(tmp_path):
    out = tmp_path / "out"
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"embedding_model": "qwen3-embedding:0.6b", "tokenizer_version": "pyvi-0.1.1", "cases": 1,
                                    "recall_at_k": 1.0, "mrr": 1.0, "doc_hit_rate": 1.0, "per_case": {"q1": 1.0},
                                    "versions": {"general": "general-v0", "embedding": "embedding-v0", "reranker": "reranker-v0"},
                                    "flags": {"contextual_retrieval": True, "reranker": True}}), encoding="utf-8")
    with server(shipped_registry()) as client:
        assert run(client, out, baseline=baseline) == 0
    moved = shipped_registry()
    moved["embedding"] = row("embedding-e5l-v1")
    with server(moved) as client:
        assert run(client, tmp_path / "out2", baseline=baseline) == 1
