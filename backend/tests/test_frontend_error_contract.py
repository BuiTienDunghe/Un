"""Exercise API error handling in Node with a stub DOM and no HTTP requests."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
TESTS = Path(__file__).resolve().parent
FRONTEND = TESTS.parent / "app/frontend"


@pytest.mark.skipif(NODE is None, reason="needs node to exercise browser-independent error handling")
@pytest.mark.parametrize("scenario", ["provider", "index_receipt", "retry_rendering"])
def test_error_contract_with_fake_fetch_and_dom(scenario):
    completed = subprocess.run([NODE, str(TESTS / "frontend_error_probe.cjs"), str(FRONTEND), scenario],
                               check=False, capture_output=True, text=True, encoding="utf-8")
    assert completed.returncode == 0, completed.stdout + completed.stderr
