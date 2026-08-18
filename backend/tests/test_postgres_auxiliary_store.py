from __future__ import annotations

import os
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from app.config.settings import Settings, get_settings
from app.main import app
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Conversation, Memory, Message, MessageSource, OcrCache, OcrRun, RequestLog
from app.services.ocr_service import OCRService
from app.services.memory_service import MemoryService
from app.services.logging_service import LoggingService
from app.stores.postgres_auxiliary_store import PostgresAuxiliaryStore


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


@pytest.fixture
def store():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    prefix = f"aux-prep-{uuid4().hex}"
    adapter = PostgresAuxiliaryStore(factory)
    yield adapter, factory, prefix
    with factory.begin() as session:
        session.execute(delete(Message).where(Message.conversation_id.like(f"{prefix}%")))
        session.execute(delete(Conversation).where(Conversation.id.like(f"{prefix}%")))
        session.execute(delete(Memory).where(Memory.id.like(f"{prefix}%")))
        session.execute(delete(OcrRun).where(OcrRun.id.like(f"{prefix}%")))
        session.execute(delete(OcrCache).where(OcrCache.model_name.like(f"{prefix}%")))
        session.execute(delete(RequestLog).where(RequestLog.endpoint.like(f"/{prefix}%")))


def test_conversation_messages_order_and_cascade(store):
    adapter, factory, prefix = store
    conversation_id = f"{prefix}-conversation"
    adapter.create_conversation(conversation_id)
    adapter.add_message(conversation_id, "user", "one")
    adapter.add_message(conversation_id, "assistant", "two", "model")
    assert adapter.get_messages(conversation_id, 1) == [{"role": "assistant", "content": "two"}]
    detail = adapter.get_conversation(conversation_id)
    assert detail and [message["content"] for message in detail["messages"]] == ["one", "two"]
    assert adapter.list_conversations()[0]["id"] == conversation_id
    assert adapter.delete_conversation(conversation_id)
    with factory() as session:
        assert session.scalar(select(Message).where(Message.conversation_id == conversation_id)) is None


def test_message_sources_are_stored_ordered_and_cascade_with_the_message(store):
    adapter, factory, prefix = store
    conversation_id = f"{prefix}-cited"
    adapter.create_conversation(conversation_id)
    adapter.add_message(conversation_id, "user", "câu hỏi")
    message_id = adapter.add_message(
        conversation_id,
        "assistant",
        "câu trả lời",
        "model",
        [
            {"document_id": "doc_a", "chunk_id": "chunk_a", "filename": "a.pdf", "page_start": 3, "page_end": 4, "heading_path": "Chương 1", "score": 0.9, "excerpt": "đoạn A"},
            {"document_id": "doc_b", "chunk_id": "chunk_b", "filename": "b.txt", "page_start": None, "page_end": None, "heading_path": None, "score": 0.5, "excerpt": "đoạn B"},
        ],
    )

    detail = adapter.get_conversation(conversation_id)
    assert detail is not None
    question, answer = detail["messages"]
    # A question cites nothing; the answer keeps its citations in prompt order.
    assert question["sources"] == []
    assert [source["chunk_id"] for source in answer["sources"]] == ["chunk_a", "chunk_b"]
    assert answer["sources"][0] == {
        "document_id": "doc_a", "chunk_id": "chunk_a", "filename": "a.pdf",
        "page_start": 3, "page_end": 4, "heading_path": "Chương 1", "score": 0.9, "excerpt": "đoạn A",
    }
    assert answer["sources"][1]["page_start"] is None

    with factory.begin() as session:
        session.execute(delete(Message).where(Message.id == message_id))
    with factory() as session:
        assert session.scalar(select(MessageSource).where(MessageSource.message_id == message_id)) is None


