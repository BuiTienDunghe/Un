"""Recreate one embedding version's memory vectors from the PostgreSQL `memories` table.

The twin of rebuild_qdrant for the memories collection: the same shell pin
(MODEL_VERSION_EMBEDDING=<id>, unset = the registry's `active`) chooses the
version, and the memories collection is derived from that same pointer. Every
row of `memories` — web memories and the Discord-mirrored `mem_dc_...` rows
alike — is embedded as a passage and upserted under its stable point id, so a
full pass overwrites in place and --missing-only adds only the rows whose point
the collection lacks. No Postgres write of any kind.

    set MODEL_VERSION_EMBEDDING=embedding-e5l-v1
    python -m scripts.rebuild_memories [--missing-only] [--dry-run]

points_after == memories_rows is the completeness signal the startup probe
checks (status `incomplete` otherwise).
"""
from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select

from app.config.model_registry import QdrantUnreachable
from app.config.settings import get_settings
from app.llm_clients.ollama_client import OllamaClient
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Memory
from app.services.model_router import ModelRouter
from app.stores.qdrant_store import QdrantStore


def _count(value: int | QdrantUnreachable) -> int | None:
    # QDRANT_UNREACHABLE is "could not decide"; the JSON summary says null, never 0.
    return None if isinstance(value, QdrantUnreachable) else int(value)


def rebuild(sessions, router: ModelRouter, qdrant: QdrantStore, *, embedding_version: str | None, collection: str,
            dry_run: bool = False, missing_only: bool = False) -> dict[str, object]:
    """One pass over the memories table; returns the summary main() prints."""
    with sessions() as session:
        rows = [(row.id, row.content, row.memory_type, float(row.importance))
                for row in session.scalars(select(Memory).order_by(Memory.created_at, Memory.id))]
    todo = rows
    skipped = embedded = 0
    if missing_only:
        ids = [qdrant.memory_point_id(memory_id) for memory_id, *_ in rows]
        present = qdrant.existing_point_ids(ids, collection=collection)
        todo = [row for row, point_id in zip(rows, ids, strict=True) if point_id not in present]
        skipped = len(rows) - len(todo)
    if not dry_run:
        for memory_id, content, memory_type, importance in todo:
            # Passage side, like every MemoryService write path (search is the query side).
            vector, _ = router.embed(content, side="passage")
            qdrant.upsert_memory(memory_id, content, memory_type, importance, vector)
            embedded += 1
    return {
        "embedding_version": embedding_version,
        "collection": collection,
        "memories_rows": len(rows),
        "embedded": embedded,
        "skipped_existing": skipped,
        "points_after": _count(qdrant.point_count(collection)),
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="count what would be embedded; write nothing")
    parser.add_argument("--missing-only", action="store_true", help="embed only memories whose point is absent from the collection")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    # Same reasoning as rebuild_qdrant: an absent target collection is what this
    # run creates; a width contradiction still degrades the role and refuses.
    resolved = settings.resolve_models(allow_missing_collections=True)
    refusal = resolved.embedding_refusal()
    if refusal is not None:
        print(f"Refusing to rebuild: {refusal} (see /models.registry)", file=sys.stderr)
        return 1
    collections = settings.qdrant_collections()
    sessions = create_session_factory(create_postgres_engine(settings.database_url))
    router = ModelRouter(
        {"ollama": OllamaClient(settings.ollama_base_url, settings.ollama_chat_timeout_seconds, settings.ollama_health_timeout_seconds, settings.ollama_retry_count)},
        settings.load_models(), embedding_refusal=refusal,
    )
    qdrant = QdrantStore(settings.qdrant_url, settings.qdrant_timeout_seconds, collections.memories, collections.documents,
                         documents_sweep=collections.all_documents, memories_sweep=collections.all_memories)
    summary = rebuild(sessions, router, qdrant, embedding_version=resolved.embedding_version_id(), collection=collections.memories,
                      dry_run=args.dry_run, missing_only=args.missing_only)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
