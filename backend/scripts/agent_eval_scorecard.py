"""Agent Eval scorecard (ticket 23): correctness, efficiency, robustness and
traceability of one run, from its artifacts alone.

    cd backend
    python -m scripts.agent_eval_scorecard <run_dir>                    # print, write <run_dir>/scorecard.json
    python -m scripts.agent_eval_scorecard --compare <run_a> <run_b>     # same dataset and grader only
    python -m scripts.agent_eval_scorecard --append-history <run_dir>    # when the run is kept

Reads manifest.json, task_results.jsonl and events.jsonl (when kept). Like the
grader it imports nothing from `app`, so it runs on artifacts older than the
code that wrote them. How every number is computed is written in ticket 23
(Comments, 28/10 00:35); a metric whose fields a run did not record is None
with the reason beside it, never 0.

History lines go to a tracked file only on request: a line must resolve to
artifacts someone can open again (kept/README), and scratch runs are outside
git.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

SCORECARD_VERSION = "agent-eval-scorecard-v1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
KEPT_DIR = PROJECT_ROOT / "data" / "evaluation" / "results" / "kept"
HISTORY_PATH = KEPT_DIR / "agent-eval-scorecard-history.jsonl"
# Cold/warm of the runs kept before the runner recorded it (28/10), copied from
# the GPU logs written while they ran; see the file's own note.
CONDITIONS_PATH = KEPT_DIR / "agent-eval-run-conditions.json"

# Fabricated = the answer stated what a task forbids (must_not_mention): only
# tasks with such a criterion can show it (hist-11 of v0.3 fabricates and has
# none). Not saying "not found" is counted apart: 15 of the 18 kept runs the
# first definition flagged were honest "not found" answers the grader's
# pattern missed (doc-19, doc-12), not claims (review 28/10).
FABRICATION_CHECK = "must_not_mention"
NOT_FOUND_CHECK = "not_found"
STOP_REASONS = ("final", "max_steps", "turn_budget", "turn_budget_exhausted")
_OMITTED = re.compile(r'"omitted":\s*\d+')
_UNCODED_ERROR = re.compile(r'"error":')


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_run(run_dir: Path) -> dict[str, Any]:
    events_path = run_dir / "events.jsonl"
    return {
        "dir": run_dir,
        "manifest": json.loads((run_dir / "manifest.json").read_text(encoding="utf-8")),
        "results": _jsonl(run_dir / "task_results.jsonl"),
        "events": _jsonl(events_path) if events_path.exists() else None,
    }


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _nearest_rank(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1]


def _ran(result: dict[str, Any]) -> bool:
    # 0 model rounds = refused before the agent ran (INPUT_TOO_LONG, as the API would).
    return int(result.get("model_rounds") or 0) > 0


def correctness(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [r for r in results if r["passed"]]
    by_category: dict[str, list[int]] = {}
    for result in results:
        counts = by_category.setdefault(result["category"], [0, 0])
        counts[0] += bool(result["passed"])
        counts[1] += 1
    checks = [(r["task_id"], c) for r in results for c in r["grade"]["checks"]]
    citations = [c for _, c in checks if c["check"] == "citation"]
    fabricated = sorted({task_id for task_id, c in checks if c["check"] == FABRICATION_CHECK and not c["passed"]})
    not_found_missed = sorted({task_id for task_id, c in checks if c["check"] == NOT_FOUND_CHECK and not c["passed"]} - set(fabricated))
    return {
        "passed": len(passed),
        "tasks": len(results),
        "pass_rate": _rate(len(passed), len(results)),
        "by_category": {name: {"passed": p, "tasks": n, "pass_rate": _rate(p, n)} for name, (p, n) in sorted(by_category.items())},
        "fabricated": len(fabricated),
        "fabricated_tasks": fabricated,
        "not_found_missed": len(not_found_missed),
        "not_found_missed_tasks": not_found_missed,
        "citation_passed": sum(c["passed"] for c in citations),
        "citation_tasks": len(citations),
        "citation_rate": _rate(sum(c["passed"] for c in citations), len(citations)),
        "citation_verbatim": sum(bool(c.get("verbatim")) for c in citations),
    }


def efficiency(results: list[dict[str, Any]]) -> dict[str, Any]:
    ran = [r for r in results if _ran(r)]
    tokens_in = [int(r["tokens_in"]) for r in ran if r.get("tokens_in") is not None]
    tokens_out = [int(r["tokens_out"]) for r in ran if r.get("tokens_out") is not None]
    latency = [int(r["latency_ms"]) for r in ran]
    calls = sum(len(r["tool_calls"]) for r in results)
    solved = [r for r in results if r["passed"]]
    return {
        "tasks_ran": len(ran),
        "tokens_in_mean": round(sum(tokens_in) / len(tokens_in)) if tokens_in else None,
        "tokens_in_median": round(median(tokens_in)) if tokens_in else None,
        "tokens_out_mean": round(sum(tokens_out) / len(tokens_out)) if tokens_out else None,
        "tokens_out_median": round(median(tokens_out)) if tokens_out else None,
        "model_rounds_mean": round(sum(int(r["model_rounds"]) for r in ran) / len(ran), 3) if ran else None,
        "tool_calls": calls,
        # The cost of one success: every call, solved or not, over the solved tasks.
        "tool_calls_per_solved": round(calls / len(solved), 3) if solved else None,
        "tool_calls_mean_of_solved": round(sum(len(r["tool_calls"]) for r in solved) / len(solved), 3) if solved else None,
        "latency_p50_ms": _nearest_rank(latency, 0.5),
        "latency_p95_ms": _nearest_rank(latency, 0.95),
        "latency_max_ms": max(latency) if latency else None,
    }


def robustness(results: list[dict[str, Any]], events: list[dict[str, Any]] | None) -> dict[str, Any]:
    errors = Counter(str(r["error"]).split(":", 1)[0] for r in results if r.get("error"))
    base: dict[str, Any] = {
        "task_errors": dict(sorted(errors.items())),
        "budget_exhausted": sum(bool(r.get("budget_exhausted")) for r in results),
    }
    if events is None:
        return {**base, "unavailable": "không có events.jsonl"}
    finals = [e for e in events if e.get("kind") == "final"]
    calls = [e for e in events if e.get("kind") == "tool_call"]
    tool_results = [e for e in events if e.get("kind") == "tool_result"]
    coded = any("error_code" in e for e in tool_results)
    stop = Counter(e.get("stop_reason") for e in finals) if any("stop_reason" in e for e in finals) else None
    codes = Counter(e["error_code"] for e in tool_results if e.get("error_code")) if coded else None
    return {
        **base,
        "stop_reasons": {reason: stop.get(reason, 0) for reason in STOP_REASONS} if stop is not None else None,
        "stop_reasons_unavailable": None if stop is not None else "bước final không có stop_reason (trước ticket 16)",
        # Both count the turns that ran out of tool rounds; a mismatch is a definition error.
        "max_steps_matches_budget_exhausted": (stop.get("max_steps", 0) == base["budget_exhausted"]) if stop is not None else None,
        "tool_error_codes": dict(sorted(codes.items())) if codes is not None else None,
        "tool_errors_uncoded": None if coded else sum(bool(_UNCODED_ERROR.search(str(e.get("content") or ""))) for e in tool_results),
        "bad_arguments_rate": _rate(codes.get("BAD_ARGUMENTS", 0), len(calls)) if codes is not None else None,
        "results_trimmed_by_item": sum(bool(_OMITTED.search(str(e.get("content") or ""))) for e in tool_results),
    }


def traceability(results: list[dict[str, Any]], events: list[dict[str, Any]] | None) -> dict[str, Any]:
    if events is None:
        return {"unavailable": "không có events.jsonl"}
    by_task: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_task.setdefault(event["task_id"], []).append(event)
    parts = Counter()
    turns = 0
    for result in results:
        if not _ran(result):
            continue
        turns += 1
        own = by_task.get(result["task_id"], [])
        rounds = [e for e in own if e.get("kind") == "model_round"]
        calls = [e for e in own if e.get("kind") == "tool_call"]
        replies = [e for e in own if e.get("kind") == "tool_result"]
        finals = [e for e in own if e.get("kind") == "final"]
        checks = {
            # Tokens per model round: the eval's router wrapper reads usage before
            # the agent does, so per-step tokens are always empty here (ticket 16).
            "rounds_timed_and_counted": bool(rounds) and all(
                r.get("tokens_in") is not None and r.get("tokens_out") is not None and r.get("latency_ms") is not None for r in rounds
            ),
            "calls_named_and_shaped": all(c.get("tool_name") and isinstance(c.get("arguments_shape"), dict) for c in calls),
            "calls_answered": len(replies) >= len(calls) and all("error_code" in r or r.get("content") is not None for r in replies),
            "final_has_stop_reason": bool(finals) and finals[-1].get("stop_reason") is not None,
        }
        parts.update(name for name, ok in checks.items() if ok)
        parts["complete"] += all(checks.values())
    return {
        "turns": turns,
        "complete": parts["complete"],
        "complete_rate": _rate(parts["complete"], turns),
        "parts": {name: parts[name] for name in ("rounds_timed_and_counted", "calls_named_and_shaped", "calls_answered", "final_has_stop_reason")},
    }


def _model_name(manifest: dict[str, Any]) -> str | None:
    return manifest.get("model") or (manifest.get("general_version") or {}).get("model")


def condition(manifest: dict[str, Any], recorded: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cold = the general model was not loaded when the run started (ticket 10's
    rule). From the manifest when the runner recorded Ollama's loaded models,
    else from the conditions file, else unknown."""
    recorded = recorded or {}
    loaded = manifest.get("ollama_loaded_at_start")
    source = "manifest" if loaded is not None else recorded.get("source")
    if loaded is None:
        loaded = recorded.get("loaded_at_start")
    cold = (_model_name(manifest) not in loaded) if loaded is not None else recorded.get("cold")
    # Declared, not inferred: nvidia-smi cannot see another project using the same Ollama.
    shared = manifest.get("gpu_shared")
    return {
        "temperature": manifest.get("temperature"),
        "seed": manifest.get("seed"),
        "cold": cold,
        "loaded_at_start": loaded,
        "source": source,
        "gpu_shared": shared if shared is not None else recorded.get("gpu_shared"),
        "gpu_at_start": manifest.get("gpu_at_start"),
    }


