"""Same-day 2B baseline (proposal 1 of .scratch/harness-research/REPORT.md). Written 11/11 with nothing
allowed to run; only --plan has been run (step 0 of the preregistration). Read
.scratch/harness-research/PREREGISTRATION-2b-baseline.md first.

    .venv/Scripts/python.exe -X utf8 backend/scripts/run_2b_baseline.py <out_dir>
    .venv/Scripts/python.exe -X utf8 backend/scripts/run_2b_baseline.py <out_dir> --plan   # print the jobs, run nothing

Adapted from data/evaluation/results/kept/small-models/run_small_models.py (08/11), with these changes:

- One model, qwen3.5:2b. Arms: bare and harness on three BFCL categories; Agent Eval with the parity
  options off, clock only, and both on, on v0 and on v0-discord-chat.
- It refuses to start while a tracked or untracked file under the product paths (PRODUCT_PATHS) differs
  from HEAD, and writes what it saw to <out_dir>/refused-dirty.json. .scratch/ and the results folders
  are not product paths.
- <out_dir>/run_manifest.json records the Ollama version, the model digest and the commit of the first
  start. A later start in the same folder goes on only when all three are the same and readable;
  otherwise it refuses and says the run cannot be resumed.
- STOP, not pause. A GPU at or above 85 °C, a GPU whose temperature cannot be read, a League process, an
  Ollama version that changed, or an Ollama that stays unreachable ends the whole run (exit 3). The job
  that was running is killed and its folder kept aside as -aborted; nothing in it is scored.
  (08/11 suspended the process instead; the agent's wall-clock turn budget kept running meanwhile, so
  every paused harness job had to be thrown away anyway.)
- A job is done only with every expected task and no task carrying an error, in either arm: the harness
  writes an `error` key, the bare arm writes result "Error during inference: ..." with a `traceback`.
  A job that ends with such tasks is run once more, whole, at the end (folder <job>-rerun).
- Which copy of a job is scored: <job>-rerun when it has a done.json, otherwise <job> when it has one.
  <out_dir>/scored.json lists the folder scored for every job, and is rewritten at the end of each start.
- An unexpected error inside a job marks its folder -aborted and ends the run (exit 4).
- Before and after every job, HEAD and the product paths are checked again: other sessions edit this
  checkout. If either moved, the job is -aborted and the run is closed for good (INVALID.json).
- None of 08/11's bare result files (2B, LFM3, 9B; searched 11/11) holds an "Error during inference"
  line, so a call the server rejects has not so far shown up as one. If a model-made error ever does,
  the job fails twice the same way and is reported as not measured, for the owner to read.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import psutil

REPO = Path(__file__).resolve().parents[2]
BFCL_PY = r"C:\Users\dungbt06\tools\bfcl-venv\Scripts\python.exe"
UN_PY = str(REPO / ".venv" / "Scripts" / "python.exe")
ENV_FILE = str(REPO / ".env")
MODEL = "qwen3.5:2b"
SLUG = "qwen3-5-2b"
BARE_MODEL_DIR = f"{SLUG}-bare-ollama"  # bfcl_bare.names_for(MODEL)[0]
HOT = 85
AE_V0 = REPO / "data" / "benchmarks" / "agent_eval" / "v0"
AE_DISCORD = REPO / "data" / "benchmarks" / "agent_eval" / "v0-discord-chat"
CLOCK_ONLY = ["--clock-note"]
PARITY = ["--clock-note", "--discord-persona"]
# What must equal HEAD for the run to start (PREREG, "Điều kiện cố định"). A path that does not exist is skipped.
PRODUCT_PATHS = ("backend", "discord_bot", "config", "data/benchmarks")
PREREG_RULE = "PREREGISTRATION-2b-baseline.md, mục 'Dừng và chạy lại'"
# Seconds per task before a job counts as hung, as on 08/11.
LIMIT_PER_TASK = {"bare": 40, "harness": 80, "ae": 120}
MULTI_TURN_FACTOR = 4
BARE_ERROR = "Error during inference"  # bfcl_eval/_llm_response_generation.py writes this as the result, with a traceback


class Stopped(Exception):
    """The run must end now. `resumable` is False when what was measured so far no longer belongs to one run."""

    def __init__(self, reason: str, resumable: bool = True) -> None:
        super().__init__(reason)
        self.resumable = resumable


def log(out: Path, text: str) -> None:
    line = f"{datetime.now():%m-%d %H:%M:%S} {text}"
    print(line, flush=True)
    with open(out / "progress.log", "a", encoding="utf-8") as sink:
        sink.write(line + "\n")


def gpu_temp() -> int | None:
    """None when nvidia-smi gives no reading in three tries: an unread temperature is not a cool one."""
    for _ in range(3):
        try:
            shown = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
            return int(shown.stdout.strip().splitlines()[0])
        except Exception:
            time.sleep(2)
    return None


def league_running() -> bool:
    return any((process.info["name"] or "").lower().startswith("league") for process in psutil.process_iter(["name"]))


def ollama(path: str) -> dict:
    with urllib.request.urlopen("http://localhost:11434" + path, timeout=10) as response:
        return json.loads(response.read())


def ollama_version() -> str | None:
    """The version string, or None when Ollama did not answer in four tries, 5 seconds apart."""
    for _ in range(4):
        try:
            version = ollama("/api/version")["version"]
            if isinstance(version, str) and version:
                return version
        except Exception:
            pass
        time.sleep(5)
    return None


def digest() -> str | None:
    try:
        return next((str(model["digest"])[:12] for model in ollama("/api/tags").get("models", []) if model.get("name") == MODEL), None)
    except Exception:
        return None


def git(*args: str) -> str | None:
    shown = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return shown.stdout if shown.returncode == 0 else None


def product_dirt() -> dict | None:
    """None when every product path equals HEAD. Otherwise what differs: the status lines and a hash of the
    diff of the tracked files. An unreadable git counts as dirty."""
    paths = [path for path in PRODUCT_PATHS if (REPO / path).exists()]
    status = git("status", "--porcelain", "--untracked-files=all", "--", *paths)
    if status is None:
        return {"error": "git status could not be read"}
    lines = [line for line in status.splitlines() if line.strip()]
    if not lines:
        return None
    diff = git("diff", "HEAD", "--", *paths) or ""
    return {"paths": paths, "status": lines, "tracked_diff_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest()}


def identity() -> dict:
    """What a run is tied to. A value that cannot be read is None, and None never equals anything."""
    commit = git("rev-parse", "HEAD")
    return {"ollama_version": ollama_version(), "model_digest": digest(), "commit": commit.strip() if commit else None}


def why_stop(version: str) -> Stopped | None:
    temp = gpu_temp()
    if temp is None:
        return Stopped("GPU temperature cannot be read")
    if temp >= HOT:
        return Stopped(f"GPU {temp} °C")
    if league_running():
        return Stopped("League is running")
    now = ollama_version()
    if now is None:
        # Possibly an auto-update restarting it. Whether this run can go on is decided at the next start,
        # against run_manifest.json, never assumed here.
        return Stopped("Ollama unreachable")
    if now != version:
        return Stopped(f"Ollama changed: {version} -> {now}", resumable=False)
    return None


def kill(pid: int) -> None:
    try:
        root = psutil.Process(pid)
        for process in [*root.children(recursive=True), root]:
            try:
                process.kill()
            except psutil.Error:
                pass
    except psutil.NoSuchProcess:
        pass


def guarded(out: Path, argv: list[str], log_path: Path, cwd: Path, limit_seconds: float, version: str) -> int:
    """The job's exit code; -9 when it was killed as hung. Raises Stopped, after killing it."""
    with open(log_path, "a", encoding="utf-8") as sink:
        process = subprocess.Popen(argv, cwd=cwd, stdout=sink, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        started = time.time()
        try:
            while process.poll() is None:
                time.sleep(15)
                stop = why_stop(version)
                if stop is not None:
                    raise stop
                if time.time() - started > limit_seconds:
                    log(out, f"timeout after {(time.time() - started) / 60:.0f} min: killing the job")
                    kill(process.pid)
                    process.wait()
                    return -9
        except BaseException:
            # Stopped, Ctrl+C or anything else: never leave the job running behind a dead runner.
            kill(process.pid)
            process.wait()
            raise
        return process.returncode


def parsed(text: str) -> list[dict]:
    lines: list[dict] = []
    for raw in text.splitlines():
        if raw.strip():
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    return lines


def bfcl_lines(run_dir: Path) -> list[dict]:
    lines: list[dict] = []
    for path in sorted((run_dir / "result").rglob("BFCL_v4_*_result.json")):
        lines.extend(parsed(path.read_text(encoding="utf-8")))
    return lines


def bfcl_error(line: dict) -> bool:
    """A task that was not measured, in either arm's form: bfcl_run's `error` key, or BFCL's own
    result string with a traceback (the bare arm)."""
    result = line.get("result")
    return "error" in line or "traceback" in line or (isinstance(result, str) and result.startswith(BARE_ERROR))


def ae_lines(run_dir: Path) -> list[dict]:
    path = run_dir / "task_results.jsonl"
    return parsed(path.read_text(encoding="utf-8")) if path.is_file() else []


def ae_count(dataset: Path) -> int:
    return len(parsed((dataset / "tasks.jsonl").read_text(encoding="utf-8")))


def jobs(out: Path) -> list[dict]:
    full = json.loads((REPO / "data" / "benchmarks" / "bfcl" / "ids_full.json").read_text(encoding="utf-8"))
    ids_dir = out / "ids"
    ids_dir.mkdir(parents=True, exist_ok=True)
    listed: list[dict] = []

    def bfcl(kind: str, category: str) -> dict:
        ids_path = ids_dir / f"{category}.json"
        ids_path.write_text(json.dumps({category: full[category]}), encoding="utf-8")
        return {"kind": kind, "label": category, "ids": ids_path, "expected": len(full[category]), "run_dir": out / kind / category}

    def ae(label: str, dataset: Path, extra: list[str]) -> dict:
        return {"kind": "ae", "label": label, "dataset": dataset, "extra": extra, "expected": ae_count(dataset), "run_dir": out / "ae" / label}

    # Agent Eval first: its parity options are the only code here that has never run, and the six jobs
    # take about 25 minutes, so a crash shows before the long BFCL jobs, not after them.
    listed += [ae("v0-parity-off", AE_V0, []), ae("v0-parity-on", AE_V0, PARITY), ae("v0-clock-only", AE_V0, CLOCK_ONLY)]
    listed += [ae("discord-chat-parity-on", AE_DISCORD, PARITY), ae("discord-chat-parity-off", AE_DISCORD, []), ae("discord-chat-clock-only", AE_DISCORD, CLOCK_ONLY)]
    # Arms alternate inside a category, so a drift over the hours falls on both.
    listed += [bfcl("bare", "simple_python"), bfcl("harness", "simple_python")]
    listed += [bfcl("harness", "irrelevance"), bfcl("bare", "irrelevance")]
    listed += [bfcl("bare", "multi_turn_base"), bfcl("harness", "multi_turn_base")]
    return listed


def command(job: dict, run_dir: Path) -> tuple[list[str], Path]:
    if job["kind"] == "bare":
        return [BFCL_PY, "-X", "utf8", str(REPO / "backend" / "scripts" / "bfcl_bare.py"), "--model", MODEL, "--ids", str(job["ids"]), str(run_dir)], REPO
    if job["kind"] == "harness":
        return [UN_PY, "-X", "utf8", "-m", "scripts.bfcl_run", "--env-file", ENV_FILE, "--model", MODEL, "--ids", str(job["ids"]),
                "--run-id", run_dir.name, "--gpu-shared", "no", "--unload-between-tasks", "--out", str(run_dir.parent)], REPO / "backend"
    return [UN_PY, "-X", "utf8", "-m", "scripts.agent_eval", "--env-file", ENV_FILE, "--model", MODEL, "--dataset", str(job["dataset"]),
            "--temperature", "0", "--seed", "42", "--unload-between-tasks", "--gpu-shared", "no", *job["extra"],
            "--out", str(run_dir.parent), "--run-id", run_dir.name], REPO / "backend"


def rerun_dir(job: dict) -> Path:
    return job["run_dir"].with_name(job["run_dir"].name + "-rerun")


def scored_dir(job: dict) -> Path | None:
    """The one folder of a job that is scored: the rerun when it finished, otherwise the first run when it did."""
    for candidate in (rerun_dir(job), job["run_dir"]):
        if (candidate / "done.json").is_file():
            return candidate
    return None


def set_aside(run_dir: Path, mark: str) -> None:
    if run_dir.exists():
        run_dir.rename(run_dir.with_name(run_dir.name + f"-{mark}-{datetime.now():%H%M%S}"))


def run_job(out: Path, job: dict, version: str, commit: str, rerun: bool = False) -> str:
    """'done' or 'failed'. Raises Stopped; any other exception has already set the folder aside as -aborted."""
    run_dir = rerun_dir(job) if rerun else job["run_dir"]
    name = f"{job['kind']} {job['label']}{'-rerun' if rerun else ''}"
    if scored_dir(job) is not None:
        log(out, f"skip {name}: done in {scored_dir(job).name}")
        return "done"
    if (run_dir / "failed.json").is_file():
        # Kept where it is, for the record: a failed first run goes to the rerun, a failed rerun is final.
        log(out, f"skip {name}: failed in an earlier start")
        return "failed"
    set_aside(run_dir, "partial")
    stop = why_stop(version) or code_moved(commit)
    if stop is not None:
        raise stop
    try:
        status = measure(out, job, run_dir, name, version)
        # Other sessions edit this checkout, and every job is a new process reading the files as they are:
        # a job during which the code moved was not measured on the commit the manifest names.
        moved = code_moved(commit)
        if moved is not None:
            raise moved
        return status
    except Stopped:
        abort(out, run_dir)
        raise
    except Exception as error:
        abort(out, run_dir)
        log(out, f"UNEXPECTED {name}: {type(error).__name__}: {error}")
        raise


def abort(out: Path, run_dir: Path) -> None:
    """Set the folder aside as -aborted. A folder Windows will not let go of is marked in place instead, so
    the stop that caused this is still reported as what it is."""
    try:
        set_aside(run_dir, "aborted")
    except OSError as locked:
        log(out, f"could not rename {run_dir.name} ({locked}): marked with ABORTED.json instead; its done.json, if any, is removed")
        try:
            (run_dir / "done.json").unlink(missing_ok=True)
            (run_dir / "ABORTED.json").write_text(json.dumps({"at": datetime.now().isoformat()}), encoding="utf-8")
        except OSError:
            pass


def code_moved(commit: str) -> Stopped | None:
    """Not resumable: HEAD is no longer the run's commit, or a product path no longer equals it."""
    head = git("rev-parse", "HEAD")
    if head is None or head.strip() != commit:
        return Stopped(f"HEAD moved: {commit} -> {head.strip() if head else 'unreadable'}", resumable=False)
    dirt = product_dirt()
    if dirt is not None:
        return Stopped(f"product paths no longer equal HEAD: {dirt.get('status') or dirt.get('error')}", resumable=False)
    return None


def measure(out: Path, job: dict, run_dir: Path, name: str, version: str) -> str:
    limit = max(LIMIT_PER_TASK[job["kind"]] * job["expected"] * (MULTI_TURN_FACTOR if "multi_turn" in job["label"] else 1), 20 * 60)
    argv, cwd = command(job, run_dir)
    logs = out / "logs"
    logs.mkdir(exist_ok=True)
    log(out, f"start {name} ({job['expected']} tasks), GPU {gpu_temp()} °C: {' '.join(argv)}")
    started = time.time()
    code = guarded(out, argv, logs / f"{run_dir.parent.name}-{run_dir.name}.log", cwd, limit, version)
    minutes = (time.time() - started) / 60
    score_line = ""
    if job["kind"] == "ae":
        lines = ae_lines(run_dir)
        count, errors = len(lines), sum(1 for line in lines if line.get("error"))
        if count == job["expected"] and (run_dir / "summary.json").is_file():
            overall = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))["overall"]
            score_line = f"{overall['passed']}/{overall['total']}"
    else:
        lines = bfcl_lines(run_dir)
        count, errors = len(lines), sum(1 for line in lines if bfcl_error(line))
        if count == job["expected"]:
            model_dir = BARE_MODEL_DIR if job["kind"] == "bare" else "un-harness"
            scored = subprocess.run([BFCL_PY, "-X", "utf8", str(REPO / "backend" / "scripts" / "bfcl_score.py"), str(run_dir), "--model-dir", model_dir],
                                    capture_output=True, text=True)
            score_line = " | ".join(line.split("failed")[0].strip() for line in scored.stdout.splitlines() if line.split(" ")[0] == job["label"])
            if not (run_dir / "scores.json").is_file():
                count = -1  # the scorer failed: not done
    record = {"exit": code, "tasks": count, "errors": errors, "minutes": round(minutes, 1), "ollama": version, "score": score_line}
    run_dir.mkdir(parents=True, exist_ok=True)
    if count != job["expected"] or errors:
        (run_dir / "failed.json").write_text(json.dumps(record), encoding="utf-8")
        log(out, f"FAILED {name}: exit {code}, {count}/{job['expected']} tasks, {errors} not measured, {minutes:.0f} min; {score_line}")
        return "failed"
    (run_dir / "done.json").write_text(json.dumps(record), encoding="utf-8")
    log(out, f"done {name}: exit {code}, {minutes:.0f} min, {score_line}")
    return "done"


