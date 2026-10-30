"""The door and the model process (ticket 38), with a stand-in for the model."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from tools.decided_server import ModelProcess, ModelUnavailable


def fake_model(tmp_path: Path, body: str) -> list[str]:
    path = tmp_path / "model.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, "-u", str(path)]


ECHO = """
    import json, sys
    for line in sys.stdin:
        print(json.dumps({"label": "ignore", "text": json.loads(line)["text"]}), flush=True)
"""


def test_starts_on_first_use_and_keeps_answering(tmp_path: Path) -> None:
    model = ModelProcess(fake_model(tmp_path, ECHO))
    assert not model.loaded
    assert model.classify("một")["text"] == "một"
    first = model._child.pid
    assert model.classify("hai")["text"] == "hai"
    assert model._child.pid == first
    model._stop()


def test_leaves_when_idle_and_comes_back(tmp_path: Path) -> None:
    model = ModelProcess(fake_model(tmp_path, ECHO), idle_seconds=0.1)
    model.classify("một")
    child = model._child
    time.sleep(0.2)
    model.stop_if_idle()
    assert not model.loaded
    assert child.poll() is not None
    assert model.classify("hai")["text"] == "hai"
    model._stop()


def test_not_idle_stays(tmp_path: Path) -> None:
    model = ModelProcess(fake_model(tmp_path, ECHO), idle_seconds=60)
    model.classify("một")
    assert not model.stop_if_idle() and model.loaded
    model._stop()


def test_a_model_that_cannot_start_is_unavailable_then_retried(tmp_path: Path) -> None:
    model = ModelProcess(fake_model(tmp_path, "import sys; sys.exit(3)"))
    with pytest.raises(ModelUnavailable):
        model.classify("một")
    assert not model.loaded
    with pytest.raises(ModelUnavailable):
        model.classify("hai")


def test_a_hung_model_is_killed_at_the_deadline(tmp_path: Path) -> None:
    model = ModelProcess(fake_model(tmp_path, "import time; time.sleep(60)"), reply_timeout=0.5)
    began = time.monotonic()
    child_seen = []
    with pytest.raises(ModelUnavailable):
        original = model._start

        def spy() -> None:
            original()
            child_seen.append(model._child)

        model._start = spy
        model.classify("một")
    assert time.monotonic() - began < 30
    assert child_seen[0].poll() is not None


def test_a_reply_saying_error_passes_through_for_the_door_to_refuse(tmp_path: Path) -> None:
    body = """
        import json, sys
        for line in sys.stdin:
            print(json.dumps({"error": "ValueError"}), flush=True)
    """
    model = ModelProcess(fake_model(tmp_path, body))
    assert model.classify("một") == {"error": "ValueError"}
    assert model.loaded
    model._stop()


def test_the_door_imports_no_model_library() -> None:
    code = "import sys, tools.decided_server; print([m for m in ('torch', 'transformers', 'peft') if m in sys.modules])"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
    assert done.stdout.strip() == "[]", done.stderr
