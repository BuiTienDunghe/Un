from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, inspect, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Conversation, EmbeddingCache, Memory, Message, OcrCache, OcrRun, RequestLog


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


def test_auxiliary_schema_has_legacy_compatible_keys_and_postgres_types(factory):
    inspector = inspect(factory.kw["bind"])
    expected = {"conversations", "messages", "memories", "request_logs", "ocr_runs", "ocr_cache", "embedding_cache"}
    assert expected.issubset(set(inspector.get_table_names()))
    assert any(foreign["referred_table"] == "conversations" and foreign["constrained_columns"] == ["conversation_id"] for foreign in inspector.get_foreign_keys("messages"))
    assert any(index["column_names"] == ["created_at"] for index in inspector.get_indexes("request_logs"))
    assert any(index["column_names"] == ["updated_at"] for index in inspector.get_indexes("ocr_runs"))
    assert any(constraint["name"] == "uq_ocr_cache_key" for constraint in inspector.get_unique_constraints("ocr_cache"))
    assert any(constraint["name"] == "uq_embedding_cache_key" for constraint in inspector.get_unique_constraints("embedding_cache"))


def test_auxiliary_schema_preserves_ids_jsonb_and_cascade(factory):
    suffix = uuid4().hex
    conversation_id = f"legacy-conversation-{suffix}"
    memory_id = f"mem-{suffix}"
    try:
        with factory.begin() as session:
            session.add(Conversation(id=conversation_id))
            session.add(Message(conversation_id=conversation_id, role="user", content="legacy message"))
            session.add(Memory(id=memory_id, content="memory", memory_type="fact", importance=0.5, metadata_json={"legacy": True}))
            session.add(RequestLog(endpoint="/chat", latency_ms=1, status="ok"))
            session.add(OcrRun(id=f"ocr-{suffix}", filename="legacy.pdf", status="completed", model="legacy-model", result_json={"pages": [{"page": 1}]}))
            session.add(OcrCache(input_hash="a" * 64, engine="ollama", model_name="model", model_revision="unknown", config_fingerprint="b" * 64, text="cached"))
            session.add(EmbeddingCache(content_hash="c" * 64, model_name="embedding", model_revision="unknown", dimensions=2, config_fingerprint="d" * 64, normalization_fingerprint="e" * 64, vector=[0.1, 0.2]))
        with factory.begin() as session:
            assert session.get(Memory, memory_id).metadata_json == {"legacy": True}
            assert session.scalar(select(OcrRun.result_json).where(OcrRun.id == f"ocr-{suffix}")) == {"pages": [{"page": 1}]}
            session.execute(delete(Conversation).where(Conversation.id == conversation_id))
        with factory() as session:
            assert session.scalar(select(Message.id).where(Message.conversation_id == conversation_id)) is None
    finally:
        with factory.begin() as session:
            session.execute(delete(Memory).where(Memory.id == memory_id))
            session.execute(delete(OcrRun).where(OcrRun.id == f"ocr-{suffix}"))
            session.execute(delete(OcrCache).where(OcrCache.input_hash == "a" * 64))
            session.execute(delete(EmbeddingCache).where(EmbeddingCache.content_hash == "c" * 64))
