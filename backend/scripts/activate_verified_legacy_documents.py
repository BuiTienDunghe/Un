"""Explicit Phase-5C activation of validated legacy document versions only."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from qdrant_client import QdrantClient
from sqlalchemy import select

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import DocumentChunk, DocumentVersion, IngestionRun
from app.postgres.repositories import PostgresDocumentRepository
from scripts.migrate_sqlite_documents_to_postgres import open_readonly, target_point_id, version_id


def verified_runs(source: Path, sessions, qdrant_url: str) -> list[str]:
    client = QdrantClient(qdrant_url, timeout=30)
    selected: list[str] = []
    with open_readonly(source) as sqlite, sessions() as session:
        rows = sqlite.execute("SELECT * FROM document_ingestion_runs WHERE status='indexed' AND stage='indexed' ORDER BY document_id,index_version").fetchall()
        for row in rows:
            doc_id, number = str(row["document_id"]), int(row["index_version"])
            target_version = version_id(doc_id, number)
            run = session.get(IngestionRun, str(row["id"])); version = session.get(DocumentVersion, target_version)
            if not run or not version or run.version_id != target_version or version.status != "staging":
                raise RuntimeError(f"unverified run/version: {row['id']}")
            chunks = list(session.scalars(select(DocumentChunk).where(DocumentChunk.version_id == target_version).order_by(DocumentChunk.chunk_index)))
            if len(chunks) != int(row["chunks_count"]):
                raise RuntimeError(f"chunk count mismatch: {doc_id}")
            for chunk in chunks:
                points = client.retrieve("documents", [target_point_id(doc_id, target_version, chunk.chunk_index)], with_payload=True, with_vectors=False)
                if len(points) != 1:
                    raise RuntimeError(f"missing versioned Qdrant point: {doc_id}:{chunk.chunk_index}")
                payload = points[0].payload or {}
                if payload.get("document_id") != doc_id or payload.get("version_id") != target_version or payload.get("chunk_id") != chunk.id or payload.get("content_hash") != chunk.content_hash:
                    raise RuntimeError(f"Qdrant payload mismatch: {doc_id}:{chunk.chunk_index}")
            selected.append(str(row["id"]))
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--source", type=Path, required=True, help="Explicit primary SQLite archive path used only for audited recovery verification"); parser.add_argument("--allow-activation", action="store_true")
    args = parser.parse_args()
    if not args.allow_activation:
        parser.error("--allow-activation is required")
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    sessions = create_session_factory(create_postgres_engine(settings.database_url))
    runs = verified_runs(args.source, sessions, settings.qdrant_url)
    for run_id in runs:
        with sessions.begin() as session:
            PostgresDocumentRepository(session).activate_verified_legacy_migration(run_id)
    print({"activated_runs": runs})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
