"""Run the 10/11 old-vs-new comparison jobs one after another on the GPU.

Stops the job and the whole run at GPU >= 85 C or when a League process appears.
Unloads every Ollama model between jobs. Records peak VRAM, temperature and Ollama
version per job in progress.jsonl.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import urllib.request

MAIN = Path(r"~\local-ai-core")
BRANCH = Path(r"~\local-ai-core-wt\check-c57aa3e")
PY = str(MAIN / ".venv" / "Scripts" / "python.exe")
HERE = Path(__file__).resolve().parent
OUT = MAIN / "data" / "evaluation" / "results" / "c57-compare-20261110"
MANIFEST = BRANCH / "data" / "benchmarks" / "ocr_evidence" / "v1" / "manifest.json"
OLLAMA = "http://127.0.0.1:11434"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def env_for(root: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{root};{root / 'backend'}"
    env["PYTHONUTF8"] = "1"
    env.update(extra)
    return env


def ae(name: str, root: Path, model: str | None, **extra: str) -> dict:
    argv = [PY, "-X", "utf8", "-m", "scripts.agent_eval", "--env-file", str(MAIN / ".env"),
            "--temperature", "0", "--seed", "42", "--unload-between-tasks", "--gpu-shared", "no",
            "--out", str(OUT / "ae"), "--run-id", name]
    if model:
        argv += ["--model", model]
    return {"name": name, "argv": argv, "cwd": root / "backend", "env": env_for(root, **extra)}


def ocr(name: str, root: Path, version: str, qa: str | None = None) -> dict:
    argv = [PY, "-X", "utf8", str(HERE / "ocr_texts.py"), "--manifest", str(MANIFEST),
            "--version", version, "--out", str(OUT / "ocr" / f"{name}.json")]
    if qa:
        argv += ["--qa-model", qa]
    return {"name": name, "argv": argv, "cwd": root / "backend", "env": env_for(root)}


JOBS = [
    ocr("ocr-old-v2-9b", MAIN, "ocr-v2", qa="qwen3.5:9b"),
    ocr("ocr-old-v1-glm", MAIN, "ocr-v1"),
    ocr("ocr-new-ovis", BRANCH, "ocr-ovis-v1"),
    ocr("ocr-new-glm", BRANCH, "ocr-small-v1"),
    {"name": "ocr-new-evidence", "cwd": BRANCH / "backend", "env": env_for(BRANCH),
     "argv": [PY, "-X", "utf8", "-m", "scripts.ocr_evidence_eval", "--manifest", str(MANIFEST),
              "--output", str(OUT / "ocr" / "ocr-new-evidence")]},
    ae("ae-A-main-9b", MAIN, "qwen3.5:9b"),
    ae("ae-C-main-2b", MAIN, "qwen3.5:2b"),
    ae("ae-B-branch-2b", BRANCH, None, DISCORD_MEMORY_EXTRACTOR_MODEL=""),
]


def get(path: str):
    with urllib.request.urlopen(f"{OLLAMA}{path}", timeout=10) as r:
        return json.loads(r.read())


def unload_all() -> list[str]:
    names = [m["name"] for m in get("/api/ps").get("models", [])]
    for name in names:
        body = json.dumps({"model": name, "keep_alive": 0}).encode()
        req = urllib.request.Request(f"{OLLAMA}/api/generate", data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60).read()
    return names


def gpu() -> tuple[int, int]:
    out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu,memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip().split(",")
    return int(out[0]), int(out[1])


def league() -> bool:
    out = subprocess.run(["tasklist"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout.lower()
    # Riot Client services idle in the background; League itself is LeagueClient*/League of Legends.exe.
    return "league" in out


def log(record: dict) -> None:
    record["at"] = time.strftime("%d/%m %H:%M:%S")
    with (OUT / "progress.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False), flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    for job in JOBS:
        if only and job["name"] not in only:
            continue
        unloaded = unload_all()
        time.sleep(3)
        temp, idle_mib = gpu()
        version = get("/api/version")["version"]
        log({"event": "start", "job": job["name"], "ollama": version, "gpu_c": temp, "vram_idle_mib": idle_mib,
             "unloaded": unloaded})
        logf = (OUT / "logs").joinpath(f"{job['name']}.log")
        logf.parent.mkdir(exist_ok=True)
        started = time.time()
        peak_mib, peak_c, stop = idle_mib, temp, None
        with logf.open("w", encoding="utf-8") as handle:
            proc = subprocess.Popen(job["argv"], cwd=job["cwd"], env=job["env"], stdout=handle,
                                    stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            while proc.poll() is None:
                time.sleep(5)
                temp, mib = gpu()
                peak_mib, peak_c = max(peak_mib, mib), max(peak_c, temp)
                if temp >= 85:
                    stop = f"GPU {temp} C"
                elif league():
                    stop = "League running"
                if stop:
                    proc.terminate()
                    proc.wait(30)
                    break
        log({"event": "done", "job": job["name"], "exit": proc.returncode, "minutes": round((time.time() - started) / 60, 1),
             "vram_peak_mib": peak_mib, "gpu_peak_c": peak_c, "ollama_after": get("/api/version")["version"],
             "stopped": stop})
        if stop:
            unload_all()
            return 3
    unload_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
