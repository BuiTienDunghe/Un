from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Conversation, Memory, Message, OcrCache, OcrRun, RequestLog
from scripts import migrate_sqlite_to_postgres as tool


URL = __import__("os").getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


def _source(path: Path, *, orphan: bool = False, invalid_ocr: bool = False) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE conversations (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, model_used TEXT, created_at TEXT NOT NULL);
        CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL, memory_type TEXT NOT NULL, importance REAL NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE ocr_runs (id TEXT PRIMARY KEY, filename TEXT NOT NULL, status TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, result_json TEXT NOT NULL);
        CREATE TABLE request_logs (id INTEGER PRIMARY KEY, endpoint TEXT NOT NULL, model_used TEXT, latency_ms INTEGER NOT NULL, status TEXT NOT NULL, error_code TEXT, created_at TEXT NOT NULL);
        CREATE TABLE ocr_cache (model_name TEXT NOT NULL, image_hash TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(model_name,image_hash));
    """)
    now = datetime.now(UTC).isoformat(); conversation_id = "legacy-conversation"
    connection.execute("INSERT INTO conversations VALUES (?,?,?)", (conversation_id, now, now))
    connection.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)", (900000042, "missing-conversation" if orphan else conversation_id, "user", "sensitive message", None, now))
    connection.execute("INSERT INTO ocr_runs VALUES (?,?,?,?,?,?,?)", ("ocr-good", "x.pdf", "completed", "ocr-model", now, now, '{"pages":[{"page":1}]}'))
    if invalid_ocr:
        connection.execute("INSERT INTO ocr_runs VALUES (?,?,?,?,?,?,?)", ("ocr-invalid", "bad.pdf", "failed", "ocr-model", now, now, "{bad"))
    connection.execute("INSERT INTO request_logs VALUES (?,?,?,?,?,?,?)", (900000007, "/chat", None, 12, "ok", None, now))
    connection.commit(); connection.close(); return path


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


def _cleanup(factory):
    with factory.begin() as session:
        session.execute(delete(Message).where(Message.conversation_id.in_(("legacy-conversation", "missing-conversation"))))
        session.execute(delete(Conversation).where(Conversation.id == "legacy-conversation"))
        session.execute(delete(OcrRun).where(OcrRun.id.in_(("ocr-good", "ocr-invalid"))))
        session.execute(delete(RequestLog).where(RequestLog.id == 900000007))
        session.execute(delete(Memory).where(Memory.id.like("mig-test-%")))
        session.execute(delete(OcrCache).where(OcrCache.input_hash == "x" * 64))


def test_dry_run_does_not_write_postgres(factory, tmp_path):
    source = _source(tmp_path / "source.db")
    _cleanup(factory)
    report = tool.migrate(source, factory, dry_run=True)
    assert report["conversations"].source_rows == 1 and report["messages"].source_rows == 1
    with factory() as session: assert session.get(Conversation, "legacy-conversation") is None


def test_conversations_messages_idempotency_and_reseed(factory, tmp_path):
    source = _source(tmp_path / "source.db"); _cleanup(factory)
    first = tool.migrate(source, factory, domains=("conversations", "messages"), batch_size=1)
    second = tool.migrate(source, factory, domains=("conversations", "messages"), batch_size=1, resume=True)
    assert first["messages"].inserted == 1 and second["messages"].inserted == 0 and second["messages"].skipped == 1
    verification = tool.verify(source, factory, domains=("conversations", "messages"))
    assert verification["conversations"]["valid"] and verification["messages"]["valid"]
    with factory.begin() as session:
        message = session.get(Message, 900000042); assert message and message.conversation_id == "legacy-conversation"
        session.add(Message(conversation_id="legacy-conversation", role="assistant", content="after import")); session.flush()
        assert session.scalar(select(Message.id).where(Message.content == "after import")) > 900000042
    _cleanup(factory)


def test_request_log_reseed_and_same_primary_key_mismatch_is_not_hidden(factory, tmp_path):
    source = _source(tmp_path / "source.db"); _cleanup(factory)
    tool.migrate(source, factory, domains=("conversations", "messages", "request_logs"))
    with factory.begin() as session:
        session.add(RequestLog(endpoint="/runtime", latency_ms=1, status="ok")); session.flush()
        runtime_id = session.scalar(select(RequestLog.id).where(RequestLog.endpoint == "/runtime"))
        assert runtime_id > 900000007
        session.get(Message, 900000042).content = "different target value"
    verification = tool.verify(source, factory, domains=("messages", "request_logs"))
    assert not verification["messages"]["valid"]
    assert verification["messages"]["mismatch"] == 1
    assert verification["messages"]["checksum_matches"] is False
    assert verification["request_logs"]["valid"]
    with factory.begin() as session:
        session.execute(delete(RequestLog).where(RequestLog.endpoint == "/runtime"))
    _cleanup(factory)


def test_verify_only_returns_nonzero_for_conflicting_existing_primary_key(factory, tmp_path, monkeypatch):
    source = _source(tmp_path / "source.db"); _cleanup(factory)
    tool.migrate(source, factory, domains=("conversations", "messages"))
    with factory.begin() as session:
        session.get(Message, 900000042).content = "conflicting target value"
    monkeypatch.setattr(tool, "validate_cli_source", lambda path: source)
    monkeypatch.setattr(tool, "get_settings", lambda: SimpleNamespace(database_url=str(URL)))
    monkeypatch.setattr("sys.argv", ["migration", "--source", str(source), "--domain", "messages", "--verify-only"])
    assert tool.main() == 1
    _cleanup(factory)


def test_orphan_message_is_reported_and_batch_is_rolled_back(factory, tmp_path):
    source = _source(tmp_path / "source.db", orphan=True); _cleanup(factory)
    report = tool.migrate(source, factory, domains=("conversations", "messages"), batch_size=10)
    assert report["messages"].orphan_messages == 1 and report["messages"].failed >= 1
    with factory() as session: assert session.get(Message, 900000042) is None
    _cleanup(factory)


def test_ocr_json_valid_invalid_and_empty_domains(factory, tmp_path):
    good = _source(tmp_path / "good.db"); _cleanup(factory)
    report = tool.migrate(good, factory, domains=("memories", "ocr_runs", "ocr_cache"))
    assert report["memories"].source_rows == 0 and report["ocr_cache"].source_rows == 0 and report["ocr_runs"].inserted == 1
    with factory() as session: assert session.get(OcrRun, "ocr-good").result_json == {"pages": [{"page": 1}]}
    _cleanup(factory)
    bad = _source(tmp_path / "bad.db", invalid_ocr=True)
    report = tool.migrate(bad, factory, domains=("ocr_runs",), batch_size=2)
    assert report["ocr_runs"].failed >= 1
    # The valid row shared the failing batch, so it must be rolled back too.
    with factory() as session: assert session.get(OcrRun, "ocr-good") is None


def test_source_and_postgres_failures_are_rejected(factory, tmp_path):
    with pytest.raises(tool.MigrationError): tool.open_readonly(tmp_path / "missing.db")
    with pytest.raises(tool.MigrationError): tool.validate_cli_source(tmp_path / "test.db")
    unavailable_url = str(URL).rsplit("/", 1)[0] + "/local_ai_phase3a_missing"
    unavailable = create_session_factory(create_postgres_engine(unavailable_url))
    with pytest.raises(OperationalError):
        tool.migrate(_source(tmp_path / "source.db"), unavailable, domains=("conversations",))