def test_memory_ocr_run_request_log_and_cache_contract(store):
    adapter, factory, prefix = store
    memory_id = f"{prefix}-memory"
    adapter.create_memory(memory_id, "first", "fact", 0.5)
    assert adapter.update_memory(memory_id, "second", "preference", 0.8)
    assert adapter.get_memory(memory_id)["content"] == "second"
    assert adapter.delete_memory(memory_id)
    run_id = f"{prefix}-ocr"
    adapter.save_ocr_run(run_id, "scan.pdf", "completed", "model", '{"unknown":{"nested":[1,true]}}')
    adapter.save_ocr_run(run_id, "scan.pdf", "completed", "model", '{"unknown":{"nested":[2,false]},"new":1}')
    saved = next(item for item in adapter.list_ocr_runs() if item["id"] == run_id)
    assert json.loads(str(saved["result_json"])) == {"unknown": {"nested": [2, False]}, "new": 1}
    adapter.log_request(f"/{prefix}/log", None, 4, "ok")
    with factory() as session:
        assert session.scalar(select(RequestLog).where(RequestLog.endpoint == f"/{prefix}/log")) is not None
    assert adapter.get_ocr_cache_with_key("a" * 64, "ollama", prefix, "revision-1", "b" * 64) is None
    adapter.save_ocr_cache_with_key("a" * 64, "ollama", prefix, "revision-1", "b" * 64, "cached")
    assert adapter.get_ocr_cache_with_key("a" * 64, "ollama", prefix, "revision-1", "b" * 64) == "cached"


def test_ocr_service_postgres_cache_misses_without_revision_and_hits_with_revision(store):
    adapter, _, prefix = store

    class Router:
        models = {"ocr": {"name": prefix, "prompt": "recognize", "revision": "r1"}}
        def ocr(self, *_args, **_kwargs): return " text ", prefix

    service = OCRService(Router(), adapter)
    first = service.recognize_png(b"png", 200)
    second = service.recognize_png(b"png", 200)
    assert not first.cache_hit and second.cache_hit
    Router.models["ocr"].pop("revision")
    assert not service.recognize_png(b"different", 200).cache_hit


def test_memory_service_crud_uses_postgres_adapter(store, tmp_path):
    adapter, _factory, _prefix = store
    class Router:
        def embed(self, value): return [float(len(value))], "embed"
    class Qdrant:
        def __init__(self): self.items = {}
        def upsert_memory(self, memory_id, content, memory_type, importance, vector): self.items[memory_id] = {"id": memory_id, "content": content, "memory_type": memory_type, "importance": importance}
        def delete_memory(self, memory_id): self.items.pop(memory_id, None)
        def search_memories(self, _vector, _top_k): return list(self.items.values())
    service = MemoryService(adapter, Qdrant(), Router(), LoggingService(adapter, tmp_path / "logs"))
    created = service.add("fact", "fact", 0.4)
    assert service.update(str(created["id"]), "updated", "preference", 0.9)["content"] == "updated"
    service.delete(str(created["id"]))
    assert adapter.get_memory(str(created["id"])) is None


def test_postgres_transaction_rollback_and_unavailable_database(store):
    adapter, factory, prefix = store
    with pytest.raises(RuntimeError):
        with factory.begin() as session:
            session.add(Conversation(id=f"{prefix}-rollback"))
            raise RuntimeError("rollback")
    assert not adapter.conversation_exists(f"{prefix}-rollback")
    unavailable = PostgresAuxiliaryStore(create_session_factory(create_postgres_engine(str(URL).rsplit("/", 1)[0] + "/auxiliary_missing")))
    with pytest.raises(OperationalError):
        unavailable.conversation_exists("any")


def test_settings_reject_invalid_or_missing_postgres_auxiliary_config():
    with pytest.raises(ValueError):
        Settings(database_url=None)
    with pytest.raises(ValueError):
        Settings(database_url="sqlite:///wrong.db")


def test_conversation_api_uses_postgres_runtime(monkeypatch, tmp_path, store):
    adapter, _factory, prefix = store
    conversation_id = f"{prefix}-api"
    adapter.create_conversation(conversation_id)
    adapter.add_message(conversation_id, "user", "postgres API")
    monkeypatch.setenv("DATABASE_URL", str(URL))
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.get(f"/conversations/{conversation_id}")
            assert response.status_code == 200
            assert response.json()["messages"][0]["content"] == "postgres API"
    finally:
        get_settings.cache_clear()
