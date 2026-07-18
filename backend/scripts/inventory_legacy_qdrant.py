"""Read-only Phase-8 inventory of legacy Qdrant points.

This tool deliberately classifies unknown points as DO_NOT_DELETE.  It never
upserts, deletes, or mutates Qdrant/PostgreSQL.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentVersion
from app.stores.qdrant_store import QdrantStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    sessions = create_session_factory(create_postgres_engine(str(settings.database_url)))
    qdrant = QdrantStore(settings.qdrant_url, settings.qdrant_timeout_seconds)
    points, _ = qdrant.client.scroll(qdrant.collection_name, limit=10_000, with_payload=True, with_vectors=False)
    versioned: dict[tuple[str, str, int], object] = {}
    legacy = []
    for point in points:
        payload = dict(point.payload or {})
        if payload.get("version_id"):
            try:
                versioned[(str(payload.get("document_id")), str(payload["version_id"]), int(payload.get("chunk_index", -1)))] = point.id
            except (TypeError, ValueError):
                pass
        elif "index_version" in payload:
            legacy.append((point.id, payload))
    rows = []
    with sessions() as session:
        for point_id, payload in legacy:
            document_id = str(payload.get("document_id") or "")
            index_version = payload.get("index_version")
            chunk_index = payload.get("chunk_index")
            document = session.get(Document, document_id) if document_id else None
            version = None
            if document is not None and isinstance(index_version, int):
                version = session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document_id, DocumentVersion.version_number == index_version))
            chunk = None
            if version is not None and isinstance(chunk_index, int):
                chunk = session.scalar(select(DocumentChunk).where(DocumentChunk.version_id == version.id, DocumentChunk.chunk_index == chunk_index))
            replacement = versioned.get((document_id, version.id, int(chunk_index))) if version is not None and isinstance(chunk_index, int) else None
            content_hash = payload.get("content_hash")
            hash_matches = bool(chunk is not None and (not content_hash or str(content_hash) == str(chunk.content_hash)))
            classification = "VERIFIED_REPLACED" if replacement and hash_matches else ("LEGACY_ONLY_KNOWN" if document is not None else "UNKNOWN_DO_NOT_DELETE")
            rows.append({"point_id": str(point_id), "document_id": document_id or None, "index_version": index_version, "chunk_index": chunk_index, "content_hash": content_hash, "postgres_document": document is not None, "postgres_version_id": version.id if version else None, "postgres_chunk_id": chunk.id if chunk else None, "versioned_replacement_point_id": str(replacement) if replacement else None, "classification": classification})
    payload = {"read_only": True, "legacy_count": len(rows), "versioned_count": len(versioned), "points": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"legacy_count": len(rows), "versioned_count": len(versioned), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
