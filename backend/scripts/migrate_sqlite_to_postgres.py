"""Phase 3A auxiliary-domain SQLite → PostgreSQL migration tool.

This tool never discovers backup/test databases.  Its CLI accepts only the
audited primary source; tests call the public functions directly with their own
SQLite fixtures and PostgreSQL test database.
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

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Conversation, Memory, Message, OcrCache, OcrRun, RequestLog

DOMAINS = ("conversations", "messages", "memories", "ocr_runs", "request_logs", "ocr_cache")
PRIMARY_SOURCE = (ROOT / "data" / "sqlite" / "local_ai_core.db").resolve()


class MigrationError(RuntimeError):
    pass


@dataclass
class DomainReport:
    domain: str
    source_rows: int = 0
    read: int = 0
    inserted: int = 0
    skipped: int = 0
    existing_identical: int = 0
    mismatch: int = 0
    failed: int = 0
    orphan_messages: int = 0
    checksum: str | None = None
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
    if resolved != PRIMARY_SOURCE and not archived_primary:
        raise MigrationError("--source must be the audited primary source or an explicit sqlite-retired archive primary with manifest.json")
    if "pre_postgres_" in resolved.name or "test" in resolved.name.lower():
        raise MigrationError("backup or test SQLite sources are not accepted")
    return resolved


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _timestamp(value: object) -> datetime:
    raw = str(value)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    # SQLite contains both naive legacy values and offsets.  PostgreSQL
    # TIMESTAMPTZ normalises to an instant, so verification must do the same.
    return (parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed).astimezone(UTC)


def _checksum(rows: list[sqlite3.Row], fields: tuple[str, ...], json_fields: tuple[str, ...] = ()) -> str:
    digest = hashlib.sha256()
    for row in rows:
        item: dict[str, object] = {}
        for field_name in fields:
            value = row[field_name]
            if field_name in json_fields:
                value = json.loads(str(value))
            elif field_name.endswith("_at"):
                value = _timestamp(value).isoformat()
            item[field_name] = value
        digest.update(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _checksum_values(rows: list[dict[str, object]], fields: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps({field: row[field] for field in fields}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _canonical_source_row(domain: str, row: sqlite3.Row) -> dict[str, object]:
    """Return the business fields which Phase 3B promises to preserve.

    This is deliberately shared by checksum and per-primary-key verification:
    an ``ON CONFLICT DO NOTHING`` result is only idempotent when these values
    are equal, not merely when an ID already exists.
    """
    if domain == "conversations":
        return {"id": str(row["id"]), "created_at": _timestamp(row["created_at"]).isoformat(), "updated_at": _timestamp(row["updated_at"]).isoformat()}
    if domain == "messages":
        return {"id": int(row["id"]), "conversation_id": str(row["conversation_id"]), "role": str(row["role"]), "content": str(row["content"]), "model_used": row["model_used"], "created_at": _timestamp(row["created_at"]).isoformat()}
    if domain == "memories":
        return {"id": str(row["id"]), "content": str(row["content"]), "memory_type": str(row["memory_type"]), "importance": float(row["importance"]), "metadata_json": {}, "created_at": _timestamp(row["created_at"]).isoformat(), "updated_at": _timestamp(row["updated_at"]).isoformat()}
    if domain == "ocr_runs":
        payload = json.loads(str(row["result_json"]))
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
        return {"id": str(row["id"]), "filename": str(row["filename"]), "status": str(row["status"]), "model": str(row["model"]), "created_at": _timestamp(row["created_at"]).isoformat(), "updated_at": _timestamp(row["updated_at"]).isoformat(), "result_json": payload}
    if domain == "request_logs":
        return {"id": int(row["id"]), "endpoint": str(row["endpoint"]), "model_used": row["model_used"], "latency_ms": int(row["latency_ms"]), "status": str(row["status"]), "error_code": row["error_code"], "created_at": _timestamp(row["created_at"]).isoformat()}
    raise MigrationError(f"no canonical source mapping for {domain}")


def _canonical_target_row(domain: str, row: object) -> dict[str, object]:
    if domain == "conversations":
        return {"id": row.id, "created_at": row.created_at.astimezone(UTC).isoformat(), "updated_at": row.updated_at.astimezone(UTC).isoformat()}
    if domain == "messages":
        return {"id": row.id, "conversation_id": row.conversation_id, "role": row.role, "content": row.content, "model_used": row.model_used, "created_at": row.created_at.astimezone(UTC).isoformat()}
    if domain == "memories":
        return {"id": row.id, "content": row.content, "memory_type": row.memory_type, "importance": float(row.importance), "metadata_json": row.metadata_json, "created_at": row.created_at.astimezone(UTC).isoformat(), "updated_at": row.updated_at.astimezone(UTC).isoformat()}
    if domain == "ocr_runs":
        return {"id": row.id, "filename": row.filename, "status": row.status, "model": row.model, "created_at": row.created_at.astimezone(UTC).isoformat(), "updated_at": row.updated_at.astimezone(UTC).isoformat(), "result_json": row.result_json}
    if domain == "request_logs":
        return {"id": row.id, "endpoint": row.endpoint, "model_used": row.model_used, "latency_ms": row.latency_ms, "status": row.status, "error_code": row.error_code, "created_at": row.created_at.astimezone(UTC).isoformat()}
    raise MigrationError(f"no canonical target mapping for {domain}")


def _rows(connection: sqlite3.Connection, domain: str) -> list[sqlite3.Row]:
    if domain not in _tables(connection):
        return []
    order = "id" if domain != "ocr_cache" else "model_name, image_hash"
    return list(connection.execute(f'SELECT * FROM "{domain}" ORDER BY {order}'))


def source_inventory(source: Path, domains: tuple[str, ...]) -> dict[str, DomainReport]:
    with open_readonly(source) as connection:
        reports: dict[str, DomainReport] = {}
        for domain in domains:
            rows = _rows(connection, domain)
            checksum = None
            if domain in {"conversations", "messages", "ocr_runs"}:
                try:
                    checksum = _checksum_values([_canonical_source_row(domain, row) for row in rows], tuple(_canonical_source_row(domain, rows[0]).keys()) if rows else ())
                except (json.JSONDecodeError, ValueError):
                    checksum = None
            reports[domain] = DomainReport(domain=domain, source_rows=len(rows), checksum=checksum)
        return reports


def _insert_if_new(session: Session, statement) -> bool:
    # psycopg does not guarantee a useful rowcount for INSERT .. ON CONFLICT.
    # RETURNING makes the idempotency outcome explicit and testable.
    return session.execute(statement.returning(text("1"))).first() is not None


def _migrate_conversations(session: Session, rows: list[sqlite3.Row], report: DomainReport) -> None:
    for row in rows:
        report.read += 1
        inserted = _insert_if_new(session, insert(Conversation).values(id=str(row["id"]), created_at=_timestamp(row["created_at"]), updated_at=_timestamp(row["updated_at"])).on_conflict_do_nothing(index_elements=["id"]))
        report.inserted += int(inserted); report.skipped += int(not inserted)


def _migrate_messages(session: Session, rows: list[sqlite3.Row], source_conversations: set[str], report: DomainReport) -> None:
    for row in rows:
        report.read += 1
        conversation_id = str(row["conversation_id"])
        if conversation_id not in source_conversations:
            report.orphan_messages += 1; report.failed += 1; report.errors.append(f"orphan_message_id={int(row['id'])}")
            continue
        if session.get(Conversation, conversation_id) is None:
            report.orphan_messages += 1; report.failed += 1; report.errors.append(f"missing_target_conversation_for_message_id={int(row['id'])}")
            continue
        inserted = _insert_if_new(session, insert(Message).values(id=int(row["id"]), conversation_id=conversation_id, role=str(row["role"]), content=str(row["content"]), model_used=row["model_used"], created_at=_timestamp(row["created_at"])).on_conflict_do_nothing(index_elements=["id"]))
        report.inserted += int(inserted); report.skipped += int(not inserted)


def _migrate_memories(session: Session, rows: list[sqlite3.Row], report: DomainReport) -> None:
    for row in rows:
        report.read += 1
        inserted = _insert_if_new(session, insert(Memory).values(id=str(row["id"]), content=str(row["content"]), memory_type=str(row["memory_type"]), importance=float(row["importance"]), metadata_json={}, created_at=_timestamp(row["created_at"]), updated_at=_timestamp(row["updated_at"])).on_conflict_do_nothing(index_elements=["id"]))
        report.inserted += int(inserted); report.skipped += int(not inserted)


def _migrate_ocr_runs(session: Session, rows: list[sqlite3.Row], report: DomainReport) -> None:
    for row in rows:
        report.read += 1
        try:
            payload = json.loads(str(row["result_json"]))
            if not isinstance(payload, dict): raise ValueError("payload is not a JSON object")
        except (json.JSONDecodeError, ValueError) as error:
            report.failed += 1; report.errors.append(f"invalid_ocr_run_json_id={str(row['id'])}: {type(error).__name__}")
            continue
        inserted = _insert_if_new(session, insert(OcrRun).values(id=str(row["id"]), filename=str(row["filename"]), status=str(row["status"]), model=str(row["model"]), result_json=payload, created_at=_timestamp(row["created_at"]), updated_at=_timestamp(row["updated_at"])).on_conflict_do_nothing(index_elements=["id"]))
        report.inserted += int(inserted); report.skipped += int(not inserted)


def _migrate_request_logs(session: Session, rows: list[sqlite3.Row], report: DomainReport) -> None:
    for row in rows:
        report.read += 1
        inserted = _insert_if_new(session, insert(RequestLog).values(id=int(row["id"]), endpoint=str(row["endpoint"]), model_used=row["model_used"], latency_ms=int(row["latency_ms"]), status=str(row["status"]), error_code=row["error_code"], created_at=_timestamp(row["created_at"])).on_conflict_do_nothing(index_elements=["id"]))
        report.inserted += int(inserted); report.skipped += int(not inserted)


def _migrate_ocr_cache(session: Session, rows: list[sqlite3.Row], report: DomainReport) -> None:
    # Legacy cache has only model_name/image_hash/text. It lacks the engine,
    # model revision and config fingerprint required by Phase-2 schema; never
    # invent those key components.
    for row in rows:
        report.read += 1; report.skipped += 1
        report.errors.append(f"ocr_cache_missing_key_metadata=model_name:{str(row['model_name'])[:12]}")


MIGRATORS = {"conversations": _migrate_conversations, "messages": _migrate_messages, "memories": _migrate_memories, "ocr_runs": _migrate_ocr_runs, "request_logs": _migrate_request_logs, "ocr_cache": _migrate_ocr_cache}


def _reseed_identity(session: Session, table: str, model) -> None:
    sequence = session.scalar(text(f"SELECT pg_get_serial_sequence('{table}', 'id')"))
    if sequence:
        maximum = int(session.scalar(select(func.coalesce(func.max(model.id), 0))) or 0)
        session.execute(text("SELECT setval(CAST(:sequence AS regclass), :value, :called)"), {"sequence": sequence, "value": max(maximum, 1), "called": maximum > 0})


def migrate(source: Path, sessions: sessionmaker, domains: tuple[str, ...] = DOMAINS, batch_size: int = 100, resume: bool = False, dry_run: bool = False) -> dict[str, DomainReport]:
    if batch_size <= 0: raise MigrationError("--batch-size must be positive")
    reports = source_inventory(source, domains)
    if dry_run: return reports
    with open_readonly(source) as connection:
        source_conversations = {str(row["id"]) for row in _rows(connection, "conversations")}
        for domain in domains:
            rows = _rows(connection, domain)
            report = reports[domain]
            for start in range(0, len(rows), batch_size):
                batch = rows[start:start + batch_size]
                inserted_before, skipped_before = report.inserted, report.skipped
                try:
                    with sessions.begin() as session:
                        if domain == "messages": _migrate_messages(session, batch, source_conversations, report)
                        else: MIGRATORS[domain](session, batch, report)
                        if report.failed: raise MigrationError(f"{domain} batch contains invalid records")
                except Exception as error:
                    # The transaction for this batch has rolled back. Do not
                    # expose source contents in reports/logs.
                    report.inserted, report.skipped = inserted_before, skipped_before
                    report.failed += len(batch) if not report.failed else 0
                    report.errors.append(f"batch_{start // batch_size + 1}_rolled_back:{type(error).__name__}")
                    break
            if domain == "messages" and report.failed == 0:
                with sessions.begin() as session: _reseed_identity(session, "messages", Message)
            if domain == "request_logs" and report.failed == 0:
                with sessions.begin() as session: _reseed_identity(session, "request_logs", RequestLog)
    verification = verify(source, sessions, domains)
    for domain, report in reports.items():
        report.mismatch = int(verification[domain].get("mismatch", 0))
        report.existing_identical = max(0, report.skipped - report.mismatch)
    return reports


def verify(source: Path, sessions: sessionmaker, domains: tuple[str, ...] = DOMAINS) -> dict[str, dict[str, object]]:
    reports = source_inventory(source, domains)
    result: dict[str, dict[str, object]] = {}
    with open_readonly(source) as connection, sessions() as session:
        source_conversations = {str(row["id"]) for row in _rows(connection, "conversations")}
        targets = {"conversations": Conversation, "messages": Message, "memories": Memory, "ocr_runs": OcrRun, "request_logs": RequestLog, "ocr_cache": OcrCache}
        for domain in domains:
            rows = _rows(connection, domain)
            if domain == "ocr_cache":
                result[domain] = {"source_rows": len(rows), "target_rows": 0, "id_matches": len(rows) == 0, "timestamp_matches": True, "foreign_key_matches": True, "jsonb_matches": True, "checksum_matches": None, "mismatch": 0, "mismatch_ids": [], "valid": len(rows) == 0, "reason": "legacy key incomplete"}
                continue
            ids = [int(row["id"]) if domain in {"messages", "request_logs"} else str(row["id"]) for row in rows]
            target = targets[domain]
            target_objects = list(session.scalars(select(target).where(target.id.in_(ids)).order_by(target.id))) if ids else []
            target_by_id = {item.id: item for item in target_objects}
            target_count = len(target_objects)
            orphans = sum(1 for row in rows if domain == "messages" and str(row["conversation_id"]) not in source_conversations)
            mismatch_ids: list[str] = []
            timestamp_matches = True
            jsonb_matches = True
            source_canonical: list[dict[str, object]] = []
            target_canonical: list[dict[str, object]] = []
            invalid_json = 0
            for source_row in rows:
                source_id = int(source_row["id"]) if domain in {"messages", "request_logs"} else str(source_row["id"])
                try:
                    expected = _canonical_source_row(domain, source_row)
                except (json.JSONDecodeError, ValueError):
                    invalid_json += 1
                    mismatch_ids.append(str(source_id))
                    continue
                source_canonical.append(expected)
                actual_object = target_by_id.get(source_id)
                if actual_object is None:
                    mismatch_ids.append(str(source_id))
                    continue
                actual = _canonical_target_row(domain, actual_object)
                target_canonical.append(actual)
                timestamp_fields = [name for name in expected if name.endswith("_at")]
                if any(expected[name] != actual[name] for name in timestamp_fields):
                    timestamp_matches = False
                if domain == "ocr_runs" and expected["result_json"] != actual["result_json"]:
                    jsonb_matches = False
                if expected != actual:
                    mismatch_ids.append(str(source_id))
            fields = tuple(source_canonical[0].keys()) if source_canonical else ()
            source_checksum = _checksum_values(source_canonical, fields) if domain in {"conversations", "messages", "ocr_runs"} and len(source_canonical) == len(rows) else None
            target_checksum = _checksum_values(target_canonical, fields) if domain in {"conversations", "messages", "ocr_runs"} and len(target_canonical) == len(rows) else None
            checksum_matches = source_checksum == target_checksum if domain in {"conversations", "messages", "ocr_runs"} else None
            foreign_key_matches = True
            if domain == "messages":
                foreign_key_matches = all(session.get(Conversation, row.conversation_id) is not None for row in target_objects)
            id_matches = target_count == len(rows) - orphans and not invalid_json
            mismatch = len(set(mismatch_ids))
            valid = bool(id_matches and not orphans and not invalid_json and not mismatch and timestamp_matches and foreign_key_matches and jsonb_matches and (checksum_matches in {True, None}))
            result[domain] = {"source_rows": len(rows), "target_rows": target_count, "source_checksum": source_checksum, "target_checksum": target_checksum, "orphan_messages": orphans, "invalid_json": invalid_json, "id_matches": id_matches, "timestamp_matches": timestamp_matches, "foreign_key_matches": foreign_key_matches, "jsonb_matches": jsonb_matches, "checksum_matches": checksum_matches, "mismatch": mismatch, "mismatch_ids": sorted(set(mismatch_ids)), "valid": valid}
    return result


def _parse_domains(value: str) -> tuple[str, ...]:
    if value == "all": return DOMAINS
    if value not in DOMAINS: raise MigrationError(f"unsupported domain: {value}")
    return (value,)


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 3A auxiliary SQLite-to-PostgreSQL migration")
    parser.add_argument("--source", type=Path, default=PRIMARY_SOURCE)
    parser.add_argument("--domain", default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--apply", action="store_true", help="write to configured PostgreSQL target; do not use against runtime production in Phase 3A")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()
    if sum(bool(item) for item in (arguments.dry_run, arguments.verify_only, arguments.apply)) != 1:
        parser.error("choose exactly one of --dry-run, --verify-only, or --apply")
    try:
        source = validate_cli_source(arguments.source); domains = _parse_domains(arguments.domain)
        if arguments.dry_run:
            payload = {name: asdict(report) for name, report in source_inventory(source, domains).items()}
        else:
            settings = get_settings()
            if not settings.database_url: raise MigrationError("DATABASE_URL is required for verify/apply")
            sessions = create_session_factory(create_postgres_engine(settings.database_url))
            payload = verify(source, sessions, domains) if arguments.verify_only else {name: asdict(report) for name, report in migrate(source, sessions, domains, arguments.batch_size, arguments.resume).items()}
        print(json.dumps({"source": str(source), "domains": domains, "dry_run": arguments.dry_run, "resume": arguments.resume, "report": payload}, ensure_ascii=False, indent=2))
        if arguments.apply and any(int(item.get("failed", 0)) > 0 for item in payload.values()):
            return 1
        if arguments.verify_only and any(not bool(item.get("valid", False)) for item in payload.values()):
            return 1
        return 0
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
