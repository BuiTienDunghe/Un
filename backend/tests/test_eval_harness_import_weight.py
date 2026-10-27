"""Importing an eval harness loads none of the server's auth stack (ticket 02).

api_key_headers left scripts/evaluate_rag.py. Its first new home, beside the server's
key check in app/security/api_key.py, pulled FastAPI, JWT and the ORM models into every
harness import: 0.81 s against 0.22 s (27/10/2026). Only a fresh interpreter can see
that — this suite has imported all of them long before any test runs.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
HEAVY = ("fastapi", "jwt", "sqlalchemy", "app.security.auth")


def test_importing_evaluate_rag_loads_neither_fastapi_nor_the_auth_layer():
    probe = f"import sys, scripts.evaluate_rag; print(sorted(m for m in {HEAVY!r} if m in sys.modules))"
    result = subprocess.run([sys.executable, "-c", probe], cwd=BACKEND, capture_output=True, text=True, timeout=120)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
