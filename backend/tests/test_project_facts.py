"""What the docs state about the repo, against the repo: these numbers drifted for days unseen."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = sorted(path.name for path in (ROOT / "backend" / "alembic" / "versions").glob("*.py") if path.name[0].isdigit())


def test_the_docs_name_the_newest_migration():
    head = re.match(r"\d+_\d+", MIGRATIONS[-1]).group()
    for document in ("README.md", "docs/RESULTS.md"):
        assert head in (ROOT / document).read_text(encoding="utf-8"), f"{document} does not name {head}"


def test_the_results_page_counts_the_migrations():
    text = (ROOT / "docs" / "RESULTS.md").read_text(encoding="utf-8")
    assert f"| Schema migrations | {len(MIGRATIONS)}," in text


def test_ci_and_compose_run_the_same_qdrant_and_it_is_pinned():
    compose = re.findall(r"image: (qdrant/qdrant:\S+)", (ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    ci = re.findall(r"image: (qdrant/qdrant:\S+)", (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    assert set(compose) == set(ci) and len(set(compose)) == 1
    assert not compose[0].endswith(":latest")


def test_no_store_is_published_beyond_this_machine():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for port in ("5432", "6333", "6334", "6379"):
        assert f'"127.0.0.1:{port}:{port}"' in text, f"port {port} is open to the network"