def write_scored(out: Path, planned: list[dict]) -> None:
    listed = {f"{job['kind']}/{job['label']}": (str(scored_dir(job).relative_to(out)) if scored_dir(job) else None) for job in planned}
    (out / "scored.json").write_text(json.dumps(listed, ensure_ascii=False, indent=2), encoding="utf-8")


def refuse(out: Path, text: str) -> int:
    log(out, f"REFUSED: {text}")
    return 2


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    planned = jobs(out)
    if "--plan" in sys.argv[2:]:
        for job in planned:
            argv, cwd = command(job, job["run_dir"])
            print(f"[{job['expected']:>3} tasks] cwd={cwd}\n    {' '.join(argv)}")
        return 0

    dirt = product_dirt()
    if dirt is not None:
        (out / "refused-dirty.json").write_text(json.dumps({"at": datetime.now().isoformat(), **dirt}, ensure_ascii=False, indent=2), encoding="utf-8")
        return refuse(out, f"product paths differ from HEAD ({len(dirt.get('status', []))} entries, see refused-dirty.json). Commit or stash them first: "
                           "PREREGISTRATION-2b-baseline.md, mục 'Điều kiện cố định'.")
    now = identity()
    missing = [key for key, value in now.items() if value is None]
    if missing:
        return refuse(out, f"cannot read {', '.join(missing)}: nothing run. A run is tied to all three.")
    manifest_path = out / "run_manifest.json"
    if (out / "INVALID.json").is_file():
        return refuse(out, f"this folder was closed by an Ollama change and CANNOT BE RESUMED. Its finished jobs are not a baseline. Start a new folder: {PREREG_RULE}.")
    if manifest_path.is_file():
        first = json.loads(manifest_path.read_text(encoding="utf-8"))["identity"]
        changed = [f"{key}: {first.get(key)} -> {now[key]}" for key in now if first.get(key) != now[key]]
        if changed:
            return refuse(out, f"THIS RUN CANNOT BE RESUMED: {'; '.join(changed)}. Jobs already finished here were measured on something else "
                               f"and must not be mixed with new ones. Start a new folder: {PREREG_RULE}.")
        log(out, f"resuming: same Ollama {now['ollama_version']}, digest {now['model_digest']}, commit {now['commit']}")
    else:
        manifest_path.write_text(json.dumps({"identity": now, "model": MODEL, "started_at": datetime.now().isoformat(),
                                             "product_paths_clean": [path for path in PRODUCT_PATHS if (REPO / path).exists()]}, ensure_ascii=False, indent=2), encoding="utf-8")
    version = now["ollama_version"]
    log(out, f"plan: {len(planned)} jobs, model {MODEL} {now['model_digest']}, Ollama {version}, GPU {gpu_temp()} °C, commit {now['commit']}")

    try:
        again = [job for job in planned if run_job(out, job, version, now["commit"]) == "failed"]
        gave_up = [job for job in again if run_job(out, job, version, now["commit"], rerun=True) == "failed"]
    except Stopped as stopped:
        write_scored(out, planned)
        if not stopped.resumable:
            (out / "INVALID.json").write_text(json.dumps({"at": datetime.now().isoformat(), "reason": str(stopped)}), encoding="utf-8")
            log(out, f"STOPPED: {stopped}. THIS RUN CANNOT BE RESUMED and its finished jobs are not a baseline: {PREREG_RULE}. Start a new folder.")
        else:
            log(out, f"STOPPED: {stopped}. Nothing from the aborted job is scored. The next start in this folder checks Ollama's version, "
                     f"the model digest and the commit against run_manifest.json and refuses if any changed or cannot be read: {PREREG_RULE}.")
        return 3
    except Exception:
        write_scored(out, planned)
        log(out, "STOPPED on an unexpected error (see UNEXPECTED above). The job's folder is -aborted; read the error before starting again.")
        return 4
    write_scored(out, planned)
    for job in gave_up:
        log(out, f"GAVE UP {job['kind']} {job['label']}: failed twice, reported as not measured")
    log(out, "all done")
    return 1 if gave_up else 0


if __name__ == "__main__":
    raise SystemExit(main())
