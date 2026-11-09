"""Prepare public paired BFCL jobs without constructing or calling a model."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from scripts import bfcl_run
from scripts.tool_state_eval import DEFAULT_CASES, DEFAULT_MODELS, encoded, fingerprint

SPLIT_SEED = "tool-state-confirmation-v2-2026-11-09"
CONFIRMATION_CATEGORIES = tuple(name for name in bfcl_run.MULTI_TURN if name != "multi_turn_base")
CONFIRMATION_PER_CATEGORY = 100
PILOT_PER_CATEGORY = 4


def code_files():
    return {key: value for key, value in fingerprint(DEFAULT_CASES).items() if key != "cases"}


def data_files(bfcl):
    paths = [*bfcl.data.glob("BFCL_v4_multi_turn*.json"), *(bfcl.data / "multi_turn_func_doc").glob("*.json")]
    return {str(path.relative_to(bfcl.root)).replace("\\", "/"): bfcl_run.sha256_of(path) for path in sorted(paths)}


def cohorts(bfcl):
    result = {"pilot": {}, "confirmation": {}, "diagnostic": {}}
    for category in bfcl_run.MULTI_TURN:
        path = bfcl.data / f"BFCL_v4_{category}.json"
        ids = [json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate BFCL IDs")
        if category == "multi_turn_base":
            result["diagnostic"][category] = ids
            continue
        ordered = sorted(ids, key=lambda ident: hashlib.sha256((SPLIT_SEED + ":" + ident).encode()).hexdigest())
        if len(ordered) < CONFIRMATION_PER_CATEGORY + PILOT_PER_CATEGORY:
            raise ValueError("not enough public cases for the frozen split")
        result["confirmation"][category] = ordered[:CONFIRMATION_PER_CATEGORY]
        result["pilot"][category] = ordered[CONFIRMATION_PER_CATEGORY:CONFIRMATION_PER_CATEGORY+PILOT_PER_CATEGORY]
    return result


def validate_prepared(plan, bfcl, args, selection):
    """Run before settings/probes/reload; no silent changes to a registered job."""
    content = {key: value for key, value in plan.items() if key != "plan_hash"}
    if plan.get("plan_hash") != hashlib.sha256(encoded(content).encode()).hexdigest():
        raise ValueError("prepared plan hash is invalid")
    if plan.get("version") != 2 or plan["source_files"] != code_files():
        raise ValueError("prepared source changed; prepare a new plan")
    if plan["bfcl_commit"] != bfcl.commit() or plan["bfcl_data_files"] != data_files(bfcl):
        raise ValueError("prepared BFCL data/clone changed")
    matching = [group for group in plan["cohorts"].values() if group["ids_sha256"] == bfcl_run.sha256_of(args.ids)]
    if len(matching) != 1 or matching[0]["selection"] != selection:
        raise ValueError("selection differs from the frozen cohort")
    if (args.model not in plan["models"] or args.max_steps != 3 or args.carry_tool_traffic or
            not args.measure_inputs or not args.unload_between_tasks or args.lookup_check):
        raise ValueError("options differ from the registered paired comparison")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clone", type=Path, default=bfcl_run.DEFAULT_CLONE)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = parser.parse_args(argv)
    if len(set(args.models)) != len(args.models):
        raise ValueError("models must be unique")
    bfcl = bfcl_run.Bfcl(args.clone)
    commit = bfcl.commit()
    if not commit.startswith(bfcl_run.CLONE_COMMIT):
        raise ValueError("BFCL checkout is not the registered version")
    split = cohorts(bfcl)  # reads IDs, never results or ground truth
    args.out.mkdir(parents=True, exist_ok=False)
    plan = {"version": 2, "inference": False, "split_seed": SPLIT_SEED, "models": args.models,
            "bfcl_commit": commit, "source_files": code_files(), "bfcl_data_files": data_files(bfcl),
            "cohorts": {}, "commands": [],
            "sampling": {"temperature": 0, "seed": 42, "think": False, "context": 16384, "top_p": 0.9},
            "limits": {"max_steps": 3}, "policy": "BFCL explicit observations; production defaults unchanged",
            "timing": "run the pilot only after permission; estimate confirmation from measured pilot, not CPU"}
    for cohort, selection in split.items():
        path = args.out / (cohort + "_ids.json")
        path.write_text(json.dumps(selection, indent=2), encoding="utf-8")
        entries = [entry for category, ids in selection.items() for entry in bfcl.load_entries(category, ids)]
        plan["cohorts"][cohort] = {"selection": selection, "ids_sha256": bfcl_run.sha256_of(path),
            "cases_per_arm": len(entries), "user_turns_per_arm": sum(len(row["question"]) for row in entries)}
        for index, model in enumerate(args.models):
            for enabled in ([False, True] if index % 2 == 0 else [True, False]):
                command = ["python", "-B", "-m", "scripts.bfcl_run",
                    "--clone", str(args.clone.resolve()),
                    "--ids", os.path.relpath(path, bfcl_run.BACKEND),
                    "--prepared-plan", os.path.relpath(args.out / "plan.json", bfcl_run.BACKEND),
                    "--out", os.path.relpath(args.out / "runs", bfcl_run.BACKEND),
                    "--run-id", cohort + "-" + model.replace(":", "-").replace("/", "-") + ("-on" if enabled else "-off"),
                    "--model", model, "--max-steps", "3", "--measure-inputs", "--unload-between-tasks"]
                if enabled:
                    command.append("--bounded-tool-state")
                plan["commands"].append({"cohort": cohort, "model": model, "enabled": enabled, "argv": command})
    plan["plan_hash"] = hashlib.sha256(encoded(plan).encode()).hexdigest()
    (args.out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(encoded({"prepared": True, "inference": False,
        "cases_per_arm": {name: group["cases_per_arm"] for name, group in plan["cohorts"].items()},
        "user_turns_per_arm": {name: group["user_turns_per_arm"] for name, group in plan["cohorts"].items()},
        "plan_hash": plan["plan_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
