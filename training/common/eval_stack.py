"""Start an isolated API + workers for measuring, on a database that is not production.

Two profiles, because two different questions are being asked:

  lab      the database the recorded baseline was measured on, in the shipped
           configuration (contextual retrieval ON, reranker ON). This is where a
           retrieval change has to prove itself before it becomes the default.
  heldout  a drill database for a public corpus, contextual retrieval OFF —
           it calls the generation model once per chunk at index time, and three
           thousand documents of that is hours of GPU that belongs to a user.

Both isolate three things, each because mixing corrupts something: the database
(§3d — eval must never touch real data), the Qdrant collection, and the RQ queue
prefix, so that starting the real system while this runs cannot cross jobs.

    python -m training.common.eval_stack --profile lab --start
    python -m training.common.eval_stack --profile lab --status
    python -m training.common.eval_stack --profile lab --stop
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND = PROJECT_ROOT / "backend"
LOG_DIR = PROJECT_ROOT / "data" / "logs"

PROFILES = {
    "lab": {
        "port": 8100,
        "database": "local_ai_core_lab_20260821",
        "collection": "documents_lab",
        "queue": "local-ai:lab",
        "contextual": True,
        "reranker": True,
    },
    "chunkexp": {
        # A/B for a chunking change, in the shipped configuration. Its own
        # database because the lab one references source files that no longer
        # exist on disk, so nothing there can be re-indexed in place — and
        # because both arms must be built from the same fixtures by the same
        # path, which a fresh database guarantees and a mutated one does not.
        "port": 8300,
        "database": "local_ai_core_chunkexp",
        "collection": "documents_chunkexp",
        "queue": "local-ai:chunkexp",
        "contextual": True,
        "reranker": True,
    },
    "heldout": {
        "port": 8200,
        "database": "local_ai_core_drill_heldout",
        "collection": "documents_drill_heldout",
        "queue": "local-ai:drill",
        "contextual": False,
        "reranker": False,
    },
}


def pid_file(profile: str) -> Path:
    return PROJECT_ROOT / "data" / f"eval_stack_{profile}.pids"


def version_pins(model_versions: list[str] | None) -> dict[str, str]:
    """--model-version ROLE=ID, repeatable -> {MODEL_VERSION_<ROLE>: ID}.

    The pin goes into the stack's env ONLY (never .env, never this shell): a
    candidate is measured on the isolated stack while every other process keeps
    resolving the registry's `active`. An unknown id refuses the API's boot
    naming the variable, which `start` then prints from the log tail.
    """
    pins: dict[str, str] = {}
    for item in model_versions or []:
        role, separator, version = item.partition("=")
        if not separator or not role.strip() or not version.strip():
            raise SystemExit(f"--model-version can dang ROLE=ID (vi du reranker=reranker-d2-v1), nhan duoc {item!r}")
        pins[f"MODEL_VERSION_{role.strip().upper()}"] = version.strip()
    return pins


def stack_env(profile: str, reranker: bool | None, mode: str | None = None,
              contextual: bool | None = None, model_versions: list[str] | None = None) -> dict[str, str]:
    spec = PROFILES[profile]
    sys.path.insert(0, str(BACKEND))
    from app.config.settings import get_settings

    base, _, _ = str(get_settings().database_url).rpartition("/")
    use_reranker = spec["reranker"] if reranker is None else reranker
    return {
        **os.environ,
        "PYTHONUTF8": "1",
        "DATABASE_URL": f"{base}/{spec['database']}",
        "QDRANT_DOCUMENTS_COLLECTION": spec["collection"],
        "RQ_QUEUE_PREFIX": spec["queue"],
        # Settings.logs_path of the stack's API and workers (relative to the repo root):
        # the API writes data/logs/<LOG_DIR>/ATTENTION_model_fallback.txt when a role
        # deviates and DELETES it when nothing does. On production's data/logs a stack
        # started with --model-version reranker=<candidate> whose candidate is rejected
        # would leave a marker the morning check attributes to production, and a clean
        # stack boot would erase the one production earned. The uvicorn stdout logs
        # (eval_<profile>_*.log) stay in data/logs, where the operator reads them.
        "LOG_DIR": f"data/logs/eval_{profile}",
        "RAG_CONTEXTUAL_RETRIEVAL_ENABLED": "true" if (spec["contextual"] if contextual is None else contextual) else "false",
        "RAG_RERANKER_ENABLED": "true" if use_reranker else "false",
        **({"RAG_RETRIEVAL_MODE": mode} if mode else {}),
        **version_pins(model_versions),
    }


def listening(port: int) -> set[str]:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    return {m.group(1) for line in out.splitlines() if f":{port}" in line and "LISTENING" in line
            for m in [re.search(r"(\d+)\s*$", line)] if m}


def healthy(port: int, timeout: float = 240.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(1.0)
    return False


def start(profile: str, reranker: bool | None, mode: str | None = None, contextual: bool | None = None,
          model_versions: list[str] | None = None) -> int:
    spec = PROFILES[profile]
    port = spec["port"]
    if listening(port):
        print(f"Da co tien trinh nghe cong {port}. Chay --stop truoc.")
        return 1
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = stack_env(profile, reranker, mode, contextual, model_versions)
    processes = {}
    api_log = (LOG_DIR / f"eval_{profile}_api.log").open("w", encoding="utf-8")
    processes["api"] = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND), env=env, stdout=api_log, stderr=subprocess.STDOUT)
    for queue in ("ocr", "index"):
        log = (LOG_DIR / f"eval_{profile}_worker_{queue}.log").open("w", encoding="utf-8")
        # Not `rq worker`: that CLI forks per job, Windows has no fork, and it
        # exits without printing anything. eval_worker uses SimpleWorker.
        processes[f"worker-{queue}"] = subprocess.Popen(
            [sys.executable, "-m", "training.common.eval_worker", queue],
            cwd=str(PROJECT_ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    pid_file(profile).write_text(json.dumps({n: p.pid for n, p in processes.items()}), encoding="utf-8")
    if not healthy(port):
        print("API khong len duoc. 20 dong cuoi:")
        print("\n".join((LOG_DIR / f"eval_{profile}_api.log").read_text(encoding="utf-8", errors="replace").splitlines()[-20:]))
        stop(profile)
        return 1
    print(f"[{profile}] san sang tren cong {port} · db={spec['database']} · collection={spec['collection']} · "
          f"queue={spec['queue']} · contextual={'ON' if spec['contextual'] else 'OFF'} · "
          f"reranker={'ON' if (spec['reranker'] if reranker is None else reranker) else 'OFF'} · "
          f"mode={mode or spec.get('mode') or 'theo models.yaml'}")
    pins = version_pins(model_versions)
    if pins:
        print("   phien ban ghim: " + ", ".join(f"{key}={value}" for key, value in pins.items()))
    for name, process in processes.items():
        print(f"   {name:14} pid {process.pid}")
    return 0


def stop(profile: str) -> int:
    pids: list[int] = []
    path = pid_file(profile)
    if path.exists():
        pids += list(json.loads(path.read_text(encoding="utf-8")).values())
        path.unlink()
    pids += [int(p) for p in listening(PROFILES[profile]["port"])]
    for pid in dict.fromkeys(pids):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    print(f"[{profile}] da dung {len(set(pids))} tien trinh" if pids else f"[{profile}] khong co gi de dung")
    return 0


def status(profile: str) -> int:
    port = PROFILES[profile]["port"]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            body = json.load(response)
        print(f"[{profile}] cong {port}: {body.get('status')}")
        for key in ("postgres", "redis", "qdrant", "ollama", "worker_ocr", "worker_index"):
            print(f"   {key:12} {body.get(key)}")
    except Exception as error:
        print(f"[{profile}] khong goi duoc /health tren {port}: {error}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--start", action="store_true")
    group.add_argument("--stop", action="store_true")
    group.add_argument("--status", action="store_true")
    parser.add_argument("--reranker", dest="reranker", action="store_true", default=None)
    parser.add_argument("--no-reranker", dest="reranker", action="store_false")
    # Contextual retrieval calls the generation model once per chunk on index, and
    # that call is not deterministic; switching it off makes a re-index reproducible,
    # which is what an A/B on chunk boundaries needs before the shipped config is run.
    parser.add_argument("--contextual", dest="contextual", action="store_true", default=None)
    parser.add_argument("--no-contextual", dest="contextual", action="store_false")
    parser.add_argument("--mode", choices=["dense", "bm25", "hybrid"], default=None,
                        help="Do mot tang mot: chi vector, chi BM25, hay ca hai. Bo trong = theo models.yaml.")
    parser.add_argument("--model-version", action="append", default=None, metavar="ROLE=ID",
                        help="Ghim mot phien ban trong model_versions.yaml cho RIENG stack nay "
                             "(MODEL_VERSION_<ROLE> trong env cua stack, khong dong vao .env). Lap lai duoc.")
    arguments = parser.parse_args()
    if arguments.start:
        return start(arguments.profile, arguments.reranker, arguments.mode, arguments.contextual, arguments.model_version)
    if arguments.stop:
        return stop(arguments.profile)
    return status(arguments.profile)


if __name__ == "__main__":
    raise SystemExit(main())
