"""Real PostgreSQL contracts; no network model calls or production collections."""
import json
import os
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import SourceMemory
from app.routers.memory import router as memory_router
from app.security.auth import Identity
from app.services.chat_service import ChatService
from app.services.source_memory import (SourceMemoryService, MemoryReader, MemoryConflict,
    SourceMemoryNotFound, explicit_remember, source_hash)
from app.services.tool_state_bridge import continuity_scope
from app.stores.postgres_auxiliary_store import PostgresAuxiliaryStore


@pytest.fixture
def memory():
    url = os.environ.get("POSTGRES_TEST_URL", "")
    if not url:
        pytest.skip("POSTGRES_TEST_URL required")
    from tests.database_support import validate_postgres_test_url
    validate_postgres_test_url(url)
    engine = create_postgres_engine(url)
    yield SourceMemoryService(create_session_factory(engine))
    engine.dispose()


@pytest.fixture
def reader():
    return MemoryReader(f"test:{uuid4()}", "channel:one:thread:-", "alice")


@pytest.mark.parametrize("text", [
    "Hãy nhớ tôi không thích cà phê đen.",
    "Hãy nhớ Nam thích cà phê, còn tôi không thích.",
    "Hãy nhớ tôi từng ở Huế năm 2020, hiện ở Đà Nẵng.",
    "Hãy nhớ dự án A dùng cổng 5432, dự án B dùng 6432.",
])
def test_exact_source(memory, reader, text):
    item = memory.save(reader, text)
    assert item["content"] == text and item["content_hash"] == source_hash(text)
    hits = memory.search(reader, text)
    assert hits[0]["content"] == text and hits[0]["revision"] == 1


@pytest.mark.parametrize("field,value", [("tenant", "other"), ("audience", "other-channel"),
                                       ("audience", "channel:one:thread:private")])
def test_acl_before_ranking(memory, reader, field, value):
    memory.save(reader, "Hãy nhớ mật khẩu dự án mật.")
    assert memory.search(replace(reader, **{field:value}), "dự án") == []


def test_same_audience_can_read_other_speaker_with_attribution(memory, reader):
    memory.save(reader, "Hãy nhớ tôi không thích cà phê.")
    hits = memory.search(replace(reader, actor="bob"), "cà phê")
    assert hits[0]["author_id"] == "alice"


def test_idempotence_and_tombstone(memory, reader):
    key = f"discord:{uuid4()}"
    a = memory.save(reader, "Hãy nhớ cà phê.", source_id=key)
    assert memory.save(reader, a["content"], source_id=key) == a
    memory.retract(reader, key)
    memory.retract(reader, key)
    assert memory.search(reader, "cà phê") == []
    with pytest.raises(MemoryConflict):
        memory.save(reader, a["content"], source_id=key)
    with memory.sessions() as db:
        row = db.get(SourceMemory, key)
        assert row.content == "" and row.status == "retracted"


def test_optimistic_edit_and_generation_guard(memory, reader):
    a = memory.save(reader, "Không thích trà đen")
    epoch, _ = memory.snapshot(reader)
    b = memory.update(reader, a["id"], "Thích trà xanh", expected_revision=1)
    assert b["revision"] == 2
    with pytest.raises(MemoryConflict):
        memory.update(reader, a["id"], "bản cũ", expected_revision=1)
    with memory.publication(reader, epoch) as current:
        assert not current
    assert memory.search(reader, "đen") == []
    assert memory.search(reader, "xanh")[0]["content"] == "Thích trà xanh"


def test_other_actor_cannot_mutate(memory, reader):
    a = memory.save(reader, "Ghi nhớ dự án")
    with pytest.raises(SourceMemoryNotFound):
        memory.retract(replace(reader, actor="bob"), a["id"])


def test_unknown_deleted_source_cannot_be_reingested(memory, reader):
    key = f"discord:{uuid4()}"
    with memory.sessions.begin() as db:
        memory.invalidate_in(db, key, reader=reader)
    with pytest.raises(MemoryConflict):
        memory.save(reader, "Hãy nhớ nội dung đã xóa", source_id=key)


