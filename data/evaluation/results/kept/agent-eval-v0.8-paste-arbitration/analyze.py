"""Ticket 20's arbitration round: a paste read whole (N1) against seven tool rounds (C7), by PREREGISTRATION.md.

    python analyze.py   # writes analysis.json beside this file

Committed with the preregistration, before the first run. Every run unloads the model before
each task. N1 has a second run on the middle tasks only; there a task passes on N1 only if
both runs pass it (the worse run, read against the proposal as before).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
KEPT = HERE.parent
RUNS = {
    "base": HERE / "v0.8-arb-base",
    "n1": HERE / "v0.8-arb-n1",
    "c7": HERE / "v0.8-arb-c7",
    "n1_r2": HERE / "v0.8-arb-n1-r2",
}
OLD_BASE = KEPT / "agent-eval-v0.7-paste-nudge-search" / "v0.7-3d-iso-base-r1"
OLD = tuple(f"doc-{n}" for n in range(39, 54))
NEW_MIDDLE = ("doc-54", "doc-55", "doc-56")  # NV3's blind tasks at 0adc697: answers at 40–60 % and in chunk >= 10
LONG = ("doc-57",)  # 45 166 characters, over N1's ceiling; answer in chunk 13 at 38 %, outside the middle on purpose
NEW = NEW_MIDDLE + LONG
PASTE_TASKS = OLD + NEW
OLD_MIDDLE = ("doc-39", "doc-40", "doc-41", "doc-44", "doc-46", "doc-50")
MIDDLE = OLD_MIDDLE + NEW_MIDDLE
# The figure each decoy task plants away from its answer (doc-53: 300.000 per four hours of
# delayed baggage, in chunk 8; doc-56: 30 days and 150.000 a pause for a work trip, in chunk 4).
DECOYS = {
    "doc-53": r"(?<![\d.,])300[.,\s]?000|(?<![\d.,])300\s*(?:nghìn|ngàn|k\b)",
    "doc-56": r"(?<![\d.,])150[.,\s]?000|(?<![\d.,])150\s*(?:nghìn|ngàn|k\b)|(?<![\d.,])30\s*ngày",
}
HASHES = ("tools_sha256", "agent_guide_sha256", "system_prompt_sha256")
TOOLS_SHA = ("153209", "a75e500")
DATASET_VERSION = "agent-eval-v0.8"
NEAR_WINDOW = 14_500  # a round this full may have had its front cut by Ollama: the task is read apart
DOC50_TOKENS = 10_900  # c-noi-tran-doc.md's estimate of N1's first round on doc-50
DOC50_TOLERANCE = 0.15
INLINED_MIN_GAIN = 1_000  # N1's first round carries the paste: at least this many tokens over base's
FIXED_TOKENS = 1_253  # pastes.INLINE_FIXED_TOKENS at 32a2d50: round 1 of stat-01, the guide and tools without a message


def load(run: Path) -> dict:
    rows = {r["task_id"]: r for r in map(json.loads, (run / "task_results.jsonl").read_text(encoding="utf-8").splitlines())}
    events: dict[str, list] = {}
    for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        events.setdefault(event["task_id"], []).append(event)
    return {"manifest": json.loads((run / "manifest.json").read_text(encoding="utf-8")), "rows": rows, "events": events}


def tasks_file(manifest: dict) -> dict[str, dict]:
    path = Path(manifest["dataset"]["path"]) / "tasks.jsonl"
    return {t["id"]: t for t in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def in_middle(task: dict) -> bool:
    """Every answer pattern's first match lies at 40–60 % of the input, rounded to two places."""
    text = task["input"]
    firsts = [re.search(p, text) for p in task["expect"].get("must_mention", [])]
    return bool(firsts) and all(m is not None and 0.40 <= round(m.start() / len(text), 2) <= 0.60 for m in firsts)


def task(run: dict, task_id: str) -> dict:
    row, steps = run["rows"][task_id], run["events"].get(task_id, [])
    rounds = sorted((s for s in steps if s["kind"] == "model_round"), key=lambda s: s["round_index"])
    final = next((s for s in reversed(steps) if s["kind"] == "final"), {})
    checks = (row.get("grade") or {}).get("checks") or []
    answer = row["answer"] or ""
    decoy = DECOYS.get(task_id)
    return {
        "passed": row["passed"],
        "failed_checks": [c.get("check") for c in checks if not c.get("passed", True)],
        "tools": [(s.get("tool_name"), json.dumps(s.get("arguments"), ensure_ascii=False, sort_keys=True)) for s in steps if s["kind"] == "tool_call"],
        "paste_reads": [s["arguments"] for s in steps if s["kind"] == "tool_call" and s.get("tool_name") == "read_document"
                        and str((s.get("arguments") or {}).get("document_id") or "").startswith("paste_")],
        "round_tokens_in": [r.get("tokens_in") for r in rounds],
        "first_round_tokens_in": rounds[0].get("tokens_in") if rounds else None,
        "max_round_tokens_in": max((r.get("tokens_in") or 0) for r in rounds) if rounds else 0,
        "near_window": any((r.get("tokens_in") or 0) > NEAR_WINDOW for r in rounds),
        "answer_check_fired": sum(s["kind"] == "answer_check" for s in steps),
        "tool_call_error": any(s["kind"] == "tool_call_error" for s in steps),
        "decoy_in_answer": bool(decoy and re.search(decoy, answer)),
        "stop_reason": final.get("stop_reason"),
        "latency_ms": row["latency_ms"],
        "error": row["error"],
        "answer": answer,
    }


