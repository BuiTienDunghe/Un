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

When the lab API fails to start, the failure line now carries evidence rather
than a guess: `ollama ps`, `docker compose ps`, and the tail of the lab
uvicorn's own output (data/logs/nightly_eval_lab_api.log). Three nights in
September died at that step and left nothing to distinguish "the machine was
off" from "something broke" — see docs/FAILURE_MODES.md.

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
# The lab uvicorn used to write to DEVNULL, so exit 97 could only ever guess at
# a cause. Overwritten each run: the interesting copy is the one from the run
# that just failed.
LAB_API_LOG = PROJECT_ROOT / "data" / "logs" / "nightly_eval_lab_api.log"


def diagnose() -> str:
    """Evidence for why the lab API did not come up, gathered after the fact.

    Exit 97 printed "Ollama or Docker down?" — a question, not a finding, and
    the three September failures left nothing behind to answer it. These three
    sources do, and none of them costs a model call (invariant #7): what Ollama
    is serving, what Docker is running, and what uvicorn itself said before it
    gave up.
    """
    parts: list[str] = []
    for label, command in (("ollama ps", ["ollama", "ps"]), ("docker compose ps", ["docker", "compose", "ps"])):
        try:
            probe = subprocess.run(command, cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            body = (probe.stdout or "").strip() or "(no output)"
            if (probe.stderr or "").strip():
                body += "\n" + probe.stderr.strip()
            parts.append(f"--- {label} (exit {probe.returncode}) ---\n{body}")
        except Exception as error:
            # A missing binary IS the diagnosis, so record it rather than raise.
            parts.append(f"--- {label} ---\n{type(error).__name__}: {error}")
    try:
        lines = LAB_API_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        parts.append("--- lab uvicorn, last 15 lines ---\n" + ("\n".join(lines[-15:]) or "(empty)"))
    except Exception as error:
        parts.append(f"--- lab uvicorn ---\ncould not read {LAB_API_LOG.name}: {error}")
    return "\n".join(parts)


def stop_api(api: subprocess.Popen) -> None:
    """Terminate the lab API, idempotently — the failure paths stop it early so
    its log file is complete before `diagnose()` reads it."""
    if api.poll() is None:
        api.terminate()
    try:
        api.wait(timeout=15)
    except subprocess.TimeoutExpired:
        api.kill()


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
    LAB_API_LOG.parent.mkdir(parents=True, exist_ok=True)
    api_log = LAB_API_LOG.open("w", encoding="utf-8")
    api = subprocess.Popen(
        [str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(LAB_PORT)],
        cwd=str(BACKEND), env=env,
        stdout=api_log, stderr=subprocess.STDOUT,
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
            stop_api(api)
            return finish(started, returncode=96, output=f"lab API exited with {api.returncode} before serving — port {LAB_PORT} already in use? Refusing to eval whatever answered /health.\n" + diagnose())
        if not healthy:
            # Stop it first: the uvicorn log is only complete once its writer
            # is gone, and the tail is the half of the diagnosis that says
            # whether this was a powered-down machine or a real regression.
            stop_api(api)
            return finish(started, returncode=97, output=f"lab API did not answer /health on port {LAB_PORT} within 180 s.\n" + diagnose())
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
        stop_api(api)
        api_log.close()


def finish(started: str, returncode: int, output: str) -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # 12 lines fitted a Python traceback and nothing else; a startup diagnosis
    # is three command outputs plus a log tail, and truncating it to 12 threw
    # away the two that say whether Docker was even running.
    tail = "\n".join(output.strip().splitlines()[-40:])
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