def scorecard(run_dir: Path, recorded: dict[str, Any] | None = None) -> dict[str, Any]:
    run = load_run(run_dir)
    manifest, results, events = run["manifest"], run["results"], run["events"]
    dataset = manifest.get("dataset") or {}
    return {
        "scorecard_version": SCORECARD_VERSION,
        "run_id": manifest.get("run_id") or run_dir.name,
        "commit": manifest.get("commit"),
        "worktree_dirty": manifest.get("worktree_dirty"),
        "dataset_version": dataset.get("version"),
        "dataset_sha256": dataset.get("sha256"),
        "grader_version": manifest.get("grader_version"),
        "model": _model_name(manifest),
        "started_at": manifest.get("started_at"),
        "condition": condition(manifest, recorded),
        "correctness": correctness(results),
        "efficiency": efficiency(results),
        "robustness": robustness(results, events),
        "traceability": traceability(results, events),
        "limits": {
            "points_per_task": round(100 / len(results), 2) if results else None,
            "cold_rule": "so ở nhiệt độ 0 chỉ giữa các lần lạnh (gỡ model chính trước mỗi lần đo)",
            "first_divergence_rule": "so từng bài chỉ chắc tới chỗ câu trả lời khác nhau đầu tiên",
            "fabrication": "chỉ đếm được ở bài có tiêu chí phủ định",
        },
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, dict):
        return ", ".join(f"{k} {_fmt(v)}" for k, v in value.items()) or "—"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "—"
    return str(value)


