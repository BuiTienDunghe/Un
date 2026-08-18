"""Shared helpers for the Alembic migration tests.

Migration tests step the isolated test database backwards so a single revision
can be exercised up, down and up again.  Their teardown must therefore return
the database to the *current* head: pinning a literal revision leaves the test
database one migration behind the moment a new revision lands, and every later
test that touches the new schema fails with a confusing SQL error instead of a
migration error.  The head is resolved from the migration scripts themselves so
the tests keep working without edits when a revision is added.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_DIRECTORY = ROOT / "backend" / "alembic"


def head_revision() -> str:
    """Return the single head revision declared under backend/alembic/versions."""
    config = Config()
    # An absolute script_location keeps this independent of the working
    # directory; alembic.ini stores a path relative to the repository root.
    config.set_main_option("script_location", str(ALEMBIC_DIRECTORY))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"expected exactly one Alembic head, got {heads}"
    return heads[0]
