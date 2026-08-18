"""Guards for the packaging contract (P0-5).

Deliberately does not `import app`: this suite runs from the repository root
where `app` is only importable via the editable install, and the guard must
hold whether or not that install is present.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _declared_version() -> str:
    text = (ROOT / "backend" / "app" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    assert match, "backend/app/__init__.py must declare __version__"
    return match.group(1)


def test_every_mapped_package_directory_exists():
    mapping = PYPROJECT["tool"]["setuptools"]["package-dir"]

    # The repo has two import roots; a mapping that points at nothing turns
    # `pip install -e .` into a package that imports as an empty namespace.
    assert set(PYPROJECT["tool"]["setuptools"]["packages"]) == set(mapping)
    for package, location in mapping.items():
        assert (ROOT / location).is_dir(), f"{package} maps to missing {location}"


def test_dependencies_still_come_from_requirements_txt():
    dynamic = PYPROJECT["tool"]["setuptools"]["dynamic"]

    # CI and run-local-ai-core.bat both install from requirements.txt; moving
    # the dependency list into pyproject would silently split the two.
    assert dynamic["dependencies"]["file"] == ["requirements.txt"]
    assert (ROOT / "requirements.txt").is_file()
    assert "dependencies" in PYPROJECT["project"]["dynamic"]


def test_the_version_has_exactly_one_home():
    assert PYPROJECT["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "app.__version__"}
    assert "version" in PYPROJECT["project"]["dynamic"]
    assert "version" not in PYPROJECT["project"]


def test_the_changelog_documents_the_current_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    releases = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)

    # A release whose version is not in the changelog is a release nobody can
    # tell apart from the one before it.
    assert releases, "CHANGELOG.md must contain at least one released version"
    assert releases[0] == _declared_version()


def test_the_distribution_is_never_publishable():
    # `app` and `tools` are far too generic to claim on a public index.
    assert "Private :: Do Not Upload" in PYPROJECT["project"]["classifiers"]
    assert PYPROJECT["project"]["requires-python"] == ">=3.11"