def render(card: dict[str, Any]) -> str:
    c, e, r, t, cond = card["correctness"], card["efficiency"], card["robustness"], card["traceability"], card["condition"]
    cold = {True: "lạnh", False: "nóng", None: "lạnh/nóng không rõ"}[cond["cold"]]
    shared = {True: "GPU dùng chung", False: "GPU riêng", None: "GPU dùng chung: không rõ"}[cond["gpu_shared"]]
    per_category = {name: f"{v['passed']}/{v['tasks']}" for name, v in c["by_category"].items()}
    stop = r.get("stop_reasons")
    stop_text = _fmt(stop) if stop is not None else "n/a: " + str(r.get("stop_reasons_unavailable") or r.get("unavailable"))
    lines = [
        f"## Bảng điểm `{card['run_id']}`",
        "",
        f"commit `{str(card['commit'])[:7]}` · {card['dataset_version']} (`{str(card['dataset_sha256'])[:12]}`) · "
        f"{card['grader_version']} · {card['model']} · t={cond['temperature']} seed={cond['seed']} · {cold}"
        + (f" ({cond['source']})" if cond["source"] else "") + f" · {shared}",
        "",
        "| Chiều | Chỉ số | Giá trị |",
        "|---|---|---|",
        f"| Đúng | đạt | {c['passed']}/{c['tasks']} ({_fmt(c['pass_rate'])}) |",
        f"| Đúng | theo loại | {_fmt(per_category)} |",
        f"| Đúng | bịa (nói ra điều bị cấm: trượt must_not_mention) | {c['fabricated']} {_fmt(c['fabricated_tasks']) if c['fabricated_tasks'] else ''} |",
        f"| Đúng | chưa nói rõ \"không tìm thấy\" (trượt not_found, có thể do mẫu của bộ chấm) | {c['not_found_missed']} {_fmt(c['not_found_missed_tasks']) if c['not_found_missed_tasks'] else ''} |",
        f"| Đúng | trích nguồn đúng / nguyên văn | {c['citation_passed']}/{c['citation_tasks']} / {c['citation_verbatim']} |",
        f"| Hiệu quả | token vào mỗi bài (TB / trung vị) | {_fmt(e['tokens_in_mean'])} / {_fmt(e['tokens_in_median'])} |",
        f"| Hiệu quả | token ra mỗi bài (TB / trung vị) | {_fmt(e['tokens_out_mean'])} / {_fmt(e['tokens_out_median'])} |",
        f"| Hiệu quả | vòng model mỗi bài | {_fmt(e['model_rounds_mean'])} |",
        f"| Hiệu quả | lượt gọi công cụ cho mỗi bài giải được (TB của riêng bài đạt) | {_fmt(e['tool_calls_per_solved'])} ({_fmt(e['tool_calls_mean_of_solved'])}) |",
        f"| Hiệu quả | độ trễ p50 / p95 / max (ms) | {_fmt(e['latency_p50_ms'])} / {_fmt(e['latency_p95_ms'])} / {_fmt(e['latency_max_ms'])} |",
        f"| Bền | lỗi của bài | {_fmt(r['task_errors'])} |",
        f"| Bền | stop_reason | {stop_text} |",
        f"| Bền | số max_steps khớp số budget_exhausted ({r['budget_exhausted']}) | {_fmt(r.get('max_steps_matches_budget_exhausted'))} |",
        f"| Bền | mã lỗi công cụ (không mã) | {_fmt(r.get('tool_error_codes'))} ({_fmt(r.get('tool_errors_uncoded'))}) |",
        f"| Bền | tỉ lệ BAD_ARGUMENTS | {_fmt(r.get('bad_arguments_rate'))} |",
        f"| Bền | kết quả bị cắt theo mục | {_fmt(r.get('results_trimmed_by_item'))} |",
    ]
    if "unavailable" in t:
        lines.append(f"| Minh bạch | lượt tái dựng trọn | n/a: {t['unavailable']} |")
    else:
        lines.append(f"| Minh bạch | lượt tái dựng trọn | {t['complete']}/{t['turns']} ({_fmt(t['complete_rate'])}) |")
        lines.append(f"| Minh bạch | từng phần | {_fmt(t['parts'])} |")
    limits = card["limits"]
    lines += [
        "",
        f"Giới hạn: 1 bài = {limits['points_per_task']} điểm %; {limits['cold_rule']}; {limits['first_divergence_rule']}; "
        f"bịa {limits['fabrication']}.",
    ]
    return "\n".join(lines) + "\n"


