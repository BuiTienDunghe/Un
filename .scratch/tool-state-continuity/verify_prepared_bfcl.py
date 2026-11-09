"""Verify all prepared BFCL schemas/commands without Settings, HTTP or generation."""
import argparse
from contextlib import redirect_stdout
import hashlib
import json
from pathlib import Path

import httpx
from scripts import bfcl_run
from scripts.prepare_tool_state_bfcl import code_files, data_files

p = argparse.ArgumentParser()
p.add_argument("--plan", type=Path, required=True)
p.add_argument("--out", type=Path, required=True)
p.add_argument("--scorer-package", type=Path, required=True)
a = p.parse_args()
a.plan, a.out, a.scorer_package = a.plan.resolve(), a.out.resolve(), a.scorer_package.resolve()
plan = json.loads(a.plan.read_text(encoding="utf-8"))
assert plan["inference"] is False and plan["source_files"] == code_files()
bfcl = bfcl_run.Bfcl(bfcl_run.DEFAULT_CLONE)
assert plan["bfcl_data_files"] == data_files(bfcl)
cases, declarations = 0, 0
for group in plan["cohorts"].values():
    for category, ids in group["selection"].items():
        for entry in bfcl.load_entries(category, ids):
            registry = bfcl_run.ToolRegistry()
            docs = [*entry["function"], *(doc for rows in entry.get("missed_function", {}).values() for doc in rows)]
            for order, doc in enumerate(docs):
                registry.register(bfcl_run.make_tool(bfcl, doc, execute=None, state_policy="read"), order)
            cases += 1
            declarations += len(docs)

def forbidden(*args, **kwargs):
    raise AssertionError("verification must not load Settings/.env or contact HTTP")
bfcl_run.build_settings = forbidden
httpx.get = httpx.post = forbidden
a.out.mkdir(parents=True, exist_ok=False)
import os
os.chdir(bfcl_run.BACKEND)
with (a.out / "dry-run.log").open("w", encoding="utf-8") as log, redirect_stdout(log):
    for job in plan["commands"]:
        assert bfcl_run.main(job["argv"][4:] + ["--dry-run"]) == 0

# Compare checker code + relevant data, normalizing checkout line endings only.
clone_package = bfcl.root / "bfcl_eval"
paths = set((clone_package / "eval_checker").rglob("*.py"))
paths.update(bfcl.root / relative for relative in plan["bfcl_data_files"])
paths.update(clone_package / "data/possible_answer" / ("BFCL_v4_" + category + ".json") for category in bfcl_run.MULTI_TURN)
matched = {}
for path in sorted(paths):
    relative = path.relative_to(clone_package)
    installed = a.scorer_package / relative
    expected = path.read_bytes().replace(b"\r\n", b"\n")
    actual = installed.read_bytes().replace(b"\r\n", b"\n")
    assert expected == actual, f"scorer/data mismatch: {relative}"
    matched[str(relative).replace("\\", "/")] = hashlib.sha256(expected).hexdigest()
result = {"inference": False, "settings_loaded": False, "http_attempted": False,
          "prepared_plan_sha256": hashlib.sha256(a.plan.read_bytes()).hexdigest(),
          "validated_cases": cases, "validated_tool_declarations": declarations,
          "dry_run_commands": len(plan["commands"]), "scorer_files_matched": matched}
(a.out / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in result.items() if key != "scorer_files_matched"}))
