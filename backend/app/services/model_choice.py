"""The model version picked on the web UI's Model screen, for this machine only.

A plain MODEL_VERSION_<ROLE>=<id> file that run-local-ai-core.bat loads into its own window,
which makes the pick an ordinary shell pin. Evals and tests never start through that launcher,
so they keep grading the registry's `active`, and the tracked model_versions.yaml never changes.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.config.model_registry import PROJECT_ROOT

CHOICE_PATH = PROJECT_ROOT / "data" / "model_choice.env"
_PREFIX = "MODEL_VERSION_"


def read_choices(path: Path) -> dict[str, str]:
    """{role: version id}; empty when nothing was ever picked."""
    if not path.exists():
        return {}
    choices: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key.startswith(_PREFIX) and value:
            choices[key[len(_PREFIX):].lower()] = value
    return choices


def save_choice(path: Path, role: str, version_id: str | None) -> None:
    """Pick `version_id` for `role`, or drop the pick when None. Written whole, then swapped in,
    so the launcher can never read half a file."""
    choices = read_choices(path)
    if version_id is None:
        choices.pop(role, None)
    else:
        choices[role] = version_id
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes("".join(f"{_PREFIX}{key.upper()}={value}\r\n" for key, value in choices.items()).encode("ascii"))
    os.replace(temporary, path)
