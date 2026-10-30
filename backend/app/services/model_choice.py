"""The model version picked on the web UI's Model screen, for this machine only.

A plain MODEL_VERSION_<ROLE>=<id> file that run-local-ai-core.bat loads into its own window,
which makes the pick an ordinary shell pin. Evals and tests never start through that launcher,
so they keep grading the registry's `active`, and the tracked model_versions.yaml never changes.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from app.config.model_registry import PROJECT_ROOT

CHOICE_PATH = PROJECT_ROOT / "data" / "model_choice.env"
_PREFIX = "MODEL_VERSION_"
# tools/supervisor.py starts the API again at once on this code, reading the file afresh.
RESTART_EXIT_CODE = 75
SUPERVISED_ENV = "LOCAL_AI_SUPERVISED"


def restart_to_apply() -> bool:
    """Under the supervisor: leave in a moment, after the reply is out, and come back on the pick.
    Started any other way nothing would bring the API back, so it keeps running on the old model."""
    if os.environ.get(SUPERVISED_ENV) != "1":
        return False
    threading.Timer(1.0, os._exit, (RESTART_EXIT_CODE,)).start()
    return True


def read_choices(path: Path) -> dict[str, str]:
    """{role: version id}, with "" for a role put back on its default; a role never picked
    is absent."""
    if not path.exists():
        return {}
    choices: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key.startswith(_PREFIX):
            choices[key[len(_PREFIX):].lower()] = value
    return choices


def save_choice(path: Path, role: str, version_id: str | None) -> None:
    """Pick `version_id` for `role`; None writes an empty value, which the launcher's `set`
    turns into clearing any pin the window inherited. Written whole, then swapped in, so the
    launcher can never read half a file."""
    choices = read_choices(path)
    choices[role] = version_id or ""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes("".join(f"{_PREFIX}{key.upper()}={value}\r\n" for key, value in choices.items()).encode("ascii"))
    os.replace(temporary, path)
