"""Recreate one embedding version's document vectors from PostgreSQL chunks; PostgreSQL remains truth.

Which version: the shell pin MODEL_VERSION_EMBEDDING=<id> (unset = the registry's
`active`). The target collection is derived from that same pointer, so the
vectors land in the collection the version searches and nowhere else
(model_versions.yaml, roles.embedding). Promotion AND demotion run this first:

    set MODEL_VERSION_EMBEDDING=embedding-e5l-v1
    python -m scripts.rebuild_qdrant [--missing-only] [--confirm]
    python -m scripts.rebuild_memories [--missing-only]

then compare points_after with active_chunks (printed below) and move `active`.

--missing-only embeds only the chunks whose point is absent from the collection
(an inactive collection is frozen at the moment it was last built, so this is
how a demoted version catches up). --confirm is required to re-embed into a
collection that already holds points without --missing-only: a full pass over
a built collection is hours of GPU that should be a decision, not a typo.

This script NEVER writes document_versions.embedding_model. That column means
"the version whose vectors were produced at activation" and is written only by
activate(); a rebuild into a candidate's collection would otherwise stamp every
serving row with a version production does not serve.
"""
from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select

from app.config.model_registry import ProductionProbes, QdrantUnreachable
from app.config.settings import get_settings
from app.llm_clients.ollama_client import OllamaClient
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk
from app.services.model_router import ModelRouter
from app.stores.qdrant_store import QdrantStore
from app.utils.chunking import ChunkLocation, DocumentChunk as ChunkRecord, combined_retrieval_text


class RebuildRefused(RuntimeError):
    """The run must not start: the message names why and what to do instead."""


def _as_record(chunk: DocumentChunk) -> ChunkRecord:
    """ORM row -> the chunking dataclass QdrantStore.upsert_chunks expects.

    Only payload metadata travels to Qdrant (retrieval re-reads content from
    PostgreSQL), so the mapping mirrors what the live index path sends."""
    locations = tuple(ChunkLocation(loc.get("page"), int(loc.get("start", 0)), int(loc.get("end", 0))) for loc in (chunk.locations or []))
    # T15: the dataclass carries heading parts as a tuple; QdrantStore joins
    # them into the display string when building the payload.
    heading = tuple(chunk.heading_path) if chunk.heading_path else None
    return ChunkRecord(chunk.content, chunk.page_start, chunk.page_end, locations, heading, chunk.section_title, chunk.block_type or "paragraph", chunk.extraction_method or "native", chunk.retrieval_context, token_count=chunk.token_count)


def _count(value: int | QdrantUnreachable) -> int | None:
    # QDRANT_UNREACHABLE is "could not decide"; the JSON summary says null, never 0.
    return None if isinstance(value, QdrantUnreachable) else int(value)


def rebuild(sessions, router: ModelRouter, qdrant: QdrantStore, *, embedding_version: str | None, collection: str,
            active_chunks: int | None, document_id: str | None = None, dry_run: bool = False,
            missing_only: bool = False, confirm: bool = False) -> dict[str, object]:
    """One pass over the active chunks; returns the summary main() prints.

    `points_after == active_chunks` is the completeness signal the startup probe
    checks (status `incomplete` otherwise), so both numbers are printed side by side.
    """
    points_before = qdrant.point_count(collection)
    if isinstance(points_before, QdrantUnreachable):
        raise RebuildRefused(f"Qdrant did not answer for collection {collection}; nothing was rebuilt")
    if points_before > 0 and not missing_only and not dry_run and not confirm:
        raise RebuildRefused(
            f"collection {collection} already holds {points_before} points: pass --missing-only to add the absent "
            f"chunks, or --confirm to re-embed every active chunk into it"
        )
    with sessions() as session:
        statement = select(Document).where(Document.status == "indexed", Document.active_version_id.is_not(None))
        if document_id:
            statement = statement.where(Document.id == document_id)
        documents = list(session.scalars(statement))
        work = [
            (doc.id, str(doc.active_version_id), doc.original_filename,
             list(session.scalars(select(DocumentChunk).where(DocumentChunk.version_id == doc.active_version_id).order_by(DocumentChunk.chunk_index))))
            for doc in documents
        ]
    total = embedded = skipped = 0
    for doc_id, version_id, filename, chunks in work:
        if not chunks:
            continue
        total += len(chunks)
        positions = list(range(len(chunks)))
        if missing_only:
            # The point id is the chunk's POSITION in its version (the live path's
            # uuid5); ask the collection which positions it already holds.
            ids = [qdrant.chunk_point_id(doc_id, version_id, index) for index in positions]
            present = qdrant.existing_point_ids(ids)
            positions = [index for index, point_id in enumerate(ids) if point_id not in present]
            skipped += len(chunks) - len(positions)
        if not positions or dry_run:
            continue
        selected = [chunks[index] for index in positions]
        # Same input as the live index path (P4-2): context+content, never bare
        # content, or a rebuild would silently downgrade a contextual index.
        vectors = [router.embed(combined_retrieval_text(chunk.retrieval_context, chunk.content), side="passage")[0] for chunk in selected]
        # replace=False keeps the points --missing-only skipped; chunk_indices keeps
        # the partial list's point ids at their true positions.
        qdrant.upsert_chunks(doc_id, version_id, filename, [_as_record(chunk) for chunk in selected], vectors,
                             chunk_ids=[chunk.id for chunk in selected], replace=not missing_only,
                             chunk_indices=positions if missing_only else None)
        embedded += len(selected)
    return {
        "embedding_version": embedding_version,
        "collection": collection,
        "documents": len(work),
        "chunks": total,
        "embedded": embedded,
        "skipped_existing": skipped,
        "points_after": _count(qdrant.point_count(collection)),
        "active_chunks": active_chunks,
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="count what would be embedded; write nothing")
    parser.add_argument("--document-id", help="rebuild one document only")
    parser.add_argument("--missing-only", action="store_true", help="embed only chunks whose point is absent from the collection")
    parser.add_argument("--confirm", action="store_true", help="re-embed into a collection that already holds points")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    # allow_missing_collections: the target pair may not exist yet (that is what a
    # rebuild creates) and completeness is what this run establishes; a width
    # contradiction still marks the role degraded, and then nothing may be written.
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
    # The same predicate the startup probe compares the collection against.
    counts = ProductionProbes(settings).postgres_counts()
    try:
        summary = rebuild(
            sessions, router, qdrant, embedding_version=resolved.embedding_version_id(), collection=collections.documents,
            active_chunks=counts.active_chunks if counts is not None else None, document_id=args.document_id,
            dry_run=args.dry_run, missing_only=args.missing_only, confirm=args.confirm,
        )
    except RebuildRefused as error:
        print(f"Refusing to rebuild: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
