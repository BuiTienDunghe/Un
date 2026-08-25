"""Nightly eval of the SHIPPED retrieval configuration, on the lab corpus.

D4-lite #4. CI deliberately measures only the bare path (reranker and
contextual retrieval pinned off, ci.yml:264-289), so nothing unattended
watches the configuration production actually runs. The reranker truncation
bug lived four days precisely in that blind spot: quality dropped on the
shipped config while every green light stayed green.

This script is what a Scheduled Task runs at night:

  1. start a second API on port 8100 pointed at the LAB database and the
     ``documents_lab`` collection (the §3d rule: never measure production —
     its twin documents pollute rankings, and eval must not touch real data);
  2. run the multidoc eval retrieval-only against it, gated on the recorded
     baseline (which since T16 also refuses a tokenizer mismatch);
  3. tear the API down, append the outcome to data/logs/nightly_eval.log,
     and on any failure leave data/logs/ATTENTION_nightly_eval.txt behind.

Retrieval-only on purpose: zero generation calls (invariant #7 — background
work must not queue behind a user on the single Ollama), but embeddings, BM25,
RRF and the cross-encoder all run exactly as shipped.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND = PROJECT_ROOT / "backend"
PYTHON = Path(sys.executable)
LAB_DB = "local_ai_core_lab_20260821"
LAB_COLLECTION = "documents_lab"
LAB_PORT = 8100
LOG = PROJECT_ROOT / "data" / "logs" / "nightly_eval.log"
ATTENTION = PROJECT_ROOT / "data" / "logs" / "ATTENTION_nightly_eval.txt"


def lab_database_url() -> str:
    from app.config.settings import get_settings

    url = str(get_settings().database_url)
    # Same server, same credentials, lab database. The name is swapped rather
    # than kept in a second env var so the two URLs cannot drift apart.
    base, _, _ = url.rpartition("/")
    return f"{base}/{LAB_DB}"


def wait_for_health(port: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(1.0)
    return False


def main() -> int:
    started = datetime.now(UTC).isoformat()
    # EVERY exit goes through finish(): the review found two paths (an
    # exception before the try, a subprocess timeout inside it) that previously
    # crashed straight out — no log line, no ATTENTION file — making "the eval
    # did not run" indistinguishable from "the eval passed" at 09:30.
    try:
        return _run(started)
    except Exception:
        import traceback

        return finish(started, returncode=98, output=traceback.format_exc())


def _run(started: str) -> int:
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "DATABASE_URL": lab_database_url(),
        "QDRANT_DOCUMENTS_COLLECTION": LAB_COLLECTION,
    }
    api = subprocess.Popen(
        [str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(LAB_PORT)],
        cwd=str(BACKEND), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        # Health only answers after lifespan finished, which includes the
        # reranker warmup — so healthy means the shipped config really loaded.
        healthy = wait_for_health(LAB_PORT, timeout_seconds=180)
        # Reproduced by the review: with the port already occupied, OUR uvicorn
        # dies on bind ([Errno 10048], sent to DEVNULL) while whoever holds the
        # port answers /health — and the eval would silently measure a foreign
        # server (possibly production, whose twin documents fail the gate, or
        # pass it against the wrong corpus). Healthy is only meaningful while
        # our own process is alive to be the thing that answered.
        if api.poll() is not None:
            return finish(started, returncode=96, output=f"lab API exited with {api.returncode} before serving — port {LAB_PORT} already in use? Refusing to eval whatever answered /health.")
        if not healthy:
            return finish(started, returncode=97, output="lab API never became healthy (Ollama or Docker down?)")
        try:
            eval_run = subprocess.run(
                [
                    str(PYTHON), "-m", "scripts.evaluate_rag",
                    "--multidoc-dataset", str(PROJECT_ROOT / "data" / "evaluation" / "rag_multidoc_eval.jsonl"),
                    "--retrieval-only",
                    "--base-url", f"http://127.0.0.1:{LAB_PORT}",
                    "--baseline", str(PROJECT_ROOT / "data" / "evaluation" / "rag_multidoc_baseline.json"),
                ],
                cwd=str(BACKEND), env=env, capture_output=True, text=True, encoding="utf-8", timeout=1800,
            )
        except subprocess.TimeoutExpired as expired:
            partial = (expired.stdout or b"").decode("utf-8", "replace") if isinstance(expired.stdout, bytes) else (expired.stdout or "")
            return finish(started, returncode=95, output="eval exceeded 1800 s and was killed.\n" + partial)
        return finish(started, returncode=eval_run.returncode, output=(eval_run.stdout or "") + (eval_run.stderr or ""))
    finally:
        api.terminate()
        try:
            api.wait(timeout=15)
        except subprocess.TimeoutExpired:
            api.kill()


def finish(started: str, returncode: int, output: str) -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    tail = "\n".join(output.strip().splitlines()[-12:])
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"started": started, "finished": datetime.now(UTC).isoformat(), "exit": returncode}) + "\n")
        handle.write(tail + "\n" + "-" * 60 + "\n")
    if returncode != 0:
        # A file on disk survives the console window; the morning alert task
        # and a human both find it in data/logs.
        ATTENTION.write_text(
            f"Nightly eval FAILED (exit {returncode}) at {started}.\n\n{tail}\n", encoding="utf-8"
        )
    elif ATTENTION.exists():
        ATTENTION.unlink()
    print(tail)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