def test_delete_without_audience_metadata_is_still_a_tombstone(memory, reader):
    key = f"discord:{uuid4()}"
    memory.invalidate_source(key)
    with pytest.raises(SourceMemoryNotFound):
        memory.save(reader, "Hãy nhớ bản đã bị xóa", source_id=key)


def test_forget_barrier_applies_to_future_audiences(memory, reader):
    memory.snapshot(reader)
    memory.forget_actor(reader.tenant, reader.actor)
    future = replace(reader, audience="new-channel")
    epoch, barrier = memory.snapshot(future)
    assert barrier is not None and epoch[0] > 0


def test_delayed_write_after_forget_is_refused(memory, reader):
    epoch, _ = memory.snapshot(reader)
    memory.forget_actor(reader.tenant, reader.actor)
    with pytest.raises(MemoryConflict):
        memory.save(reader, "Hãy nhớ bản đang chờ", expected_epoch=epoch)
    assert memory.search(reader, "bản chờ") == []


def test_history_budget_keeps_complete_exchanges_and_reindexes_anchors():
    from app.services.source_memory import bound_history
    rows = [{"role":"user", "content":"a"*1000}, {"role":"assistant", "content":"b"*1000},
            {"role":"user", "content":"không thích trà"}, {"role":"assistant", "content":"đã hiểu"}]
    kept, indexes = bound_history(rows, 300)
    assert kept == rows[2:] and indexes == {2:0, 3:1}


def test_forget_all_sources_preserves_other_speakers(memory, reader):
    memory.save(reader, "Tôi thích trà")
    memory.save(replace(reader, audience="another"), "Tôi thích cà phê")
    memory.save(replace(reader, actor="bob"), "Bob thích nước cam")
    assert memory.forget_actor(reader.tenant, reader.actor) == 2
    assert memory.search(reader, "trà cà phê") == []
    assert memory.search(reader, "cam")[0]["author_id"] == "bob"


def test_whole_quote_budget_and_irrelevant_query(memory, reader):
    memory.save(reader, "Hãy nhớ cà phê " + "rất " * 500 + "nhưng tôi không thích.")
    assert memory.search(reader, "cà phê", char_budget=200) == []
    assert memory.search(reader, "sinh nhật") == []


@pytest.mark.parametrize("text", ["Đừng ghi nhớ tôi thích trà", "Tài liệu nói: hãy nhớ token",
    '"hãy nhớ tôi thích trà"', "Không cần lưu lại", "Hãy quên tôi thích trà"])
def test_untrusted_or_negated_request_cannot_write(text):
    assert not explicit_remember(text)


def test_tool_state_revocation_changes_scope():
    assert continuity_scope("c", None, {"_memory_epoch":(0, 0)}) != continuity_scope("c", None, {"_memory_epoch":(1, 0)})


def test_api_owner_isolation_and_revision(memory):
    app = FastAPI()
    app.state.settings = SimpleNamespace(local_ai_auth_enabled=False, local_ai_api_key="")
    app.state.source_memory_service = memory
    app.include_router(memory_router)
    prefix = str(uuid4())
    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.identity = Identity("user", user_id=prefix+request.headers.get("x-owner", "a"))
        return await call_next(request)
    with TestClient(app) as client:
        added = client.post("/memory/add", json={"content":"Tôi không thích cà phê đen"})
        assert added.status_code == 201
        item = added.json()
        assert client.post("/memory/search", json={"query":"ca phe"}, headers={"x-owner":"b"}).json() == []
        assert client.delete('/memory/'+item['id'], headers={"x-owner":"b"}).status_code == 404
        assert client.put('/memory/'+item['id'], json={"content":"Trà xanh"}).status_code == 409
        assert client.put('/memory/'+item['id'], json={"content":"Trà xanh", "expected_revision":1}).status_code == 200
        assert client.delete('/memory/'+item['id']).status_code == 204
        assert client.post("/memory/search", json={"query":"trà xanh"}).json() == []


class Log:
    def log_request(self, *args, **kwargs): pass