def main() -> None:
    runs = {arm: load(path) for arm, path in RUNS.items()}
    per = {arm: {t: task(run, t) for t in run["rows"]} for arm, run in runs.items()}
    old_base = load(OLD_BASE)
    manifests = [run["manifest"] for run in runs.values()]
    defs = tasks_file(runs["base"]["manifest"])
    old_defs = tasks_file(old_base["manifest"]) if Path(old_base["manifest"]["dataset"]["path"]).exists() else None

    preconditions = {
        **{h: len({m[h] for m in manifests}) == 1 for h in HASHES},
        "tools_sha256_as_registered": manifests[0]["tools_sha256"].startswith(TOOLS_SHA[0]) and manifests[0]["tools_sha256"].endswith(TOOLS_SHA[1]),
        "dataset_one_sha": len({m["dataset"]["sha256"] for m in manifests}) == 1,
        "dataset_version": {m["dataset"]["version"] for m in manifests} == {DATASET_VERSION},
        "unload_between_tasks": all(m.get("unload_between_tasks") is True for m in manifests),
        "arm_keys": "paste_inline" not in runs["base"]["manifest"] and "paste_extra_rounds" not in runs["base"]["manifest"]
        and all((runs[a]["manifest"].get("paste_inline") or {}).get("max_tokens") == 12_288 and "paste_extra_rounds" not in runs[a]["manifest"] for a in ("n1", "n1_r2"))
        and runs["c7"]["manifest"].get("paste_extra_rounds") == 4 and "paste_inline" not in runs["c7"]["manifest"],
        "tasks_run_full_arms": all(tuple(runs[a]["manifest"]["dataset"]["tasks_run"]) == PASTE_TASKS for a in ("base", "n1", "c7")),
        "tasks_run_n1_r2": tuple(runs["n1_r2"]["manifest"]["dataset"]["tasks_run"]) == MIDDLE,
        "new_tasks_registered": bool(NEW_MIDDLE) and len(LONG) >= 1,
        "middle_set_recomputed": tuple(t for t in PASTE_TASKS if in_middle(defs[t])) == MIDDLE,
        "old_tasks_unchanged": old_defs is not None and all(defs[t] == old_defs[t] for t in OLD),
        "n1_inlined_all_but_long": all(
            (per["n1"][t]["first_round_tokens_in"] or 0) - (per["base"][t]["first_round_tokens_in"] or 0) >= INLINED_MIN_GAIN and not per["n1"][t]["paste_reads"]
            for t in PASTE_TASKS if t not in LONG
        ),
        "n1_long_not_inlined": all(per["n1"][t]["first_round_tokens_in"] == per["base"][t]["first_round_tokens_in"] for t in LONG),
    }

    def counted(t: str) -> bool:
        return not any(per[a][t]["near_window"] for a in ("base", "n1", "c7")) and not (t in MIDDLE and per["n1_r2"][t]["near_window"])

    def n1_pass(t: str) -> bool:
        return per["n1"][t]["passed"] and (t not in MIDDLE or per["n1_r2"][t]["passed"])

    # R1 counts the blind middle tasks only (fable's review of 0adc697); the seen ones are reported beside it.
    lose_middle = [t for t in NEW_MIDDLE if counted(t) and per["c7"][t]["passed"] and not n1_pass(t)]
    lose_old_middle = [t for t in OLD_MIDDLE if counted(t) and per["c7"][t]["passed"] and not n1_pass(t)]
    lose_any = [t for t in PASTE_TASKS if counted(t) and per["c7"][t]["passed"] and not n1_pass(t)]
    regress = [t for t in PASTE_TASKS if counted(t) and per["base"][t]["passed"] and not n1_pass(t)]
    doc50 = per["n1"]["doc-50"]["first_round_tokens_in"] or 0
    r1 = len(lose_middle) >= 2
    r2 = not lose_any and not regress
    rule = {
        "P_preconditions": all(preconditions.values()),
        "R1_lost_in_the_middle": r1,
        "R2_choose_n1_drop_c": r2,
        "R0_no_conclusion": not r1 and not r2,
        "R3_recompute_thresholds": abs(doc50 - DOC50_TOKENS) > DOC50_TOLERANCE * DOC50_TOKENS,
    }

    long_identical = all(per["n1"][t]["answer"] == per["base"][t]["answer"] and per["n1"][t]["tools"] == per["base"][t]["tools"] for t in LONG)
    under_ceiling = [t for t in PASTE_TASKS if per["base"][t]["stop_reason"] != "max_steps"]
    predictions = {
        "p1_base_old_identical_to_v07_r1": all(per["base"][t]["answer"] == task(old_base, t)["answer"] for t in OLD),
        "p2_base_fails_every_new_task": not any(per["base"][t]["passed"] for t in NEW),
        "p3_n1_passes_two_new_middle": sum(n1_pass(t) for t in NEW_MIDDLE) >= 2,
        "p4_c7_passes_doc49_doc50": per["c7"]["doc-49"]["passed"] and per["c7"]["doc-50"]["passed"],
        "p5_n1_answer_check_never_fires_inlined": not any(per["n1"][t]["answer_check_fired"] for t in PASTE_TASKS if t not in LONG),
        "p6_n1_long_identical_to_base": long_identical,
        "p7_no_turn_budget_stop": not any(per[a][t]["stop_reason"] == "turn_budget" for a in ("base", "n1", "c7") for t in PASTE_TASKS),
        "p8_n1_median_latency_below_c7": median(per["n1"][t]["latency_ms"] for t in PASTE_TASKS) < median(per["c7"][t]["latency_ms"] for t in PASTE_TASKS),
        "p9_n1_r1_equals_r2_on_middle": all(per["n1"][t]["answer"] == per["n1_r2"][t]["answer"] for t in MIDDLE),
        "p10_c7_under_ceiling_identical_to_base": all(
            per["c7"][t]["answer"] == per["base"][t]["answer"] and per["c7"][t]["tools"] == per["base"][t]["tools"] for t in under_ceiling
        ),
    }

    def score(arm: str, group) -> int:
        return sum(n1_pass(t) if arm == "n1" else per[arm][t]["passed"] for t in group)

    result = {
        "preconditions": preconditions,
        "hashes": {arm: {h: run["manifest"][h][:12] for h in HASHES} | {"dataset": run["manifest"]["dataset"]["sha256"][:12], "commit": run["manifest"].get("commit")}
                   for arm, run in runs.items()},
        "score": {arm: {"all": score(arm, PASTE_TASKS), "old": score(arm, OLD), "new": score(arm, NEW), "new_middle": score(arm, NEW_MIDDLE),
                        "old_middle": score(arm, OLD_MIDDLE), "long": score(arm, LONG)} for arm in ("base", "n1", "c7")},
        "passed": {arm: sorted(t for t in per[arm] if per[arm][t]["passed"]) for arm in per},
        "n1_counted_passes": sorted(t for t in PASTE_TASKS if n1_pass(t)),
        "lose_middle_c7_pass_n1_fail": lose_middle,
        "lose_old_middle_c7_pass_n1_fail": lose_old_middle,
        "lose_any_c7_pass_n1_fail": lose_any,
        "regress_base_pass_n1_fail": regress,
        "win_n1_pass_c7_fail": [t for t in PASTE_TASKS if counted(t) and n1_pass(t) and not per["c7"][t]["passed"]],
        "not_counted_near_window": [t for t in PASTE_TASKS if not counted(t)],
        "over_window_16384": {arm: sorted(t for t, v in per[arm].items() if v["max_round_tokens_in"] > 16_384) for arm in per},
        # fable's note on 32a2d50: doc-50's text ran 2,79 characters a token in the old reads, not 3,3.
        "n1_chars_per_token_round1": {
            t: round(len(defs[t]["input"]) / ((per["n1"][t]["first_round_tokens_in"] or 0) - FIXED_TOKENS), 2)
            for t in PASTE_TASKS if t not in LONG and (per["n1"][t]["first_round_tokens_in"] or 0) > FIXED_TOKENS
        },
        "doc50_n1_first_round_tokens_in": doc50,
        "first_round_tokens_in": {arm: {t: per[arm][t]["first_round_tokens_in"] for t in per[arm]} for arm in per},
        "max_round_tokens_in": {arm: max(v["max_round_tokens_in"] for v in per[arm].values()) for arm in per},
        "answer_check_fired": {arm: {t: v["answer_check_fired"] for t, v in per[arm].items() if v["answer_check_fired"]} for arm in per},
        "decoy_in_answer": {arm: sorted(t for t, v in per[arm].items() if v["decoy_in_answer"]) for arm in per},
        "tool_call_error": {arm: sorted(t for t, v in per[arm].items() if v["tool_call_error"]) for arm in per},
        "lost_turn_errors": {arm: {t: v["error"][:80] for t, v in per[arm].items() if v["error"]} for arm in per},
        "stop_reasons": {arm: {t: v["stop_reason"] for t, v in per[arm].items()} for arm in per},
        "latency_ms_median": {arm: median(v["latency_ms"] for v in per[arm].values()) for arm in per},
        "reload_ms_median": {arm: median(r["reload_ms"] for r in run["rows"].values() if r.get("reload_ms") is not None) for arm, run in runs.items()},
        "rule": rule,
        "predictions": predictions,
        "tasks": per,
    }
    (HERE / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("tasks", "first_round_tokens_in", "stop_reasons")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
