"""check_operational_alerts and the model registry's ATTENTION marker (invariant #6).

Run as the Scheduled Task runs it (a subprocess from backend/), with LOG_DIR
pointed at a temporary directory: the marker's presence must show up in the JSON
payload and, with --fail-on-alert, as exit 2 — the popup the morning task shows.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.config.model_registry import ATTENTION_FILENAME

BACKEND = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not os.getenv("POSTGRES_TEST_URL"), reason="set POSTGRES_TEST_URL: the script opens the database")


def run_check(logs: Path) -> tuple[int, dict]:
    env = {**os.environ, "LOG_DIR": str(logs), "PYTHONUTF8": "1"}
    # The other alerts are switched off so only the marker decides the exit code.
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.check_operational_alerts", "--fail-on-alert", "--dump-max-age-hours", "0",
         "--chunk-warn", "0", "--uncondensed-warn", "0"],
        cwd=str(BACKEND), env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    assert lines, completed.stdout + completed.stderr
    return completed.returncode, json.loads(lines[-1])


def test_the_marker_is_an_alert_and_its_absence_is_not(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    code, payload = run_check(logs)
    assert payload["model_fallback_alert"] is False
    assert payload["nightly_eval_alert"] is False
    if code == 2:
        # Only a pre-existing condition of the shared test database may fire here.
        assert payload["stale_jobs"] or payload["condensation_alert"], payload

    (logs / ATTENTION_FILENAME).write_text("reranker: requested=x loaded=reranker-v0 status=fallback\n", encoding="utf-8")
    code, payload = run_check(logs)
    assert payload["model_fallback_alert"] is True
    assert code == 2, "the marker alone must produce the popup exit code"
