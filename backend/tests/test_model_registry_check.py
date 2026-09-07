"""`python -m app.config.model_registry --check`: the static rules CI runs on every commit.

The pytest twin of the CI step: the shipped file must pass, and each rule must
fail on the one document that violates it, naming role and id.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from app.config.model_registry import CI_WORKFLOW_PATH, PROJECT_ROOT, check_registry, load_registry, main

BACKEND = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONUTF8": "1"}


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "app.config.model_registry", *args], cwd=BACKEND, capture_output=True, text=True, env=ENV, check=False)


# ── the shipped file and the workflow ───────────────────────────────────────────

def test_check_on_the_shipped_file_exits_0():
    result = _cli("--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 error(s)" in result.stdout


def test_shipped_file_has_no_errors_and_only_grandfathered_warnings():
    errors, warnings = check_registry()
    assert errors == []
    # v0 reports predate the `versions` stamp: a warning each, never an error.
    assert all("carries no versions." in warning for warning in warnings), warnings
    assert {warning.split(" id=")[1].split(":")[0] for warning in warnings} == {"general-v0", "embedding-v0", "reranker-v0", "extractor-v0"}


def test_ci_ollama_cache_key_equals_the_active_embedding_revision():
    registry = load_registry()
    revision = registry.get("embedding", registry.roles["embedding"].active).config["revision"]
    workflow = yaml.safe_load(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    keys = [step["with"]["key"] for job in workflow["jobs"].values() for step in job.get("steps", [])
            if str(step.get("uses", "")).startswith("actions/cache") and step.get("with", {}).get("path") == "~/.ollama"]
    assert keys == [f"ollama-{revision}"]


def test_pull_list_cli_prints_the_launcher_tags_and_create_list_prints_nothing():
    env = {**ENV, "DATABASE_URL": os.environ.get("DATABASE_URL") or "postgresql+psycopg://x:y@localhost/x"}
    pull = subprocess.run([sys.executable, "-m", "app.config.model_registry", "--ollama-pull-list"], cwd=BACKEND, capture_output=True, text=True, env=env, check=False)
    assert pull.returncode == 0, pull.stderr
    assert pull.stdout.split() == ["qwen3.5:9b", "qwen3-embedding:0.6b", "glm-ocr:latest"]
    create = subprocess.run([sys.executable, "-m", "app.config.model_registry", "--ollama-create-list"], cwd=BACKEND, capture_output=True, text=True, env=env, check=False)
    assert create.returncode == 0 and create.stdout.strip() == ""


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_checkpoint_weights_are_ignored_but_their_contract_files_are_not():
    def ignored(path: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", path], cwd=PROJECT_ROOT, capture_output=True, check=False).returncode == 0

    assert ignored("data/models/reranker/reranker-d2-v1/model.safetensors")
    assert ignored("data/models/extractor/extractor-d2-student-v1/model.gguf")
    assert not ignored("data/models/reranker/reranker-d2-v1/export.json")
    assert not ignored("data/models/extractor/extractor-d2-student-v1/Modelfile")


# ── the rules, one violating document each ──────────────────────────────────────

def _shipped_document() -> dict:
    return yaml.safe_load(Path(load_registry().path).read_text(encoding="utf-8"))


def _write(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _report(tmp_path: Path, name: str, payload: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _errors(tmp_path: Path, document: dict) -> list[str]:
    errors, _warnings = check_registry(_write(tmp_path, document))
    return errors


def test_budget_overrun_and_null_vram_on_the_active_version_are_errors(tmp_path):
    document = _shipped_document()
    document["budget"]["vram_mib"] = 9000
    assert any("need 9920 MiB, budget.vram_mib is 9000" in error for error in _errors(tmp_path, document))
    document = _shipped_document()
    document["roles"]["general"]["versions"][0]["vram_mib"] = None
    assert any("roles.general id=general-v0 (ACTIVE): vram_mib is null" in error for error in _errors(tmp_path, document))


def test_extractor_sharing_generals_tag_costs_no_budget_but_a_different_tag_does(tmp_path):
    document = _shipped_document()
    document["budget"]["vram_mib"] = 9920          # exactly general + embedding + reranker
    assert _errors(tmp_path, document) == []
    document["roles"]["extractor"]["versions"][0]["config"]["name"] = "other:1b"
    document["roles"]["extractor"]["versions"][0]["vram_mib"] = 1
    document["roles"]["extractor"]["versions"][0]["eval"]["reports"]["extractor_benchmark"] = _report(tmp_path, "bench.json", {"model": "other:1b", "versions": {"extractor": "extractor-v0"}})
    assert any("need 9921 MiB" in error for error in _errors(tmp_path, document))


def test_active_gated_version_needs_an_existing_report(tmp_path):
    document = _shipped_document()
    document["roles"]["general"]["versions"][0]["eval"]["reports"]["d1_multidoc"] = None
    assert any("roles.general id=general-v0 (ACTIVE): needs at least one existing eval.reports path" in error for error in _errors(tmp_path, document))
    document = _shipped_document()
    document["roles"]["general"]["versions"][0]["eval"]["reports"]["d1_multidoc"] = "data/evaluation/does_not_exist.json"
    errors = _errors(tmp_path, document)
    assert any("eval.reports.d1_multidoc" in error and "does not exist" in error for error in errors)
    assert any("(ACTIVE): needs at least one existing" in error for error in errors)


def test_report_stamp_must_name_the_version_unless_grandfathered(tmp_path):
    document = _shipped_document()
    versions = document["roles"]["general"]["versions"]
    versions.append({"id": "general-v1", "provider": "ollama", "vram_mib": 6407, "config": versions[0]["config"],
                     "eval": {"reports": {"d1_multidoc": _report(tmp_path, "unstamped.json", {"recall_at_k": 1.0})}}})
    document["roles"]["general"]["active"] = "general-v1"
    assert any("roles.general id=general-v1: eval.reports.d1_multidoc" in error and "carries no versions.general stamp" in error for error in _errors(tmp_path, document))
    versions[-1]["eval"]["reports"]["d1_multidoc"] = _report(tmp_path, "wrong.json", {"versions": {"general": "general-v0"}})
    assert any("was produced by versions.general='general-v0'" in error for error in _errors(tmp_path, document))
    versions[-1]["eval"]["reports"]["d1_multidoc"] = _report(tmp_path, "right.json", {"versions": {"general": "general-v1"}})
    assert _errors(tmp_path, document) == []


def test_benchmark_and_mteb_reports_must_name_the_configured_model(tmp_path):
    document = _shipped_document()
    document["roles"]["extractor"]["versions"][0]["eval"]["reports"]["extractor_benchmark"] = _report(tmp_path, "bench.json", {"model": "qwen3.5:2b"})
    assert any("names model 'qwen3.5:2b', config.name is 'qwen3.5:9b'" in error for error in _errors(tmp_path, document))
    document = _shipped_document()
    document["roles"]["embedding"]["versions"][0]["eval"]["reports"]["mteb"] = _report(tmp_path, "mteb.json", {"model": "qwen3-embedding:0.6b", "versions": {"embedding": "embedding-v0"}})
    assert _errors(tmp_path, document) == []


def test_modelfile_versions_in_a_chain_need_the_file_and_the_gguf_hash(tmp_path):
    document = _shipped_document()
    document["roles"]["extractor"]["active"] = "extractor-d2-student-v1"
    document["roles"]["extractor"]["versions"][1]["vram_mib"] = 100
    document["roles"]["extractor"]["versions"][1]["eval"]["reports"]["extractor_benchmark"] = _report(
        tmp_path, "student.json", {"model": "local-ai/extractor-student:d2", "versions": {"extractor": "extractor-d2-student-v1"}})
    errors = _errors(tmp_path, document)
    assert any("ollama.modelfile" in error and "does not exist" in error for error in errors)
    assert any("ollama.gguf_sha256 is null" in error for error in errors)
    # As a candidate (listed after the active version) the same record is not checked.
    assert not any("extractor-d2-student-v1" in error for error in _errors(tmp_path, _shipped_document()))


def test_active_path_reranker_needs_digest_scores_and_a_matching_export(tmp_path):
    document = _shipped_document()
    document["roles"]["reranker"]["active"] = "reranker-d2-v1"
    candidate = document["roles"]["reranker"]["versions"][1]
    candidate["vram_mib"] = 700
    candidate["eval"]["reports"]["d1_multidoc"] = _report(tmp_path, "d1.json", {"versions": {"reranker": "reranker-d2-v1"}})
    errors = _errors(tmp_path, document)
    assert any("digest.sha256 must be non-null" in error for error in errors)
    assert any("probe.scores must be non-null" in error for error in errors)
    assert any("export.json" in error and "does not exist" in error for error in errors)

    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "export.json").write_text(json.dumps({"activation_fn": "sigmoid", "scores": [1.0], "model_safetensors_sha256": "deadbeef"}), encoding="utf-8")
    candidate["path"] = str(checkpoint)
    candidate["digest"]["sha256"] = "cafebabe"
    candidate["probe"] = {"pairs": [["q", "p"]], "scores": [1.0], "tolerance": 0.05, "max_ms": 500}
    errors = _errors(tmp_path, document)
    assert any("export.json activation_fn 'sigmoid' != activation 'identity'" in error for error in errors)
    assert any("model_safetensors_sha256 != digest.sha256" in error for error in errors)
    (checkpoint / "export.json").write_text(json.dumps({"activation_fn": "identity", "scores": [1.0], "model_safetensors_sha256": "cafebabe"}), encoding="utf-8")
    assert _errors(tmp_path, document) == []


def test_hub_active_reranker_without_scores_only_warns(tmp_path):
    document = _shipped_document()
    document["roles"]["reranker"]["versions"][0]["probe"]["scores"] = None
    errors, warnings = check_registry(_write(tmp_path, document))
    assert errors == [] and any("probe.scores is null" in warning for warning in warnings)


def test_ci_cache_key_mismatch_is_an_error(tmp_path):
    document = _shipped_document()
    workflow = tmp_path / "ci.yml"
    workflow.write_text(yaml.safe_dump({"jobs": {"eval": {"steps": [{"uses": "actions/cache@v4", "with": {"path": "~/.ollama", "key": "ollama-stale"}}]}}}), encoding="utf-8")
    errors, _ = check_registry(_write(tmp_path, document), ci_workflow=workflow)
    assert errors == [f"{workflow}: Ollama cache key 'ollama-stale' != 'ollama-qwen3-embedding-0.6b-r1' (active embedding config.revision)"]


def test_invalid_registry_is_the_single_listed_error(tmp_path):
    document = _shipped_document()
    document["schema_version"] = 2
    errors, warnings = check_registry(_write(tmp_path, document))
    assert len(errors) == 1 and "schema_version must be 1" in errors[0] and warnings == []
    assert main(["--check", "--registry", str(tmp_path / "registry.yaml")]) == 1