class Incomparable(ValueError):
    """Two runs on different datasets or graders: their numbers do not compare."""


SCALARS = (
    ("correctness", "pass_rate"), ("correctness", "fabricated"), ("correctness", "not_found_missed"), ("correctness", "citation_rate"),
    ("efficiency", "tokens_in_mean"), ("efficiency", "tokens_out_mean"), ("efficiency", "model_rounds_mean"),
    ("efficiency", "tool_calls_per_solved"), ("efficiency", "latency_p50_ms"), ("efficiency", "latency_p95_ms"),
    ("robustness", "bad_arguments_rate"), ("robustness", "results_trimmed_by_item"), ("traceability", "complete_rate"),
)


def compare(run_a: Path, run_b: Path) -> str:
    a, b = scorecard(run_a), scorecard(run_b)
    if (a["dataset_sha256"], a["grader_version"]) != (b["dataset_sha256"], b["grader_version"]):
        raise Incomparable(
            f"không so: {a['run_id']} dùng {a['dataset_version']}/{a['grader_version']}, "
            f"{b['run_id']} dùng {b['dataset_version']}/{b['grader_version']}; chỉ so khi cùng dataset (sha256) và bộ chấm"
        )
    shared_a, shared_b = a["condition"]["gpu_shared"], b["condition"]["gpu_shared"]
    # Latency measures the card as much as the harness: compared only when both
    # runs declare the same sharing.
    latency_note = None if shared_a is not None and shared_a == shared_b else (
        f"không so: GPU dùng chung {_fmt(shared_a)} / {_fmt(shared_b)}"
    )
    lines = [f"## So `{a['run_id']}` → `{b['run_id']}`", "", "| Chỉ số | A | B | B − A |", "|---|---|---|---|"]
    for section, key in SCALARS:
        va, vb = a[section].get(key), b[section].get(key)
        delta = round(vb - va, 4) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
        shown = latency_note if key.startswith("latency") and latency_note else _fmt(delta)
        lines.append(f"| {section}.{key} | {_fmt(va)} | {_fmt(vb)} | {shown} |")
    ra = {r["task_id"]: r for r in load_run(run_a)["results"]}
    rb = {r["task_id"]: r for r in load_run(run_b)["results"]}
    order = [task_id for task_id in ra if task_id in rb]
    first = next((task_id for task_id in order if ra[task_id]["answer"] != rb[task_id]["answer"]), None)
    after = order[order.index(first) + 1:] if first else []
    lines += ["", f"Câu trả lời khác nhau đầu tiên: {first or 'không có'}.", ""]
    flips = [task_id for task_id in order if ra[task_id]["passed"] != rb[task_id]["passed"]]
    for task_id in flips:
        note = " (sau chỗ khác đầu tiên: chỉ tham khảo)" if task_id in after else ""
        lines.append(f"- {task_id}: {'đạt' if ra[task_id]['passed'] else 'trượt'} → {'đạt' if rb[task_id]['passed'] else 'trượt'}{note}")
    if not flips:
        lines.append("- không bài nào đổi đạt/trượt")
    return "\n".join(lines) + "\n"


