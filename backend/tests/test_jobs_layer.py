"""app.jobs sits below the layers that use it (ticket 05, M1d).

The job vocabulary — job types, queue routes, retry policy — used to live in app.services,
so the data layer imported from the business layer to use it
(postgres/discord_memory_job_repository.py). It moved to app.jobs, whose rule is one line:
the standard library and sqlalchemy, nothing else. Read off the source, lazy imports
inside functions included, so nothing has to be importable for the check to run.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
ALLOWED = set(sys.stdlib_module_names) | {"sqlalchemy", "app"}


def imported_modules(package: Path) -> dict[str, set[str]]:
    """{file: every absolute module name it imports}; relative imports stay in the package."""
    found: dict[str, set[str]] = {}
    for path in sorted(package.rglob("*.py")):
        names: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module)
        found[path.relative_to(APP).as_posix()] = names
    return found


def test_app_jobs_imports_only_the_standard_library_and_sqlalchemy():
    modules = imported_modules(APP / "jobs")
    assert modules, "app/jobs has no modules to check"
    for path, names in modules.items():
        outside = sorted(name for name in names if name.split(".")[0] not in ALLOWED)
        upward = sorted(name for name in names if name.startswith("app.") and not name.startswith("app.jobs"))
        assert not outside, f"{path} imports {outside}"
        assert not upward, f"{path} imports {upward}: app.jobs must stay below services, postgres and workers"


def test_the_data_layer_no_longer_imports_the_business_layer():
    for path, names in imported_modules(APP / "postgres").items():
        assert not [name for name in names if name.startswith("app.services")], f"{path} imports app.services"
