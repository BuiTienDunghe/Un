"""Phase 9A read-only audit for legacy Qdrant document points.

This command is deliberately fail-closed.  It creates a collection snapshot
before reading production points, verifies the only authoritative SQLite
archive against its manifest, and uses no Qdrant/PostgreSQL mutation API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import or_, select

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentVersion, Job, OutboxEvent
from app.stores.qdrant_store import QdrantStore


class AuditError(RuntimeError):
    pass


def deterministic_legacy_point_id(document_id: str, index_version: int, chunk_index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"local-ai-core:{document_id}:{index_version}:{chunk_index}"))


def deterministic_versioned_point_id(document_id: str, version_id: str, chunk_index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"local-ai-core:{document_id}:{version_id}:{chunk_index}"))


def vector_dimensions(vector: object) -> int | None:
    if isinstance(vector, list):
        return len(vector)
    if isinstance(vector, dict):
        dimensions = {len(value) for value in vector.values() if isinstance(value, list)}
        return dimensions.pop() if len(dimensions) == 1 else None
    return None


def vector_fingerprint(vector: object) -> str | None:
    if vector is None:
        return None
    return hashlib.sha256(json.dumps(vector, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def citation_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload.get(key) for key in ("page", "page_start", "page_end", "locations", "heading_path", "section_title", "block_type", "extraction_method") if key in payload}


def canonical_citation(chunk: DocumentChunk) -> dict[str, Any]:
    return {
        "page": chunk.page_start,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "locations": list(chunk.locations or []),
        "heading_path": list(chunk.heading_path or []),
        "section_title": chunk.section_title,
        "block_type": chunk.block_type,
        "extraction_method": chunk.extraction_method,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def validate_primary_archive(archive: Path, manifest: Path) -> dict[str, Any]:
    """Verify a primary archive before opening it and reject pre-Postgres DBs."""
    archive, manifest = archive.resolve(), manifest.resolve()
    if archive.name != "local_ai_core.db" or "pre_postgres_" in archive.name:
        raise AuditError("only archived local_ai_core.db is authoritative; pre_postgres archives are forbidden")
    if not archive.is_file() or not manifest.is_file():
        raise AuditError("authoritative archive or manifest is missing")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    record = next((item for item in payload.get("files", []) if Path(str(item.get("archive_path", ""))).name == archive.name), None)
    if not isinstance(record, dict):
        raise AuditError("manifest has no entry for primary archive")
    actual = _sha256(archive)
    if actual != str(record.get("sha256_before", "")).upper() or actual != str(record.get("sha256_after", "")).upper():
        raise AuditError("archive checksum does not match manifest")
    if archive.stat().st_size != int(record.get("size_bytes", -1)):
        raise AuditError("archive size does not match manifest")
    return {"archive": str(archive), "manifest": str(manifest), "sha256": actual, "verified": True, "authoritative": True}


def open_archive_readonly(archive: Path) -> sqlite3.Connection:
    normalized = str(archive.resolve()).replace("\\", "/")
    uri = f"file:{quote(normalized)}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def archive_chunks(archive: Path) -> dict[tuple[str, int, int], dict[str, Any]]:
    result: dict[tuple[str, int, int], dict[str, Any]] = {}
    with open_archive_readonly(archive) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "document_chunk_versions" not in tables:
            return result
        for row in connection.execute('SELECT * FROM "document_chunk_versions" ORDER BY document_id, index_version, chunk_index'):
            item = dict(row)
            result[(str(item["document_id"]), int(item["index_version"]), int(item["chunk_index"]))] = item
    return result


def _scroll_all(client: Any, collection: str) -> list[Any]:
    points, offset = [], None
    while True:
        batch, offset = client.scroll(collection_name=collection, offset=offset, limit=256, with_payload=True, with_vectors=True)
        points.extend(batch)
        if offset is None:
            return points


def create_and_verify_snapshot(client: Any, collection: str) -> dict[str, Any]:
    snapshot = client.create_snapshot(collection_name=collection)
    name = getattr(snapshot, "name", None) or (snapshot.get("name") if isinstance(snapshot, dict) else None)
    if not name:
        raise AuditError("Qdrant returned a snapshot without a name")
    snapshots = client.list_snapshots(collection_name=collection)
    names = {getattr(item, "name", None) or (item.get("name") if isinstance(item, dict) else None) for item in snapshots}
    if name not in names:
        raise AuditError("new Qdrant snapshot could not be verified")
    return {"collection": collection, "name": str(name), "verified": True}


def _safe_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _archive_evidence(row: dict[str, Any] | None, point_id: str, document_id: str | None, index_version: int | None, chunk_index: int | None) -> dict[str, Any]:
    if not row:
        return {"authoritative": False, "status": "not_found"}
    deterministic = bool(document_id and index_version is not None and chunk_index is not None and point_id == deterministic_legacy_point_id(document_id, index_version, chunk_index))
    return {"authoritative": True, "status": "matched" if deterministic else "identity_mismatch", "deterministic_legacy_id_matches": deterministic, "content_hash": row.get("content_hash"), "citation": {"page": row.get("page"), "page_start": row.get("page_start"), "page_end": row.get("page_end"), "locations": json.loads(row["locations_json"]) if row.get("locations_json") else [], "heading_path": row.get("heading_path"), "section_title": row.get("section_title"), "block_type": row.get("block_type"), "extraction_method": row.get("extraction_method")}}


def _matches_citation(payload: dict[str, Any], chunk: DocumentChunk) -> bool:
    expected, actual = canonical_citation(chunk), citation_metadata(payload)
    # Legacy payloads historically did not carry every citation field.  Any
    # field it does carry must agree; replacement points must carry all fields.
    return all(actual.get(key) == expected[key] for key in actual)


def _archive_citation_matches(evidence: dict[str, Any], chunk: DocumentChunk) -> bool:
    citation = evidence.get("citation")
    if not isinstance(citation, dict):
        return False
    heading = citation.get("heading_path")
    if isinstance(heading, str):
        try:
            parsed = json.loads(heading)
            heading = parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, str) else None
        except json.JSONDecodeError:
            heading = [heading]
    expected = canonical_citation(chunk)
    return bool(
        heading == expected["heading_path"]
        and citation.get("page") == expected["page"]
        and citation.get("page_start") == expected["page_start"]
        and citation.get("page_end") == expected["page_end"]
        and citation.get("locations") == expected["locations"]
        and citation.get("section_title") == expected["section_title"]
        and citation.get("block_type") == expected["block_type"]
        and citation.get("extraction_method") == expected["extraction_method"]
    )


@dataclass
class PointView:
    point_id: str
    payload: dict[str, Any]
    vector: object
    qdrant_point_version: int | None


def audit_points(points: Iterable[Any], session_factory: Any, archive_rows: dict[tuple[str, int, int], dict[str, Any]]) -> dict[str, Any]:
    views = [PointView(str(point.id), dict(point.payload or {}), getattr(point, "vector", None), getattr(point, "version", None)) for point in points]
    legacy = [item for item in views if not item.payload.get("version_id") and "index_version" in item.payload]
    versioned = [item for item in views if item.payload.get("version_id")]
    candidates: dict[tuple[str, str, int], list[PointView]] = defaultdict(list)
    for item in versioned:
        index = _safe_int(item.payload.get("chunk_index"))
        if isinstance(item.payload.get("document_id"), str) and isinstance(item.payload.get("version_id"), str) and index is not None:
            candidates[(item.payload["document_id"], item.payload["version_id"], index)].append(item)
    logical = Counter((str(item.payload.get("document_id")), item.payload.get("index_version"), item.payload.get("chunk_index")) for item in legacy)
    vector_groups: dict[str, list[str]] = defaultdict(list)
    for item in views:
        fingerprint = vector_fingerprint(item.vector)
        if fingerprint:
            vector_groups[fingerprint].append(item.point_id)

    rows: list[dict[str, Any]] = []
    with session_factory() as session:
        for item in legacy:
            payload = item.payload
            document_id = payload.get("document_id") if isinstance(payload.get("document_id"), str) and payload.get("document_id") else None
            version_number, chunk_index = _safe_int(payload.get("index_version")), _safe_int(payload.get("chunk_index"))
            archive_row = archive_rows.get((document_id, version_number, chunk_index)) if document_id and version_number is not None and chunk_index is not None else None
            archive = _archive_evidence(archive_row, item.point_id, document_id, version_number, chunk_index)
            document = session.get(Document, document_id) if document_id else None
            version = session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document_id, DocumentVersion.version_number == version_number)) if document and version_number is not None else None
            chunk = session.scalar(select(DocumentChunk).where(DocumentChunk.version_id == version.id, DocumentChunk.chunk_index == chunk_index)) if version and chunk_index is not None else None
            replacement_id = deterministic_versioned_point_id(document_id, version.id, chunk_index) if document_id and version and chunk_index is not None else None
            replacement_candidates = candidates.get((document_id, version.id, chunk_index), []) if document_id and version and chunk_index is not None else []
            replacement = replacement_candidates[0] if len(replacement_candidates) == 1 else None
            raw_hash = payload.get("content_hash") if isinstance(payload.get("content_hash"), str) else None
            canonical_hash = chunk.content_hash if chunk else None
            # A supplied payload hash is a hard assertion; archive evidence only fills historical absence.
            hash_evidence = (raw_hash == canonical_hash) if raw_hash else bool(archive.get("deterministic_legacy_id_matches") and archive.get("content_hash") == canonical_hash)
            replacement_ok = bool(replacement and chunk and replacement.point_id == replacement_id and replacement.payload.get("chunk_id") == chunk.id and replacement.payload.get("content_hash") == canonical_hash and replacement.payload.get("document_id") == document_id and replacement.payload.get("version_id") == version.id and _safe_int(replacement.payload.get("chunk_index")) == chunk_index and vector_dimensions(replacement.vector) == vector_dimensions(item.vector) and vector_fingerprint(replacement.vector) == vector_fingerprint(item.vector) and _matches_citation(replacement.payload, chunk))
            legacy_citation_ok = bool(chunk and (not citation_metadata(payload) or _matches_citation(payload, chunk)))
            archive_citation_ok = bool(chunk and archive.get("deterministic_legacy_id_matches") and _archive_citation_matches(archive, chunk))
            citation_evidence_ok = legacy_citation_ok or archive_citation_ok
            active = bool(document and version and document.active_version_id == version.id and version.status == "active")
            pending_reference = bool(document_id and session.scalar(select(Job.id).where(Job.document_id == document_id, Job.status.in_(("queued", "running"))).limit(1))) or bool(document_id and session.scalar(select(OutboxEvent.id).where(or_(OutboxEvent.aggregate_id == document_id, OutboxEvent.payload["document_id"].astext == document_id), OutboxEvent.status.in_(("pending", "processing"))).limit(1)))
            classification, reason, confidence = "UNKNOWN_DO_NOT_DELETE", "insufficient authoritative evidence", "low"
            if document and version and chunk and hash_evidence and citation_evidence_ok and replacement_ok and len(replacement_candidates) == 1:
                classification, reason, confidence = "VERIFIED_REPLACED", "archive/PG identity, replacement payload, citation and vector all match", "high"
            elif document and version and chunk and hash_evidence and citation_evidence_ok and version.status != "active":
                classification, reason, confidence = "STALE_VERSION_VERIFIED", "canonical PostgreSQL chunk belongs to verified non-active version", "high"
            elif (chunk and hash_evidence) or (archive.get("deterministic_legacy_id_matches") and archive.get("content_hash")):
                classification, reason, confidence = "LEGACY_CHUNK_RECOVERABLE", "authoritative chunk evidence exists but no fully verified production replacement", "medium"
            elif document:
                classification, reason, confidence = "LEGACY_DOCUMENT_KNOWN", "PostgreSQL document exists but chunk/version evidence is incomplete", "medium"
            logical_key = (str(payload.get("document_id")), payload.get("index_version"), payload.get("chunk_index"))
            duplicate_logical = logical[logical_key] > 1
            eligible = bool(classification == "VERIFIED_REPLACED" and active and not pending_reference and len(replacement_candidates) == 1 and not duplicate_logical)
            gaps = []
            if not document_id: gaps.append("missing_document_id")
            if version_number is None: gaps.append("missing_or_invalid_index_version")
            if chunk_index is None: gaps.append("missing_or_invalid_chunk_index")
            if not raw_hash and not archive.get("deterministic_legacy_id_matches"): gaps.append("payload_missing_content_hash")
            if not archive.get("deterministic_legacy_id_matches"): gaps.append("no_authoritative_archive_identity")
            if len(replacement_candidates) != 1: gaps.append("replacement_missing_or_ambiguous")
            if pending_reference: gaps.append("active_job_or_outbox_reference")
            if duplicate_logical: gaps.append("duplicate_legacy_logical_tuple")
            rows.append({
                "legacy_point_id": item.point_id, "document_id": document_id, "index_version": version_number, "chunk_index": chunk_index,
                "content_hash": raw_hash, "canonical_content_hash": canonical_hash, "vector_dimensions": vector_dimensions(item.vector),
                "vector_fingerprint": vector_fingerprint(item.vector), "qdrant_point_version": item.qdrant_point_version, "payload_metadata": payload, "payload_anomalies": ["missing_content_hash"] if not raw_hash else [], "postgres_document_id": document.id if document else None,
                "postgres_version_id": version.id if version else None, "postgres_chunk_id": chunk.id if chunk else None,
                "replacement_point_id": replacement.point_id if replacement_ok and replacement else None, "expected_replacement_point_id": replacement_id,
                "source_evidence": {"status": "not_reparsed_in_phase9a", "source_available": bool(document.source_available) if document else False},
                "archive_evidence": archive, "classification": classification, "eligible_for_future_delete": eligible,
                "confidence": confidence, "reason": reason, "blocking_gaps": gaps,
                "replacement_candidate_ids": [candidate.point_id for candidate in replacement_candidates], "postgres_active_version": active,
            })
    return {
        "total_points": len(views), "legacy_points": len(legacy), "versioned_points": len(versioned),
        "points_missing_document_id": sum(not item.payload.get("document_id") for item in views),
        "points_missing_chunk_index": sum(_safe_int(item.payload.get("chunk_index")) is None for item in views),
        "points_missing_content_hash": sum(not item.payload.get("content_hash") for item in views),
        "duplicate_logical_tuples": [{"tuple": list(key), "point_ids": [item.point_id for item in legacy if (str(item.payload.get("document_id")), item.payload.get("index_version"), item.payload.get("chunk_index")) == key]} for key, count in logical.items() if count > 1],
        "duplicate_vectors": [ids for ids in vector_groups.values() if len(ids) > 1], "points": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 9A read-only legacy Qdrant mapping")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, help="Phase-8A inventory used only for read-only comparison")
    args = parser.parse_args()
    try:
        evidence = validate_primary_archive(args.archive, args.manifest)
        settings = get_settings()
        if not str(settings.database_url).startswith("postgresql+"):
            raise AuditError("Phase 9A requires PostgreSQL-only runtime configuration")
        sessions = create_session_factory(create_postgres_engine(str(settings.database_url)))
        qdrant = QdrantStore(settings.qdrant_url, 120)
        if not qdrant.client.collection_exists(qdrant.collection_name):
            raise AuditError("production Qdrant documents collection is unavailable")
        snapshot = create_and_verify_snapshot(qdrant.client, qdrant.collection_name)
        inventory = audit_points(_scroll_all(qdrant.client, qdrant.collection_name), sessions, archive_chunks(args.archive))
        comparison: dict[str, Any] = {"baseline": None, "changed": False}
        if args.baseline:
            baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
            before_ids = {str(row.get("point_id") or row.get("legacy_point_id")) for row in baseline.get("points", [])}
            after_ids = {str(row["legacy_point_id"]) for row in inventory["points"]}
            comparison = {"baseline": str(args.baseline), "baseline_legacy_points": int(baseline.get("legacy_count", baseline.get("legacy_points", 0))), "baseline_versioned_points": int(baseline.get("versioned_count", baseline.get("versioned_points", 0))), "current_legacy_points": inventory["legacy_points"], "current_versioned_points": inventory["versioned_points"], "added_legacy_point_ids": sorted(after_ids - before_ids), "removed_legacy_point_ids": sorted(before_ids - after_ids), "changed": before_ids != after_ids or int(baseline.get("versioned_count", baseline.get("versioned_points", 0))) != inventory["versioned_points"]}
        payload = {"phase": "9A", "read_only": True, "created_at": datetime.now(UTC).isoformat(), "runtime": {"database": "postgresql-only", "legacy_runtime_query": "ignored by PostgresRetrievalService"}, "snapshot": snapshot, "postgres_recovery_reference": "data/backups/postgres-phase8b/local-ai-20260719-001749.dump", "archive_validation": evidence, "phase8a_comparison": comparison, **inventory}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"snapshot": snapshot["name"], "legacy_points": inventory["legacy_points"], "versioned_points": inventory["versioned_points"], "output": str(args.output)}, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