def _flat(card: dict[str, Any]) -> dict[str, Any]:
    return {f"{section}.{key}": card[section].get(key) for section, key in SCALARS}


def history_line(card: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    try:
        where = run_dir.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        where = str(run_dir)
    return {
        "scorecard_version": card["scorecard_version"],
        "run_id": card["run_id"],
        "path": where,
        "commit": card["commit"],
        "started_at": card["started_at"],
        "dataset_version": card["dataset_version"],
        "dataset_sha256": card["dataset_sha256"],
        "grader_version": card["grader_version"],
        "model": card["model"],
        **{f"condition.{k}": v for k, v in card["condition"].items()},
        "passed": card["correctness"]["passed"],
        "tasks": card["correctness"]["tasks"],
        **_flat(card),
    }


def append_history(card: dict[str, Any], run_dir: Path, path: Path = HISTORY_PATH) -> None:
    """One line per (run_id, commit), replaced when recomputed; sorted by start time."""
    line = history_line(card, run_dir)
    rows = _jsonl(path) if path.exists() else []
    rows = [row for row in rows if (row["run_id"], row["commit"]) != (line["run_id"], line["commit"])] + [line]
    rows.sort(key=lambda row: (str(row.get("started_at")), row["run_id"]))
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8", newline="\n")


def recorded_conditions() -> dict[str, Any]:
    if not CONDITIONS_PATH.exists():
        return {}
    return json.loads(CONDITIONS_PATH.read_text(encoding="utf-8"))["runs"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path, help="run directories")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("RUN_A", "RUN_B"))
    parser.add_argument("--append-history", action="store_true", help="also append each run to the tracked history (kept runs only)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.compare:
        try:
            print(compare(*args.compare))
        except Incomparable as error:
            print(f"CẢNH BÁO: {error}", file=sys.stderr)
            return 2
        return 0
    conditions = recorded_conditions()
    for run_dir in args.runs:
        card = scorecard(run_dir, conditions.get(run_dir.name))
        print(render(card))
        if args.append_history:
            append_history(card, run_dir)
        else:
            (run_dir / "scorecard.json").write_text(json.dumps(card, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
