"""Export local CPU evidence without workstation paths or runtime database URLs."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

repo = Path(__file__).resolve().parents[2]
private = repo / "data/logs/tool-state-continuity-2026-11-09"
public = repo / "data/evaluation/results/kept/tool-state-continuity-2026-11-09"
public.mkdir(parents=True, exist_ok=True)
runs = []
for label, filename in [
    ("small-fixes", "focused.xml"), ("state-unit", "pytest.xml"),
    ("focused-v2", "pytest.xml"), ("focused-v3", "pytest.xml"),
    ("focused-v4", "pytest.xml"), ("full-v1", "pytest.xml"),
    ("full-final", "pytest.xml"), ("eval-final", "pytest.xml"),
]:
    path = private / label / filename
    raw = path.read_bytes()
    tree = ET.fromstring(raw)
    suites = list(tree) if tree.tag == "testsuites" else [tree]
    record = {"label": label, "tests": sum(int(row.get("tests", 0)) for row in suites),
        "failures": sum(int(row.get("failures", 0)) for row in suites),
        "errors": sum(int(row.get("errors", 0)) for row in suites),
        "skipped": sum(int(row.get("skipped", 0)) for row in suites),
        "pytest_seconds": sum(float(row.get("time", 0)) for row in suites),
        "raw_sha256": hashlib.sha256(raw).hexdigest()}
    record["passed"] = record["tests"] - record["failures"] - record["errors"] - record["skipped"]
    runs.append(record)
    if label in {"state-unit", "focused-v2", "full-final", "eval-final"}:
        text = re.sub(r"(?m)^E[ \t]+$", "E", raw.decode("utf-8"))
        for prefix, token in [(str(repo), "BRANCH_ROOT"), (str(Path.home() / "local-ai-core"), "MAIN_ROOT"), (str(Path.home()), "USER_HOME")]:
            text = text.replace(prefix, token).replace(prefix.replace("\\", "/"), token)
        normalized = text.encode("utf-8")
        ET.fromstring(normalized)
        (public / (label + ".xml")).write_bytes(normalized)
        record["normalized_sha256"] = hashlib.sha256(normalized).hexdigest()
for label in ["full-final", "eval-final"]:
    result = next(row for row in runs if row["label"] == label)
    assert result["passed"] and not result["failures"] and not result["errors"] and not result["skipped"]
sources = [path for folder in ["backend/app", "backend/scripts", "backend/tests", "backend/alembic", "discord_bot", "tests", "tools"]
           for path in (repo / folder).rglob("*.py")]
for path in sources:
    ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path.relative_to(repo)))
changed = subprocess.check_output(["git", "diff", "--name-only", "3eac7f6"], cwd=repo).decode().splitlines()
untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo).decode().splitlines()
hashes = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in sorted(set(changed + untracked))
          if name.startswith("backend/") and (repo / name).is_file()}
benchmark = json.loads((private / "cpu-overhead.json").read_text(encoding="utf-8"))
(public / "cpu-overhead.json").write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
manifest = json.loads((repo / "data/evaluation/results/tool_state_continuity/prepared-final-20261109/manifest.json").read_text(encoding="utf-8"))
assert manifest["executed"] is False
(public / "prepared-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
(public / "checks.json").write_text(json.dumps({"base": "3eac7f6", "branch": "codex/tool-state-continuity",
    "runs": runs, "python_files_parsed": len(sources), "syntax_errors": 0,
    "changed_backend_sha256": hashes, "generation_models_executed": False,
    "reranker_check": "existing real-reranker test uses cached weights on CPU, offline subprocess",
    "guard": "hidden CUDA; no cloud keys; network loopback only, model ports denied; dead Ollama URL",
    "notes": ["full-v1 had Windows cp1252 reader-thread warnings; final runner sets PYTHONUTF8=1",
              "eval-final verifies final grader/fingerprint changes made during the last full suite",
              "CPU benchmark has scripted calls, not inference or an accuracy score"]}, indent=2), encoding="utf-8")
print(json.dumps({"runs": runs, "parsed": len(sources)}, indent=2))
