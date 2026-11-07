"""Both arms of the full BFCL comparison, interleaved by category, with a thermal and League guard.

    .venv/Scripts/python.exe run_full_bfcl.py <out_dir>

Per category: write its ids, run one arm then the other (the first arm alternates by category so a
drift over the hours falls on both), score each. A category whose scores.json exists is skipped, so
a rerun resumes. While a run goes, every 15 s: GPU at or above 85 °C, or a League process, suspends
the run's process tree until the GPU is at or below 75 °C and League is gone. The Ollama version is
recorded around every run; a change is logged.
"""
from __future__ import annotations

import json
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
CATEGORIES = ["simple_python", "multi_turn_base", "irrelevance", "multi_turn_miss_func", "multiple",
              "multi_turn_miss_param", "parallel", "multi_turn_long_context", "parallel_multiple",
              "simple_java", "simple_javascript"]
HOT, COOL = 85, 75


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


def guarded(out: Path, argv: list[str], log_path: Path, cwd: Path) -> int:
    with open(log_path, "a", encoding="utf-8") as sink:
        proc = subprocess.Popen(argv, cwd=cwd, stdout=sink, stderr=subprocess.STDOUT,
                                env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        while proc.poll() is None:
            time.sleep(15)
            temp, league = gpu_temp(), league_running()
            if temp >= HOT or league:
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
        return proc.returncode


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    all_ids = json.loads((REPO / "data" / "benchmarks" / "bfcl" / "ids_full.json").read_text(encoding="utf-8"))
    (out / "ids").mkdir(exist_ok=True)
    for index, category in enumerate(CATEGORIES):
        ids_path = out / "ids" / f"{category}.json"
        ids_path.write_text(json.dumps({category: all_ids[category]}), encoding="utf-8")
        arms = ["bare", "harness"] if index % 2 == 0 else ["harness", "bare"]
        for arm in arms:
            run_dir = out / arm / category
            if (run_dir / "scores.json").is_file():
                log(out, f"skip {arm} {category}: scored")
                continue
            before = ollama_version()
            log(out, f"start {arm} {category} ({len(all_ids[category])} tasks), Ollama {before}, GPU {gpu_temp()} °C")
            started = time.time()
            if arm == "bare":
                code = guarded(out, [BFCL_PY, "-X", "utf8", str(REPO / "backend" / "scripts" / "bfcl_bare.py"),
                                     "--ids", str(ids_path), str(run_dir)], out / f"{arm}-{category}.log", REPO)
                model_dir = "qwen-bare-ollama"
            else:
                code = guarded(out, [UN_PY, "-m", "scripts.bfcl_run", "--probe", "--env-file", ENV_FILE, "--ids", str(ids_path),
                                     "--run-id", category, "--gpu-shared", "no", "--unload-between-tasks",
                                     "--out", str(out / "harness")], out / f"{arm}-{category}.log", REPO / "backend")
                model_dir = "un-harness"
            after = ollama_version()
            if after != before:
                log(out, f"OLLAMA CHANGED during {arm} {category}: {before} -> {after}")
            score = subprocess.run([BFCL_PY, "-X", "utf8", str(REPO / "backend" / "scripts" / "bfcl_score.py"), str(run_dir),
                                    "--model-dir", model_dir], capture_output=True, text=True)
            line = next((l for l in score.stdout.splitlines() if l.startswith(category)), score.stderr[-300:])
            log(out, f"done {arm} {category}: exit {code}, {(time.time() - started) / 60:.0f} min, {line.split('failed')[0].strip()}")
    log(out, "all done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
