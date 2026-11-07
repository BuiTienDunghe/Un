"""Small-model comparison (08/11): qwen3.5:9b, lfm3:1.7b, qwen3.5:2b, each bare and in the harness.

    .venv/Scripts/python.exe run_small_models.py <out_dir>

Jobs run in the fixed order below. Within a category the models and arms are interleaved, so a drift
over the hours falls on every arm. The fixes over run_full_bfcl.py (07/11) are these:

- A job counts as done only when its result holds every expected task. Exit code and the scorer's
  output alone do not count. Done jobs carry a done.json, and a rerun skips only those.
- A failed job does not stop the night. It is logged and retried once at the end.
- Pauses: a GPU at or above 85 °C, or a League process, suspends the job's process tree until the
  GPU is at or below 75 °C and League is gone, as before. The harness and Agent Eval budget each turn
  by wall clock, which keeps running while the process is suspended. So a harness or Agent Eval job
  that was paused is rerun whole once at the end, and the paused copy is kept for the record. The
  bare arm has no wall-clock budget and is not rerun.
- 9B, simple_python: 07/11 has already measured all 400 tasks. Here the 81 ablation tasks are run again,
  per arm. If any task's calls differ from 07/11, that arm is queued for the full 400.
- 9B, multi_turn_base, harness: 07/11 ran 159 tasks. Here the remaining 41 are run, plus the first 20
  of the 159 as a same-day check.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

REPO = Path(r"C:\Users\dungbt06\local-ai-core")
BFCL_PY = r"C:\Users\dungbt06\tools\bfcl-venv\Scripts\python.exe"
UN_PY = str(REPO / ".venv" / "Scripts" / "python.exe")
ENV_FILE = str(REPO / ".env")
FULL_RUN = REPO / "data" / "evaluation" / "results" / "bfcl-full-run"
ABLATION_IDS = REPO / "data" / "evaluation" / "results" / "bfcl-guide-ablation" / "ids.json"
NINE, LFM, TWO = "qwen3.5:9b", "lfm3:1.7b", "qwen3.5:2b"
HOT, COOL = 85, 75


def slug(model: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in model.lower()).strip("-")


def bare_dir_name(model: str) -> str:
    return "qwen-bare-ollama" if model == NINE else f"{slug(model)}-bare-ollama"


def log(out: Path, text: str) -> None:
    line = f"{datetime.now():%m-%d %H:%M:%S} {text}"
    print(line, flush=True)
    with open(out / "progress.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def gpu_temp() -> int:
    try:
        return int(subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
                                  capture_output=True, text=True, timeout=20).stdout.strip().splitlines()[0])
    except Exception:
        return 0


def league_running() -> bool:
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower().startswith("league"):
            return True
    return False


def ollama_version() -> str:
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:11434/api/version", timeout=10) as r:
            return json.loads(r.read())["version"]
    except Exception as exc:
        return f"down ({exc})"


def tree(pid: int) -> list[psutil.Process]:
    try:
        root = psutil.Process(pid)
        return [root, *root.children(recursive=True)]
    except psutil.NoSuchProcess:
        return []


def guarded(out: Path, argv: list[str], log_path: Path, cwd: Path) -> tuple[int, int]:
    """(exit code, number of pauses)."""
    pauses = 0
    with open(log_path, "a", encoding="utf-8") as sink:
        proc = subprocess.Popen(argv, cwd=cwd, stdout=sink, stderr=subprocess.STDOUT,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        while proc.poll() is None:
            time.sleep(15)
            temp, league = gpu_temp(), league_running()
            if temp >= HOT or league:
                pauses += 1
                log(out, f"pause: GPU {temp} °C, League {league}")
                for p in tree(proc.pid):
                    try:
                        p.suspend()
                    except psutil.Error:
                        pass
                while True:
                    time.sleep(30)
                    temp, league = gpu_temp(), league_running()
                    if temp <= COOL and not league:
                        break
                for p in tree(proc.pid):
                    try:
                        p.resume()
                    except psutil.Error:
                        pass
                log(out, f"resume: GPU {temp} °C")
        return proc.returncode, pauses


def result_lines(run_dir: Path) -> list[dict]:
    lines: list[dict] = []
    for path in sorted((run_dir / "result").rglob("BFCL_v4_*_result.json")):
        lines.extend(json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())
    return lines


def ae_count(run_dir: Path) -> int:
    path = run_dir / "task_results.jsonl"
    return sum(1 for l in path.read_text(encoding="utf-8").splitlines() if l.strip()) if path.is_file() else 0


def write_ids(out: Path, name: str, ids: dict[str, list[str]]) -> Path:
    path = out / "ids" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ids), encoding="utf-8")
    return path


def job(kind: str, model: str, label: str, ids_path: Path | None, expected: int, out: Path) -> dict:
    if kind == "bare":
        run_dir = out / "bare" / slug(model) / label
    elif kind == "harness":
        run_dir = out / "harness" / slug(model) / label
    else:
        run_dir = out / "ae" / slug(model)
    return {"kind": kind, "model": model, "label": label, "ids": ids_path, "expected": expected, "run_dir": run_dir}


def run_job(out: Path, j: dict, attempt: str = "") -> str:
    """'done', 'failed' or 'paused' (complete, but a wall-clock arm was suspended)."""
    run_dir: Path = j["run_dir"]
    if attempt:
        run_dir = run_dir.with_name(run_dir.name + attempt)
    name = f"{j['kind']} {j['model']} {j['label']}{attempt}"
    if (run_dir / "done.json").is_file():
        log(out, f"skip {name}: done")
        return "done"
    if run_dir.exists():
        # A job that did not finish leaves a partial folder; start it clean, keeping the old one aside.
        run_dir.rename(run_dir.with_name(run_dir.name + f"-partial-{datetime.now():%H%M%S}"))
    before = ollama_version()
    log(out, f"start {name} ({j['expected']} tasks), Ollama {before}, GPU {gpu_temp()} °C")
    started = time.time()
    logs = out / "logs"
    logs.mkdir(exist_ok=True)
    log_path = logs / f"{j['kind']}-{slug(j['model'])}-{j['label']}{attempt}.log"
    if j["kind"] == "bare":
        argv = [BFCL_PY, "-X", "utf8", str(REPO / "backend" / "scripts" / "bfcl_bare.py"), "--model", j["model"],
                "--ids", str(j["ids"]), str(run_dir)]
        code, pauses = guarded(out, argv, log_path, REPO)
    elif j["kind"] == "harness":
        argv = [UN_PY, "-X", "utf8", "-m", "scripts.bfcl_run", "--env-file", ENV_FILE, "--model", j["model"],
                "--ids", str(j["ids"]), "--run-id", run_dir.name, "--gpu-shared", "no", "--unload-between-tasks",
                "--out", str(run_dir.parent)]
        code, pauses = guarded(out, argv, log_path, REPO / "backend")
    else:
        argv = [UN_PY, "-X", "utf8", "-m", "scripts.agent_eval", "--env-file", ENV_FILE, "--model", j["model"],
                "--temperature", "0", "--seed", "42", "--unload-between-tasks", "--gpu-shared", "no",
                "--out", str(run_dir.parent), "--run-id", run_dir.name]
        code, pauses = guarded(out, argv, log_path, REPO / "backend")
    after = ollama_version()
    if after != before:
        log(out, f"OLLAMA CHANGED during {name}: {before} -> {after}")
    minutes = (time.time() - started) / 60
    if j["kind"] == "ae":
        count = ae_count(run_dir)
        score_line = ""
        if count == j["expected"]:
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))["overall"]
            score_line = f"{summary['passed']}/{summary['total']}"
    else:
        count = len(result_lines(run_dir))
        score_line = ""
        if count == j["expected"]:
            model_dir = bare_dir_name(j["model"]) if j["kind"] == "bare" else "un-harness"
            score = subprocess.run([BFCL_PY, "-X", "utf8", str(REPO / "backend" / "scripts" / "bfcl_score.py"),
                                    str(run_dir), "--model-dir", model_dir], capture_output=True, text=True)
            score_line = " | ".join(l.split("failed")[0].strip() for l in score.stdout.splitlines()
                                    if l.split(" ")[0] in ("simple_python", "irrelevance", "multi_turn_base"))
            if not (run_dir / "scores.json").is_file():
                count = -1  # scorer failed: not done
    if count != j["expected"]:
        log(out, f"FAILED {name}: exit {code}, {count}/{j['expected']} tasks, {minutes:.0f} min")
        return "failed"
    status = "paused" if pauses and j["kind"] in ("harness", "ae") else "done"
    (run_dir / "done.json").write_text(json.dumps({"exit": code, "tasks": count, "minutes": round(minutes, 1),
                                                    "pauses": pauses, "ollama": after, "status": status}), encoding="utf-8")
    log(out, f"done {name}: exit {code}, {minutes:.0f} min, {score_line}" + (f", {pauses} pause(s)" if pauses else ""))
    return status


def calls_by_id(lines: list[dict]) -> dict[str, str]:
    return {line["id"]: json.dumps(line["result"], sort_keys=True, ensure_ascii=False) for line in lines}


def nine_check(out: Path, kind: str, check_dir: Path) -> int:
    """Tasks of the 81-task check whose calls differ from 07/11."""
    old_dir = FULL_RUN / kind / "simple_python"
    old, new = calls_by_id(result_lines(old_dir)), calls_by_id(result_lines(check_dir))
    differ = sorted(i for i in new if old.get(i) != new[i])
    log(out, f"9B {kind} simple_python check: {len(new) - len(differ)}/{len(new)} same as 07/11" + (f"; differ: {differ}" if differ else ""))
    return len(differ)


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    full = json.loads((REPO / "data" / "benchmarks" / "bfcl" / "ids_full.json").read_text(encoding="utf-8"))
    ids = {
        "simple_python": write_ids(out, "simple_python", {"simple_python": full["simple_python"]}),
        "irrelevance": write_ids(out, "irrelevance", {"irrelevance": full["irrelevance"]}),
        "multi_turn_base": write_ids(out, "multi_turn_base", {"multi_turn_base": full["multi_turn_base"]}),
        "simple_python_check81": write_ids(out, "simple_python_check81", json.loads(ABLATION_IDS.read_text(encoding="utf-8"))),
    }
    done159 = [line["id"] for line in result_lines(FULL_RUN / "partial-backup" / "harness-multi_turn_base-159")]
    rest41 = [i for i in full["multi_turn_base"] if i not in set(done159)]
    ids["mt_rest41"] = write_ids(out, "mt_rest41", {"multi_turn_base": rest41})
    ids["mt_check20"] = write_ids(out, "mt_check20", {"multi_turn_base": done159[:20]})
    log(out, f"plan: 9B multi_turn_base harness has {len(done159)} from 07/11, runs {len(rest41)} more and re-runs 20; "
             f"models {NINE} {LFM} {TWO}; Ollama {ollama_version()}")

    jobs = [
        job("bare", NINE, "simple_python_check81", ids["simple_python_check81"], 81, out),
        job("harness", NINE, "simple_python_check81", ids["simple_python_check81"], 81, out),
        job("bare", LFM, "simple_python", ids["simple_python"], 400, out),
        job("harness", LFM, "simple_python", ids["simple_python"], 400, out),
        job("harness", TWO, "simple_python", ids["simple_python"], 400, out),
        job("bare", TWO, "simple_python", ids["simple_python"], 400, out),
        job("harness", NINE, "irrelevance", ids["irrelevance"], 240, out),
        job("bare", NINE, "irrelevance", ids["irrelevance"], 240, out),
        job("bare", TWO, "irrelevance", ids["irrelevance"], 240, out),
        job("harness", TWO, "irrelevance", ids["irrelevance"], 240, out),
        job("harness", LFM, "irrelevance", ids["irrelevance"], 240, out),
        job("bare", LFM, "irrelevance", ids["irrelevance"], 240, out),
        job("ae", LFM, "agent_eval", None, 66, out),
        job("ae", NINE, "agent_eval", None, 66, out),
        job("ae", TWO, "agent_eval", None, 66, out),
        job("bare", NINE, "multi_turn_base", ids["multi_turn_base"], 200, out),
        job("harness", NINE, "multi_turn_base_rest41", ids["mt_rest41"], len(rest41), out),
        job("harness", NINE, "multi_turn_base_check20", ids["mt_check20"], 20, out),
        job("harness", LFM, "multi_turn_base", ids["multi_turn_base"], 200, out),
        job("bare", LFM, "multi_turn_base", ids["multi_turn_base"], 200, out),
        job("bare", TWO, "multi_turn_base", ids["multi_turn_base"], 200, out),
        job("harness", TWO, "multi_turn_base", ids["multi_turn_base"], 200, out),
    ]
    retry: list[dict] = []
    for j in jobs:
        status = run_job(out, j)
        if status in ("failed", "paused"):
            retry.append(j)
        if status == "done" and j["model"] == NINE and j["label"] == "simple_python_check81":
            if nine_check(out, j["kind"], j["run_dir"]):
                retry.append(job(j["kind"], NINE, "simple_python", ids["simple_python"], 400, out))
                log(out, f"queued: 9B {j['kind']} simple_python 400 (the check differs from 07/11)")
    for j in retry:
        attempt = "" if j["label"] == "simple_python" and j["model"] == NINE else "-rerun"
        status = run_job(out, j, attempt)
        if status != "done":
            log(out, f"GAVE UP {j['kind']} {j['model']} {j['label']}: {status}")
    log(out, "all done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