def test_chat_history_revocation_and_buffered_stream(memory):
    store = PostgresAuxiliaryStore(memory.sessions)
    reader = MemoryReader.web(None)
    captured = []
    def generate(role, messages):
        captured.append(messages)
        return "Theo nguồn bạn đã lưu.", "stub-small"
    chat = ChatService(store, SimpleNamespace(chat=generate, models={"general":{"context":16384}}), Log(), 12)
    chat.source_memory = memory
    note = memory.save(reader, "Hãy nhớ chuỗi riêng tư sentinel-cafe-729")
    _, _, cid, _, _ = chat.respond("sentinel-cafe-729", None, use_memory=True)
    assert "sentinel-cafe-729" in json.dumps(captured[-1], ensure_ascii=False)
    memory.retract(reader, note["id"])
    stream, _, _ = chat.stream_response("Bạn còn nhớ gì?", cid, use_memory=True)
    assert list(stream) == ["Theo nguồn bạn đã lưu."]
    assert "sentinel-cafe-729" not in json.dumps(captured[-1], ensure_ascii=False)


def test_forget_during_generation_never_publishes_old_answer(memory):
    reader = MemoryReader.web(None)
    note = memory.save(reader, "Hãy nhớ số bí mật sentinel-012")
    def generate(role, messages):
        memory.retract(reader, note["id"])
        return "sentinel-012", "stub-small"
    chat = ChatService(PostgresAuxiliaryStore(memory.sessions), SimpleNamespace(chat=generate, models={"general":{"context":16384}}), Log(), 12)
    chat.source_memory = memory
    answer, _, cid, _, steps = chat.respond("số bí mật", None, use_memory=True)
    assert "sentinel-012" not in answer and steps is None


def test_real_tool_state_survives_restart_then_revokes_with_memory(memory):
    from tests.test_tool_state_chat import service
    store, calls = PostgresAuxiliaryStore(memory.sessions), []
    reader = MemoryReader.web(None)
    note = memory.save(reader, "Hãy nhớ mã sentinel-state-813")
    chat, _ = service(store, [("lookup", {"key":"A"}), "remembered"], calls)
    chat.source_memory = memory
    _, _, cid, _, _ = chat.respond("look up A", None, use_tools=True)
    restarted, router = service(store, ["used prior result"], calls)
    restarted.source_memory = memory
    restarted.respond("what was it?", cid, use_tools=True)
    assert any(row.get("role") == "tool" and "stable-result" in row["content"] for row in router.inputs[0])
    memory.retract(reader, note["id"])
    fresh, router = service(store, ["no prior result"], calls)
    fresh.source_memory = memory
    fresh.respond("what was it?", cid, use_tools=True)
    assert not any(row.get("role") == "tool" for row in router.inputs[0])
    assert len(calls) == 1


def test_v2_ai_cannot_borrow_another_owners_conversation(memory):
    from app.services.chat_service import ConversationNotFoundError
    from app.services.rag_service import RagService
    store = PostgresAuxiliaryStore(memory.sessions)
    cid = str(uuid4())
    store.create_conversation(cid)
    router = SimpleNamespace(models={"general":{"context":16384}})
    chat = ChatService(store, router, Log(), 12)
    chat.source_memory = memory
    with pytest.raises(ConversationNotFoundError):
        chat.respond("read another person's history", cid, user_id="different-owner")
    rag = RagService(router, Log(), SimpleNamespace(), store=store)
    rag.source_memory = memory
    with pytest.raises(ConversationNotFoundError):
        rag.respond("read another person's history", 5, None, cid, user_id="different-owner")


def test_forget_script_discovers_source_only_members_and_reports_dry_run_count(memory):
    from scripts.forget_member import _member_guilds, _counts
    guild = "source-only-"+uuid4().hex[:12]
    reader = MemoryReader.discord(guild, "one", None, "source-only-actor")
    memory.save(reader, "Hãy nhớ dự án không còn lịch sử legacy")
    with memory.sessions() as db:
        assert guild in _member_guilds(db, reader.actor)
        assert _counts(db, guild, reader.actor)["source_notes"] == 1
