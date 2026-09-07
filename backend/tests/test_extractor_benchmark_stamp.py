"""benchmark_discord_memory_extractor --version-id: the only writer of the extractor_benchmark
gate stamps the version it measured, so `--check` can accept a promoted extractor.

operator-ux review: the report carried `model` but never `versions.extractor`, and `--check`
turns an unstamped report into an error for any id outside GRANDFATHERED_UNSTAMPED — the
runbook promised a gate no tool could satisfy without hand-editing the JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from app.config.model_registry import DEFAULT_REGISTRY_PATH, check_registry
from scripts import benchmark_discord_memory_extractor as benchmark

BACKEND = Path(__file__).resolve().parents[1]
FIXTURE = BACKEND / "tests" / "fixtures" / "discord_memory_extractor_benchmark_v1.json"
STUDENT_TAG = "local-ai/extractor-student:d2"
STUDENT_ID = "extractor-d2-student-v1"


def run_benchmark(monkeypatch, tmp_path: Path, *extra: str) -> dict:
    """The harness with no model call: --repeat-only skips the cases, --skip-repeatability
    the repeats, and the adapter is a stub that never opens a connection."""
    monkeypatch.setattr(benchmark, "DiscordMemoryExtractorAdapter", lambda **kwargs: object())
    output = tmp_path / "bench.json"
    monkeypatch.setattr(sys, "argv", ["benchmark", "--fixture", str(FIXTURE), "--model", STUDENT_TAG, "--output", str(output),
                                      "--repeat-only", "--skip-repeatability", *extra])
    benchmark.main()
    return json.loads(output.read_text(encoding="utf-8"))


def candidate_active(tmp_path: Path, report: Path) -> Path:
    """The shipped registry with the student promoted and this report as its gate."""
    document = yaml.safe_load(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    extractor = document["roles"]["extractor"]
    extractor["active"] = STUDENT_ID
    candidate = next(record for record in extractor["versions"] if record["id"] == STUDENT_ID)
    candidate["vram_mib"] = 100
    candidate["eval"]["reports"]["extractor_benchmark"] = str(report)
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_version_id_is_stamped_and_check_accepts_the_stamped_report(monkeypatch, tmp_path):
    report = run_benchmark(monkeypatch, tmp_path, "--version-id", STUDENT_ID)
    assert report["model"] == STUDENT_TAG and report["versions"] == {"extractor": STUDENT_ID}
    errors, _ = check_registry(candidate_active(tmp_path, tmp_path / "bench.json"))
    # The Modelfile / gguf rules still fire for the unexported student; the report rules do not.
    assert not any("versions.extractor" in error or "names model" in error for error in errors), errors


def test_an_unstamped_report_cannot_promote_a_candidate(monkeypatch, tmp_path):
    report = run_benchmark(monkeypatch, tmp_path)
    assert report["versions"] == {"extractor": None}
    errors, _ = check_registry(candidate_active(tmp_path, tmp_path / "bench.json"))
    assert any(f"id={STUDENT_ID}" in error and "carries no versions.extractor stamp" in error for error in errors), errors
