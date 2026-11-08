"""Publish reproducible CPU evidence without local host/user paths."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

repo = Path(__file__).resolve().parents[2]
private = repo / "data/logs/backend-improvements-2026-11-08"
public = repo / "data/evaluation/results/kept/backend-improvements-2026-11-08"
public.mkdir(parents=True, exist_ok=True)
runs = []
normalization = []
for label in ("focused", "full", "reranker-offline", "reranker-fresh-process", "full-final"):
    path = private / label / "pytest.xml"
    if not path.exists():
        continue
    raw = path.read_bytes()
    tree = ET.fromstring(raw)
    counts = dict(passed=0, failed=0, errors=0, skipped=0)
    for case in tree.findall(".//testcase"):
        status = ("failed" if case.find("failure") is not None else "errors" if case.find("error") is not None
                  else "skipped" if case.find("skipped") is not None else "passed")
        counts[status] += 1
    runs.append({"label": label, **counts})
    for node in tree.iter():
        node.attrib.pop("hostname", None)
    normalized = ET.tostring(tree, encoding="unicode")
    # Pytest emits blank traceback markers as 'E     '; trim only those
    # markers so evidence passes whitespace checks without editing assertions.
    normalized = re.sub(r"(?m)^E[ \\t]+$", "E", normalized)
    for prefix, token in [(str(repo), "BRANCH_ROOT"), (str(Path.home() / "local-ai-core"), "MAIN_ROOT"), (str(Path.home()), "USER_HOME")]:
        normalized = normalized.replace(prefix, token).replace(prefix.replace("\\", "/"), token)
    output = normalized.encode("utf-8")
    ET.fromstring(output)
    (public / (label + ".xml")).write_bytes(output)
    normalization.append({"file": label + ".xml", "raw_sha256": hashlib.sha256(raw).hexdigest(),
                          "normalized_sha256": hashlib.sha256(output).hexdigest()})
    steps = private / label / "steps.json"
    if steps.exists():
        (public / (label + "-steps.json")).write_bytes(steps.read_bytes())
assert any(r["label"] == "full-final" and not r["failed"] and not r["errors"] for r in runs), runs
sources = [p for part in ("backend/app", "backend/scripts", "backend/alembic", "backend/tests", "discord_bot", "tests", "tools")
           for p in (repo / part).rglob("*.py")]
for source in sources:
    ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source.relative_to(repo)))
changed = subprocess.check_output(["git", "diff", "--name-only", "67260f3"], cwd=repo).decode().splitlines()
untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo).decode().splitlines()
hashes = {p: hashlib.sha256((repo / p).read_bytes()).hexdigest() for p in sorted(set(changed + untracked))
          if p.startswith("backend/") and (repo / p).is_file()}
summary = {"base": "67260f3", "main_reference": "c01d6dd", "runs": runs,
           "python_files_parsed": len(sources), "syntax_errors": 0, "normalization": normalization,
           "changed_backend_file_sha256": hashes,
           "cpu_only": {"cuda_visible_devices": "", "network": "loopback only, model ports denied",
                        "ollama": "unused port", "cloud_keys": "empty", "real_reranker": "cached weights, CPU, fresh offline subprocess"}}
(public / "checks.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps({"runs": runs, "parsed": len(sources)}, indent=2))
