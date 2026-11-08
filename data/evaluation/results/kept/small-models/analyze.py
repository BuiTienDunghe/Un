"""Per-task analysis of the 08/11 small-model run, as the preregistration plans it.

    .venv/Scripts/python.exe -X utf8 data/evaluation/results/kept/small-models/analyze.py

Reads the run folder (gitignored, this machine only), the 07/11 9B runs it reuses, and writes
analysis.json next to this file. Every pass set is the category's task ids minus BFCL's failed ids;
a task whose line carries an `error` is failed by the scorer and is listed separately.
"""
from __future__ import annotations

import json
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
RUN = REPO / "data" / "evaluation" / "results" / "small-models-run"
FULL = REPO / "data" / "evaluation" / "results" / "bfcl-full-run"
NINE_MT159 = HERE / "nine_harness_multi_turn_159_scores.json"
IDS = json.loads((REPO / "data" / "benchmarks" / "bfcl" / "ids_full.json").read_text(encoding="utf-8"))
MODELS = {"9b": "qwen3-5-9b", "lfm3": "lfm3-1-7b", "2b": "qwen3-5-2b"}
CATS = ("simple_python", "irrelevance", "multi_turn_base")


def mcnemar(a: set[str], b: set[str], universe: set[str]) -> dict:
    """Exact two-sided McNemar on the tasks both were run on: only_a passes in a and fails in b."""
    only_a, only_b = len((a - b) & universe), len((b - a) & universe)
    n, k = only_a + only_b, min(only_a, only_b)
    p = 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)
    return {"only_a": only_a, "only_b": only_b, "p": round(p, 4)}


def score_dir(model: str, arm: str, cat: str) -> Path | None:
    if model == "9b" and cat == "simple_python":
        return FULL / arm / "simple_python"
    if model == "9b" and cat == "multi_turn_base":
        return None if arm == "bare" else HERE  # only the 159 harness tasks of 07/11
    return RUN / arm / MODELS[model] / cat


def passes(model: str, arm: str, cat: str) -> tuple[set[str], set[str]] | None:
    """(passed ids, ids the run covers)."""
    folder = score_dir(model, arm, cat)
    if folder is None:
        return None
    path = NINE_MT159 if folder == HERE else folder / "scores.json"
    s = json.loads(path.read_text(encoding="utf-8"))[cat]
    if folder == HERE:
        universe = set(s["ids"])
    else:
        universe = set(IDS[cat])
    assert s["total"] == len(universe), (model, arm, cat, s["total"], len(universe))
    failed = set(s["failed_ids"])
    assert failed <= universe
    return universe - failed, universe


def error_ids(model: str, arm: str, cat: str) -> list[str]:
    folder = score_dir(model, arm, cat)
    if folder is None or folder == HERE:
        return []
    found = []
    for path in (folder / "result").rglob("*_result.json"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and "error" in (row := json.loads(line)):
                found.append(row["id"])
    return found


def agent_eval(model: str) -> dict[str, dict]:
    rows = {}
    for line in (RUN / "ae" / MODELS[model] / "task_results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["task_id"]] = r
    return rows


def main() -> None:
    out: dict = {"scores": {}, "errors": {}, "pairs": [], "agent_eval": {}}
    sets: dict[tuple[str, str, str], tuple[set[str], set[str]]] = {}
    for model in MODELS:
        for arm in ("bare", "harness"):
            for cat in CATS:
                got = passes(model, arm, cat)
                if got is None:
                    continue
                sets[(model, arm, cat)] = got
                p, u = got
                out["scores"][f"{model} {arm} {cat}"] = {"passed": len(p), "total": len(u), "pct": round(100 * len(p) / len(u), 2)}
                if errs := error_ids(model, arm, cat):
                    out["errors"][f"{model} {arm} {cat}"] = errs

    def pair(a: tuple, b: tuple, cat: str) -> None:
        ka, kb = (*a, cat), (*b, cat)
        if ka not in sets or kb not in sets:
            return
        universe = sets[ka][1] & sets[kb][1]
        r = mcnemar(sets[ka][0], sets[kb][0], universe)
        out["pairs"].append({"a": " ".join(a), "b": " ".join(b), "cat": cat, "tasks": len(universe),
                             "a_passed": len(sets[ka][0] & universe), "b_passed": len(sets[kb][0] & universe), **r})

    for cat in CATS:
        for model in MODELS:
            pair((model, "harness"), (model, "bare"), cat)
        for small in ("lfm3", "2b"):
            for arm in ("bare", "harness"):
                pair((small, arm), ("9b", arm), cat)
        for arm in ("bare", "harness"):
            pair(("lfm3", arm), ("2b", arm), cat)

    ae = {m: agent_eval(m) for m in MODELS}
    ids = sorted(ae["9b"])
    assert all(sorted(ae[m]) == ids for m in MODELS)
    for model in MODELS:
        rows = ae[model]
        passed = {t for t in ids if rows[t]["passed"]}
        by_cat: dict[str, list[int]] = {}
        for t in ids:
            c = by_cat.setdefault(rows[t]["category"], [0, 0])
            c[0] += rows[t]["passed"]
            c[1] += 1
        no_tool_calls = [t for t in ids if rows[t]["category"] == "no_tool" and rows[t].get("tool_calls")]
        entry = {"passed": len(passed), "total": len(ids), "by_category": by_cat, "no_tool_with_a_call": no_tool_calls,
                 "errors": [t for t in ids if rows[t].get("error")]}
        if model != "9b":
            nine = {t for t in ids if ae["9b"][t]["passed"]}
            entry["only_this"] = sorted(passed - nine)
            entry["only_9b"] = sorted(nine - passed)
            entry["vs_9b"] = mcnemar(passed, nine, set(ids))
        out["agent_eval"][model] = entry
    lfm, two = ({t for t in ids if ae[m][t]["passed"]} for m in ("lfm3", "2b"))
    out["agent_eval"]["lfm3_vs_2b"] = mcnemar(lfm, two, set(ids))

    # The preregistered "worth trying next" rule, harness arm only.
    nine = {c: out["scores"][f"9b harness {c}"]["pct"] for c in ("simple_python", "irrelevance")}
    out["rule"] = {}
    for small in ("lfm3", "2b"):
        s = out["scores"]
        checks = {
            "simple_python >= 9B - 5": s[f"{small} harness simple_python"]["pct"] >= nine["simple_python"] - 5,
            "irrelevance >= 9B - 5": s[f"{small} harness irrelevance"]["pct"] >= nine["irrelevance"] - 5,
            "agent_eval >= 9B - 6": out["agent_eval"][small]["passed"] >= out["agent_eval"]["9b"]["passed"] - 6,
            "no no_tool task calls a tool": not out["agent_eval"][small]["no_tool_with_a_call"],
        }
        out["rule"][small] = {**checks, "qualifies": all(checks.values())}

    (HERE / "analysis.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in out["scores"].items():
        print(f"{k:40} {v['passed']}/{v['total']} {v['pct']}")
    print("errors", out["errors"])
    for p in out["pairs"]:
        print(f"{p['cat']:16} {p['a']:13} vs {p['b']:13} n={p['tasks']:3} {p['a_passed']:3}-{p['b_passed']:3} "
              f"only_a {p['only_a']:3} only_b {p['only_b']:3} p={p['p']}")
    for m, e in out["agent_eval"].items():
        print("AE", m, json.dumps(e, ensure_ascii=False))
    print("rule", json.dumps(out["rule"]))


if __name__ == "__main__":
    main()
