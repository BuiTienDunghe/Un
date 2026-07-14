"""One-time, non-destructive migration from data/uploads to data/documents.

Run from the project root after stopping FastAPI:
    .venv\Scripts\python.exe backend\scripts\migrate_document_storage.py

It moves only files represented in SQLite's documents table. It also removes the
legacy `content` key from every document point in Qdrant; chunk text remains in
SQLite and retrieval resolves it there.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.config.settings import get_settings
from app.stores.qdrant_store import QdrantStore
from app.stores.sqlite_store import SQLiteStore


def migrate() -> tuple[int, bool]:
    settings = get_settings()
    store = SQLiteStore(settings.database_path)
    store.initialize()
    moved = 0
    old_uploads = settings.documents_path.parent / "uploads"
    for document in store.list_documents_for_storage_migration():
        source = old_uploads / str(document["stored_filename"])
        suffix = Path(str(document["stored_filename"])).suffix
        target = settings.documents_path / str(document["id"]) / f"original{suffix}"
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
            moved += 1
    qdrant = QdrantStore(settings.qdrant_url, settings.qdrant_timeout_seconds)
    payload_cleaned = qdrant.delete_legacy_document_content()
    return moved, payload_cleaned


if __name__ == "__main__":
    moved_count, cleaned = migrate()
    print(f"Moved {moved_count} document file(s). Qdrant legacy content removed: {cleaned}.")
