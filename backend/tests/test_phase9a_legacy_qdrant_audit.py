from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.audit_legacy_qdrant_phase9a import (
    AuditError,
    _scroll_all,
    create_and_verify_snapshot,
    deterministic_legacy_point_id,
    deterministic_versioned_point_id,
    open_archive_readonly,
    validate_primary_archive,
    vector_dimensions,
    vector_fingerprint,
)


def _archive(tmp_path: Path) -> tuple[Path, Path]:
    archive = tmp_path / "local_ai_core.db"
    connection = sqlite3.connect(archive)
    connection.execute("CREATE TABLE document_chunk_versions (document_id TEXT, index_version INTEGER, chunk_index INTEGER)")
    connection.commit()
    connection.close()
    digest = hashlib.sha256(archive.read_bytes()).hexdigest().upper()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": [{"archive_path": str(archive), "size_bytes": archive.stat().st_size, "sha256_before": digest, "sha256_after": digest}]}), encoding="utf-8")
    return archive, manifest


def test_deterministic_ids_are_version_and_chunk_specific():
    legacy = deterministic_legacy_point_id("doc-a", 1, 0)
    assert legacy != deterministic_legacy_point_id("doc-a", 1, 1)
    assert deterministic_versioned_point_id("doc-a", "ver_doc-a_1", 0) != legacy


def test_archive_is_verified_and_opened_read_only(tmp_path):
    archive, manifest = _archive(tmp_path)
    evidence = validate_primary_archive(archive, manifest)
    assert evidence["verified"] and evidence["authoritative"]
    with open_archive_readonly(archive) as connection, pytest.raises(sqlite3.OperationalError):
        connection.execute("INSERT INTO document_chunk_versions VALUES ('x', 1, 0)")


def test_manifest_checksum_mismatch_is_rejected(tmp_path):
    archive, manifest = _archive(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["files"][0]["sha256_after"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AuditError, match="checksum"):
        validate_primary_archive(archive, manifest)


def test_pre_postgres_archive_is_never_authoritative(tmp_path):
    archive, manifest = _archive(tmp_path)
    forbidden = archive.with_name("local_ai_core.pre_postgres_20260716.db")
    archive.rename(forbidden)
    with pytest.raises(AuditError, match="pre_postgres"):
        validate_primary_archive(forbidden, manifest)


def test_vector_equivalence_helpers_are_stable():
    assert vector_dimensions([0.1, 0.2]) == 2
    assert vector_dimensions({"named": [0.1, 0.2]}) == 2
    assert vector_fingerprint([0.1, 0.2]) == vector_fingerprint([0.1, 0.2])


def test_snapshot_must_be_listed_after_creation():
    class Client:
        def create_snapshot(self, **kwargs):
            return {"name": "safe.snapshot"}
        def list_snapshots(self, **kwargs):
            return [{"name": "safe.snapshot"}]
    assert create_and_verify_snapshot(Client(), "documents")["verified"]


def test_unverified_snapshot_fails_closed():
    class Client:
        def create_snapshot(self, **kwargs):
            return {"name": "safe.snapshot"}
        def list_snapshots(self, **kwargs):
            return []
    with pytest.raises(AuditError, match="could not be verified"):
        create_and_verify_snapshot(Client(), "documents")


def test_scroll_reads_pages_without_mutation_api():
    class Client:
        def __init__(self): self.calls = 0
        def scroll(self, **kwargs):
            self.calls += 1
            return ([self.calls], "next") if self.calls == 1 else ([self.calls], None)
    client = Client()
    assert _scroll_all(client, "documents") == [1, 2]
    assert not hasattr(client, "delete") and not hasattr(client, "upsert")
