"""Phase 5B document-only SQLite -> PostgreSQL preparation tool.

This tool deliberately prepares verified document metadata without changing the
document runtime selector or activating a PostgreSQL version.  SQLite is always
opened read-only; Qdrant writes are allowed only to a separately named
validation collection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentVersion, IngestionRun


PRIMARY_SOURCE = (ROOT / "data" / "sqlite" / "local_ai_core.db").resolve()
DOMAINS = ("documents", "versions", "runs", "chunks")


class MigrationError(RuntimeError):
    pass


@dataclass
class DomainReport:
    domain: str
    source_rows: int = 0
    read: int = 0
    inserted: int = 0
    updated: int = 0
    existing_identical: int = 0
    skipped: int = 0
    mismatch: int = 0
    failed: int = 0
    policy_controlled: int = 0
    errors: list[str] = field(default_factory=list)


def _source_uri(path: Path) -> str:
    normalized = str(path.resolve()).replace("\\", "/")
    return f"file:{quote(normalized)}?mode=ro"


def open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise MigrationError(f"SQLite source does not exist: {path}")
    connection = sqlite3.connect(_source_uri(path), uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def validate_cli_source(path: Path) -> Path:
    resolved = path.resolve()
    archive_manifest = resolved.parent / "manifest.json"
    archived_primary = resolved.name == "local_ai_core.db" and resolved.parent.name.startswith("sqlite-retired-") and archive_manifest.is_file()
    if (resolved != PRIMARY_SOURCE and not archived_primary) or "pre_postgres_" in resolved.name or "test" in resolved.name.lower():
        raise MigrationError("--source must be the audited primary source or an explicit sqlite-retired archive primary with manifest.json")
    return resolved


def _timestamp(value: object | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed).astimezone(UTC)


def _time_equal(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    return left.astimezone(UTC) == right.astimezone(UTC)


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _rows(connection: sqlite3.Connection, domain: str, document_id: str | None = None) -> list[sqlite3.Row]:
    table = {"documents": "documents", "runs": "document_ingestion_runs", "chunks": "document_chunk_versions"}.get(domain)
    if domain == "versions":
        table = "document_ingestion_runs"
    if not table or table not in _tables(connection):
        return []
    where, values = ("", ()) if document_id is None else (" WHERE document_id = ?" if table != "documents" else " WHERE id = ?", (document_id,))
    order = "id" if table == "documents" else "document_id, index_version, chunk_index" if table == "document_chunk_versions" else "document_id, index_version"
    return list(connection.execute(f'SELECT * FROM "{table}"{where} ORDER BY {order}', values))


def _locations(value: object | None) -> list[dict[str, object]]:
    if not value:
        return []
    parsed = json.loads(str(value))
    if not isinstance(parsed, list) or any(not isinstance(item, dict) for item in parsed):
        raise ValueError("locations_json must be an array of objects")
    return parsed


def _heading_path(value: object | None) -> list[str]:
    if value is None or str(value) == "":
        return []
    raw = str(value)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [raw]
    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        return parsed
    if isinstance(parsed, str):
        return [parsed]
    raise ValueError("heading_path must be a string or JSON string array")


def version_id(document_id: str, index_version: int) -> str:
    return f"ver_{document_id}_{index_version}"


def legacy_point_id(document_id: str, index_version: int, chunk_index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"local-ai-core:{document_id}:{index_version}:{chunk_index}"))


def target_point_id(document_id: str, target_version_id: str, chunk_index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"local-ai-core:{document_id}:{target_version_id}:{chunk_index}"))


def _reports(source: Path, document_id_filter: str | None = None) -> dict[str, DomainReport]:
    with open_readonly(source) as connection:
        docs = _rows(connection, "documents", document_id_filter)
        runs = _rows(connection, "runs", document_id_filter)
        return {
            "documents": DomainReport("documents", source_rows=len(docs)),
            "versions": DomainReport("versions", source_rows=len(runs)),
            "runs": DomainReport("runs", source_rows=len(runs)),
            "chunks": DomainReport("chunks", source_rows=len(_rows(connection, "chunks", document_id_filter))),
        }


def _document_compare(source: sqlite3.Row, target: Document) -> tuple[bool, bool, list[str]]:
    """Return equal, policy-controlled, mismatched fields.

    An indexed legacy record paired with an uploaded/staging PostgreSQL record
    is explicitly a Phase-5B preparation state, not permission to activate it.
    A null legacy source hash also cannot decide against a non-null target hash.
    """
    mismatches: list[str] = []
    for name, left, right in (
        ("original_filename", str(source["original_filename"]), target.original_filename),
        ("stored_filename", str(source["stored_filename"]), target.stored_filename),
        ("mime_type", source["content_type"], target.mime_type),
        ("source_available", bool(source["source_available"]), bool(target.source_available)),
        ("pinned", bool(source["pinned"]), bool(target.pinned)),
        ("retention_policy", str(source["retention_policy"]), target.retention_policy),
    ):
        if left != right:
            mismatches.append(name)
    if source["content_hash"] is not None and str(source["content_hash"]) != target.content_hash:
        mismatches.append("content_hash")
    # Source-removal and last-access timestamps are mutable lifecycle metadata.
    # SQLite remains authoritative until Phase 5C, so apply() reconciles them
    # below rather than treating their expected drift as a content conflict.
    policy = source["content_hash"] is None
    source_status, target_status = str(source["status"]), target.status
    prepared = source_status == "indexed" and target_status == "uploaded" and target.active_version_id is None
    if source_status != target_status and not prepared:
        mismatches.append("status")
    return not mismatches, policy or prepared, mismatches


def _run_compare(source: sqlite3.Row, target: IngestionRun, target_version_id: str) -> list[str]:
    expected = {
        "document_id": str(source["document_id"]), "version_id": target_version_id,
        "status": str(source["status"]), "current_stage": str(source["stage"]),
        "total_pages": int(source["total_pages"]), "processed_pages": int(source["processed_pages"]),
        "total_chunks": int(source["chunks_count"]), "embedded_chunks": int(source["vectors_count"]),
        "cancel_requested": bool(source["cancel_requested"]), "error_code": source["error_code"], "error_message": source["error_message"],
    }
    return [name for name, value in expected.items() if getattr(target, name) != value]


def _chunk_compare(source: sqlite3.Row, target: DocumentChunk, target_version_id: str) -> list[str]:
    expected_locations, expected_heading = _locations(source["locations_json"]), _heading_path(source["heading_path"])
    fields = {
        "document_id": str(source["document_id"]), "version_id": target_version_id,
        "chunk_index": int(source["chunk_index"]), "content": str(source["content"]),
        "content_hash": str(source["content_hash"]), "page_start": source["page_start"], "page_end": source["page_end"],
        "locations": expected_locations, "heading_path": expected_heading, "section_title": source["section_title"],
        "block_type": str(source["block_type"]), "extraction_method": str(source["extraction_method"]),
    }
    return [name for name, value in fields.items() if getattr(target, name) != value]


def _apply_document(session: Session, row: sqlite3.Row, report: DomainReport) -> None:
    report.read += 1
    target = session.get(Document, str(row["id"]))
    if target is None:
        target = Document(id=str(row["id"]), original_filename=str(row["original_filename"]), stored_filename=str(row["stored_filename"]), mime_type=row["content_type"], content_hash=str(row["content_hash"]) if row["content_hash"] is not None else None, status="uploaded", source_available=bool(row["source_available"]), source_removed_at=_timestamp(row["source_removed_at"]), pinned=bool(row["pinned"]), retention_policy=str(row["retention_policy"]), created_at=_timestamp(row["created_at"]), updated_at=_timestamp(row["updated_at"]), last_accessed_at=_timestamp(row["last_accessed_at"]))
        session.add(target); report.inserted += 1; report.policy_controlled += int(row["content_hash"] is None); return
    equal, policy, mismatch = _document_compare(row, target)
    if mismatch:
        report.mismatch += 1; report.errors.append(f"document_mismatch:{row['id']}:{','.join(mismatch)}"); return
    # Backfill only non-activation metadata. Never change status/active version.
    changed = False
    for name, value in (("content_hash", str(row["content_hash"]) if row["content_hash"] is not None else None), ("source_removed_at", _timestamp(row["source_removed_at"])), ("last_accessed_at", _timestamp(row["last_accessed_at"])), ("created_at", _timestamp(row["created_at"])), ("updated_at", _timestamp(row["updated_at"]))):
        if getattr(target, name) != value:
            setattr(target, name, value); changed = True
    report.updated += int(changed); report.existing_identical += int(not changed)
    report.policy_controlled += int(policy)


def _verified_legacy_activation(session: Session, row: sqlite3.Row, version: DocumentVersion) -> bool:
    """Return true only for the narrowly permitted Phase-5C active state.

    Phase 5B intentionally rejects activation.  Once the separately audited
    activation transaction has promoted a legacy indexed run, an idempotent
    final-delta verification must recognise that exact state without allowing
    arbitrary active versions to pass migration verification.
    """
    if str(row["status"]) != "indexed" or str(row["stage"]) != "indexed" or version.status != "active":
        return False
    document = session.get(Document, version.document_id)
    run = session.get(IngestionRun, str(row["id"]))
    return bool(
        document
        and document.status == "indexed"
        and document.active_version_id == version.id
        and run
        and run.document_id == version.document_id
        and run.version_id == version.id
        and run.status == "indexed"
        and run.current_stage == "indexed"
        and not run.cancel_requested
        and session.scalar(select(DocumentChunk.id).where(DocumentChunk.version_id == version.id).limit(1))
    )


def _apply_version(session: Session, row: sqlite3.Row, report: DomainReport, *, allow_activated_legacy: bool = False) -> None:
    report.read += 1
    doc_id, number, target_id = str(row["document_id"]), int(row["index_version"]), version_id(str(row["document_id"]), int(row["index_version"]))
    target = session.get(DocumentVersion, target_id)
    if target is None:
        # A deterministic ID is permitted only when the convention is verified
        # against existing records for this document/version.
        conflict = session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc_id, DocumentVersion.version_number == number))
        if conflict:
            report.mismatch += 1; report.errors.append(f"version_id_convention_mismatch:{doc_id}:{number}"); return
        session.add(DocumentVersion(id=target_id, document_id=doc_id, version_number=number, status="staging", chunking_config={}, created_at=_timestamp(row["created_at"]))); report.inserted += 1; return
    if target.document_id != doc_id or target.version_number != number:
        report.mismatch += 1; report.errors.append(f"version_mismatch:{target_id}"); return
    if target.status == "active" and not (allow_activated_legacy and _verified_legacy_activation(session, row, target)):
        report.mismatch += 1; report.errors.append(f"unexpected_active_version:{target_id}"); return
    report.existing_identical += 1


def _apply_run(session: Session, row: sqlite3.Row, report: DomainReport) -> None:
    report.read += 1
    target_id = version_id(str(row["document_id"]), int(row["index_version"]))
    target = session.get(IngestionRun, str(row["id"]))
    if target is None:
        if not session.get(DocumentVersion, target_id):
            report.failed += 1; report.errors.append(f"missing_version_for_run:{row['id']}"); return
        target = IngestionRun(id=str(row["id"]), document_id=str(row["document_id"]), version_id=target_id, status=str(row["status"]), current_stage=str(row["stage"]), total_pages=int(row["total_pages"]), processed_pages=int(row["processed_pages"]), total_chunks=int(row["chunks_count"]), embedded_chunks=int(row["vectors_count"]), cancel_requested=bool(row["cancel_requested"]), error_code=row["error_code"], error_message=row["error_message"], started_at=_timestamp(row["created_at"]), completed_at=_timestamp(row["completed_at"]))
        session.add(target); report.inserted += 1; return
    mismatch = _run_compare(row, target, target_id)
    if mismatch:
        # Fields can be backfilled only if the identity mapping agrees; never
        # regress a completed run to processing.
        identity = {"document_id", "version_id"}
        if identity.intersection(mismatch) or (target.current_stage == "completed" and str(row["stage"]) not in {"completed", "indexed"}):
            report.mismatch += 1; report.errors.append(f"run_mismatch:{row['id']}:{','.join(mismatch)}"); return
        for name, value in (("status", str(row["status"])), ("current_stage", str(row["stage"])), ("total_pages", int(row["total_pages"])), ("processed_pages", int(row["processed_pages"])), ("total_chunks", int(row["chunks_count"])), ("embedded_chunks", int(row["vectors_count"])), ("cancel_requested", bool(row["cancel_requested"])), ("error_code", row["error_code"]), ("error_message", row["error_message"]), ("started_at", _timestamp(row["created_at"])), ("completed_at", _timestamp(row["completed_at"]))):
            setattr(target, name, value)
        report.updated += 1
    else:
        report.existing_identical += 1


def _apply_chunk(session: Session, row: sqlite3.Row, report: DomainReport) -> None:
    report.read += 1
    doc_id, target_id, index = str(row["document_id"]), version_id(str(row["document_id"]), int(row["index_version"])), int(row["chunk_index"])
    target = session.scalar(select(DocumentChunk).where(DocumentChunk.document_id == doc_id, DocumentChunk.version_id == target_id, DocumentChunk.chunk_index == index))
    locations, heading = _locations(row["locations_json"]), _heading_path(row["heading_path"])
    if target is None:
        uid = str(uuid5(NAMESPACE_URL, f"local-ai-core:{doc_id}:{target_id}:{index}"))
        session.add(DocumentChunk(chunk_uid=uid, document_id=doc_id, version_id=target_id, chunk_index=index, content=str(row["content"]), content_hash=str(row["content_hash"]), page_start=row["page_start"], page_end=row["page_end"], locations=locations, heading_path=heading, section_title=row["section_title"], block_type=str(row["block_type"]), extraction_method=str(row["extraction_method"]), status="staging", created_at=_timestamp(row["created_at"]))); report.inserted += 1; return
    mismatch = _chunk_compare(row, target, target_id)
    hard = {"document_id", "version_id", "chunk_index", "content", "content_hash"}
    if hard.intersection(mismatch):
        report.mismatch += 1; report.errors.append(f"chunk_mismatch:{doc_id}:{index}:{','.join(mismatch)}"); return
    if mismatch:
        target.page_start, target.page_end = row["page_start"], row["page_end"]
        target.locations, target.heading_path = locations, heading
        target.section_title, target.block_type, target.extraction_method = row["section_title"], str(row["block_type"]), str(row["extraction_method"])
        target.created_at = _timestamp(row["created_at"])
        report.updated += 1
    else:
        report.existing_identical += 1


def migrate(source: Path, sessions: sessionmaker, *, document_id_filter: str | None = None, batch_size: int = 100, dry_run: bool = False, allow_activated_legacy: bool = False) -> dict[str, DomainReport]:
    if batch_size <= 0:
        raise MigrationError("--batch-size must be positive")
    reports = _reports(source, document_id_filter)
    if dry_run:
        return reports
    with open_readonly(source) as connection:
        for domain, apply in (("documents", _apply_document), ("versions", _apply_version), ("runs", _apply_run), ("chunks", _apply_chunk)):
            rows = _rows(connection, domain, document_id_filter)
            report = reports[domain]
            for start in range(0, len(rows), batch_size):
                batch = rows[start:start + batch_size]
                before = (report.inserted, report.updated, report.existing_identical)
                try:
                    with sessions.begin() as session:
                        for row in batch:
                            if domain == "versions":
                                apply(session, row, report, allow_activated_legacy=allow_activated_legacy)
                            else:
                                apply(session, row, report)
                        if report.failed or report.mismatch:
                            raise MigrationError(f"{domain} batch cannot be reconciled")
                except Exception as error:
                    report.inserted, report.updated, report.existing_identical = before
                    report.failed += len(batch)
                    report.errors.append(f"batch_{start // batch_size + 1}_rolled_back:{type(error).__name__}")
                    break
    verification = verify(source, sessions, document_id_filter=document_id_filter, allow_activated_legacy=allow_activated_legacy)
    for name, details in verification.items():
        reports[name].mismatch = max(reports[name].mismatch, int(details["mismatch"]))
    return reports


def verify(source: Path, sessions: sessionmaker, *, document_id_filter: str | None = None, allow_activated_legacy: bool = False) -> dict[str, dict[str, object]]:
    result = {name: {"source_rows": 0, "target_rows": 0, "mismatch": 0, "policy_controlled": 0, "valid": True, "errors": []} for name in DOMAINS}
    with open_readonly(source) as connection, sessions() as session:
        for row in _rows(connection, "documents", document_id_filter):
            item = result["documents"]; item["source_rows"] += 1
            target = session.get(Document, str(row["id"]))
            if target is None:
                item["mismatch"] += 1; item["errors"].append(f"missing_document:{row['id']}"); continue
            item["target_rows"] += 1; equal, policy, mismatch = _document_compare(row, target)
            item["policy_controlled"] += int(policy)
            if mismatch:
                item["mismatch"] += 1; item["errors"].append(f"document_mismatch:{row['id']}:{','.join(mismatch)}")
            active_version = session.get(DocumentVersion, target.active_version_id) if target.active_version_id else None
            run = session.get(IngestionRun, str(row["active_ingestion_run_id"])) if row["active_ingestion_run_id"] else None
            activated_matches = bool(
                allow_activated_legacy
                and str(row["status"]) == "indexed"
                and active_version
                and active_version.document_id == target.id
                and active_version.status == "active"
                and run
                and run.version_id == active_version.id
                and run.status == "indexed"
                and run.current_stage == "indexed"
            )
            if target.active_version_id is not None and not activated_matches:
                item["mismatch"] += 1; item["errors"].append(f"activation_not_allowed:{row['id']}")
        for row in _rows(connection, "versions", document_id_filter):
            item = result["versions"]; item["source_rows"] += 1
            target = session.get(DocumentVersion, version_id(str(row["document_id"]), int(row["index_version"])))
            if not target:
                item["mismatch"] += 1; item["errors"].append(f"missing_version:{row['document_id']}:{row['index_version']}"); continue
            item["target_rows"] += 1
            active_allowed = allow_activated_legacy and _verified_legacy_activation(session, row, target)
            if target.document_id != row["document_id"] or target.version_number != row["index_version"] or (target.status == "active" and not active_allowed):
                item["mismatch"] += 1; item["errors"].append(f"version_mismatch:{target.id}")
        for row in _rows(connection, "runs", document_id_filter):
            item = result["runs"]; item["source_rows"] += 1
            target = session.get(IngestionRun, str(row["id"]))
            if not target:
                item["mismatch"] += 1; item["errors"].append(f"missing_run:{row['id']}"); continue
            item["target_rows"] += 1; mismatch = _run_compare(row, target, version_id(str(row["document_id"]), int(row["index_version"])))
            if mismatch:
                item["mismatch"] += 1; item["errors"].append(f"run_mismatch:{row['id']}:{','.join(mismatch)}")
        for row in _rows(connection, "chunks", document_id_filter):
            item = result["chunks"]; item["source_rows"] += 1
            target = session.scalar(select(DocumentChunk).where(DocumentChunk.document_id == str(row["document_id"]), DocumentChunk.version_id == version_id(str(row["document_id"]), int(row["index_version"])), DocumentChunk.chunk_index == int(row["chunk_index"])))
            if not target:
                item["mismatch"] += 1; item["errors"].append(f"missing_chunk:{row['document_id']}:{row['chunk_index']}"); continue
            item["target_rows"] += 1; mismatch = _chunk_compare(row, target, version_id(str(row["document_id"]), int(row["index_version"])))
            if mismatch:
                item["mismatch"] += 1; item["errors"].append(f"chunk_mismatch:{row['document_id']}:{row['chunk_index']}:{','.join(mismatch)}")
    for item in result.values():
        item["valid"] = item["mismatch"] == 0
    return result


def qdrant_mapping(source: Path, sessions: sessionmaker, *, mode: str, validation_collection: str, qdrant_url: str, document_id_filter: str | None = None) -> dict[str, object]:
    if mode == "none":
        return {"mode": mode, "mapped": 0, "valid": True, "mappings": []}
    client = QdrantClient(url=qdrant_url, timeout=10)
    if not client.collection_exists("documents"):
        raise MigrationError("Qdrant documents collection is unavailable")
    with open_readonly(source) as connection, sessions() as session:
        mappings: list[dict[str, object]] = []
        for row in _rows(connection, "chunks", document_id_filter):
            doc_id, number, index = str(row["document_id"]), int(row["index_version"]), int(row["chunk_index"])
            document = session.get(Document, doc_id); target_version = version_id(doc_id, number)
            chunk = session.scalar(select(DocumentChunk).where(DocumentChunk.document_id == doc_id, DocumentChunk.version_id == target_version, DocumentChunk.chunk_index == index))
            if not document or not chunk or str(row["content_hash"]) != chunk.content_hash:
                raise MigrationError(f"unverified_chunk_mapping:{doc_id}:{number}:{index}")
            old_id = legacy_point_id(doc_id, number, index)
            records, _ = client.retrieve("documents", [old_id], with_payload=True, with_vectors=True), None
            if len(records) != 1:
                raise MigrationError(f"missing_legacy_qdrant_point:{doc_id}:{number}:{index}")
            record = records[0]; payload = dict(record.payload or {})
            if payload.get("document_id") != doc_id or payload.get("index_version") != number or int(payload.get("chunk_index", -1)) != index:
                raise MigrationError(f"legacy_qdrant_payload_mismatch:{doc_id}:{number}:{index}")
            mappings.append({"legacy_point_id": old_id, "target_point_id": target_point_id(doc_id, target_version, index), "document_id": doc_id, "version_id": target_version, "chunk_id": chunk.id, "chunk_index": index, "content_hash": chunk.content_hash, "vector": record.vector, "payload": {**payload, "version_id": target_version, "chunk_id": chunk.id, "content_hash": chunk.content_hash, "locations": chunk.locations or [], "heading_path": chunk.heading_path or []}})
    if mode in {"validation-upsert", "production-upsert"}:
        collection = "documents" if mode == "production-upsert" else validation_collection
        if mode == "validation-upsert" and collection == "documents":
            raise MigrationError("validation Qdrant collection must not be the production documents collection")
        source_info = client.get_collection("documents")
        if not client.collection_exists(collection):
            client.create_collection(collection, vectors_config=source_info.config.params.vectors)
        points = [PointStruct(id=item["target_point_id"], vector=item.pop("vector"), payload={key: value for key, value in item["payload"].items() if key != "index_version"}) for item in mappings]
        if points:
            # Upsert is deterministic by target UUID5. It never selects or
            # deletes legacy point IDs, so a retry cannot create a duplicate.
            client.upsert(collection, points=points, wait=True)
    for item in mappings:
        item.pop("vector", None); item.pop("payload", None)
    return {"mode": mode, "mapped": len(mappings), "valid": True, "target_collection": ("documents" if mode == "production-upsert" else validation_collection if mode == "validation-upsert" else None), "mappings": mappings}


def _parse_mode(value: str) -> str:
    if value not in {"none", "validate", "validation-upsert", "production-upsert"}:
        raise MigrationError("--qdrant-mode must be none, validate, validation-upsert, or production-upsert")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 5B document SQLite-to-PostgreSQL preparation")
    parser.add_argument("--source", type=Path, default=PRIMARY_SOURCE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--resume", action="store_true", help="accepted for idempotent re-runs")
    parser.add_argument("--document-id")
    parser.add_argument("--qdrant-mode", default="none")
    parser.add_argument("--qdrant-validation-collection", default="documents_phase5b_validation")
    parser.add_argument("--allow-production-qdrant", action="store_true", help="required with production-upsert; legacy points are retained")
    parser.add_argument("--allow-activated-legacy", action="store_true", help="Phase 5C only: verify the narrowly defined post-activation legacy state")
    arguments = parser.parse_args()
    if sum(bool(item) for item in (arguments.dry_run, arguments.apply, arguments.verify_only)) != 1:
        parser.error("choose exactly one of --dry-run, --apply, or --verify-only")
    try:
        source = validate_cli_source(arguments.source); mode = _parse_mode(arguments.qdrant_mode)
        if mode == "production-upsert" and not arguments.allow_production_qdrant:
            raise MigrationError("production-upsert requires --allow-production-qdrant")
        if arguments.dry_run:
            payload: dict[str, object] = {name: asdict(value) for name, value in _reports(source, arguments.document_id).items()}
        else:
            settings = get_settings()
            if not settings.database_url:
                raise MigrationError("DATABASE_URL is required for apply/verify")
            sessions = create_session_factory(create_postgres_engine(settings.database_url))
            payload = verify(source, sessions, document_id_filter=arguments.document_id, allow_activated_legacy=arguments.allow_activated_legacy) if arguments.verify_only else {name: asdict(value) for name, value in migrate(source, sessions, document_id_filter=arguments.document_id, batch_size=arguments.batch_size, allow_activated_legacy=arguments.allow_activated_legacy).items()}
            if mode != "none":
                payload["qdrant"] = qdrant_mapping(source, sessions, mode=mode, validation_collection=arguments.qdrant_validation_collection, qdrant_url=settings.qdrant_url, document_id_filter=arguments.document_id)
        print(json.dumps({"source": str(source), "resume": arguments.resume, "report": payload}, ensure_ascii=False, indent=2, default=str))
        invalid = any(not item.get("valid", True) for item in payload.values() if isinstance(item, dict) and "valid" in item)
        failed = any(int(item.get("failed", 0)) > 0 or int(item.get("mismatch", 0)) > 0 for item in payload.values() if isinstance(item, dict))
        return 1 if invalid or failed else 0
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
