"""One-time, non-destructive migration from data/uploads to data/documents.

Run from the project root after stopping FastAPI:
    .venv\Scripts\python.exe backend\scripts\migrate_document_storage.py

It is an explicit legacy migration utility, not runtime code. It moves only
files represented in the archived SQLite documents table.
"""
from __future__ import annotations

import sys
import hashlib
import sqlite3
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.config.settings import get_settings
from app.stores.qdrant_store import QdrantStore


def migrate(database_path: Path) -> tuple[int, int]:
    settings = get_settings()
    database_path = database_path.resolve()
    if not database_path.exists():
        raise FileNotFoundError(f"legacy SQLite source not found: {database_path}")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    moved = 0
    old_uploads = settings.documents_path.parent / "uploads"
    for document in connection.execute("SELECT id, stored_filename FROM documents").fetchall():
        source = old_uploads / str(document["stored_filename"])
        suffix = Path(str(document["stored_filename"])).suffix
        target = settings.documents_path / str(document["id"]) / f"original{suffix}"
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
            moved += 1
        if target.is_file():
            connection.execute("UPDATE documents SET content_hash = ? WHERE id = ?", (hashlib.sha256(target.read_bytes()).hexdigest(), str(document["id"])))
    connection.commit()
    connection.close()
    qdrant = QdrantStore(settings.qdrant_url, settings.qdrant_timeout_seconds)
    migrated_vectors = qdrant.migrate_legacy_document_points()
    return moved, migrated_vectors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True, help="Explicit retired SQLite archive path; never a runtime database")
    args = parser.parse_args()
    moved_count, vectors = migrate(args.source)
    print(f"Moved {moved_count} document file(s). Migrated {vectors} legacy Qdrant vector(s).")
