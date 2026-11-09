"""Private tool-state persistence on an explicitly isolated real PostgreSQL DB."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import os
from types import SimpleNamespace
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from tests.database_support import validate_postgres_test_url
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import AgentTrace, AgentTraceSummary, Conversation, Document, DocumentVersion, Message
from app.services.tool_state import STATE_KIND, ToolStateLimits, ToolStateRecorder, scope_key
from app.stores import postgres_auxiliary_store
from app.stores.postgres_auxiliary_store import PostgresAuxiliaryStore


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL to a dedicated PostgreSQL test database")


@pytest.fixture
def state_database():
    engine = create_postgres_engine(validate_postgres_test_url(URL))
    sessions = create_session_factory(engine)
    prefix = "tool-state-" + uuid4().hex
    try:
        yield PostgresAuxiliaryStore(sessions), sessions, prefix
    finally:
        with sessions.begin() as session:
            # Summaries deliberately have no FK; remove only this fixture's telemetry.
            session.execute(delete(AgentTraceSummary).where(AgentTraceSummary.conversation_id.startswith(prefix)))
            session.execute(delete(Conversation).where(Conversation.id.startswith(prefix)))
            session.execute(delete(Document).where(Document.id.startswith(prefix)))
        engine.dispose()


def payload(content="42"):
    recorder = ToolStateRecorder()
    assert recorder.record("calculate", {"expression": "6*7"}, content, None, policy="read", schema={
        "type": "function", "function": {"name": "calculate", "parameters": {"type": "object", "properties": {}}},
    })
    return recorder.payload()


def conversation(store, prefix, suffix="one"):
    conversation_id = prefix + "-" + suffix
    store.create_conversation(conversation_id)
    return conversation_id


def state_rows(sessions, conversation_id):
    with sessions() as session:
        return list(session.scalars(select(AgentTrace).where(
            AgentTrace.conversation_id == conversation_id, AgentTrace.kind == STATE_KIND,
        ).order_by(AgentTrace.id)))


def test_agent_history_keeps_order_and_trusted_message_ids_without_changing_text_history(state_database):
    store, _sessions, prefix = state_database
    conv = conversation(store, prefix)
    other = conversation(store, prefix, "other")
    first = store.add_message(conv, "user", "question")
    second = store.add_message(conv, "assistant", "answer")
    third = store.add_message(conv, "user", "follow-up")
    store.add_message(other, "assistant", "unrelated")
    assert store.get_agent_history(conv, 2) == [
        {"role": "assistant", "content": "answer", "message_id": second},
        {"role": "user", "content": "follow-up", "message_id": third},
    ]
    assert store.get_agent_history(conv, 9)[0]["message_id"] == first
    assert store.get_messages(conv, 2) == [
        {"role": "assistant", "content": "answer"}, {"role": "user", "content": "follow-up"},
    ]


@pytest.mark.parametrize("wrong_owner", ["user", "other_conversation", "missing"])
def test_state_must_belong_to_the_assistant_in_the_same_conversation(state_database, wrong_owner):
    store, sessions, prefix = state_database
    conv = conversation(store, prefix)
    other = conversation(store, prefix, "other")
    if wrong_owner == "user":
        message_id = store.add_message(conv, "user", "not an assistant")
    else:
        message_id = store.add_message(other, "assistant", "another conversation")
        if wrong_owner == "missing":
            with sessions.begin() as session:
                session.execute(delete(Message).where(Message.id == message_id))
    with pytest.raises(ValueError, match="assistant message"):
        store.save_tool_state(conv, message_id, "scope", payload())
    assert state_rows(sessions, conv) == []
    assert state_rows(sessions, other) == []


def test_restarted_store_loads_only_selected_messages_or_origins_in_the_exact_scope(state_database):
    store, sessions, prefix = state_database
    conv = conversation(store, prefix)
    other_conv = conversation(store, prefix, "other")
    scope = scope_key(conv, "discord", "member-a", "guild-a")
    other_scope = scope_key(conv, "discord", "member-b", "guild-a")
    first = store.add_message(conv, "assistant", "first")
    second = store.add_message(conv, "assistant", "second")
    alien = store.add_message(conv, "assistant", "different speaker")
    elsewhere = store.add_message(other_conv, "assistant", "different conversation")
    store.save_tool_state(conv, first, scope, payload("first"), origin="discord-message-1")
    store.save_tool_state(conv, second, scope, payload("second"), origin="discord-message-2")
    store.save_tool_state(conv, alien, other_scope, payload("alien"), origin="discord-message-1")
    store.save_tool_state(other_conv, elsewhere, scope, payload("elsewhere"), origin="discord-message-1")

    restarted = PostgresAuxiliaryStore(sessions)
    assert restarted.load_tool_states(conv, scope) == []
    assert restarted.load_tool_states(conv, scope, message_ids=[], origins=[]) == []
    selected = restarted.load_tool_states(conv, scope, message_ids=[first, alien, elsewhere])
    assert [(row["message_id"], row["payload"]) for row in selected] == [(first, payload("first"))]
    assert restarted.load_tool_states(conv, scope, origins=["unknown"]) == []
    origins = restarted.load_tool_states(conv, scope, origins=["discord-message-1"])
    assert [row["message_id"] for row in origins] == [first]
    assert origins[0]["origin"] == "discord-message-1"
    union = restarted.load_tool_states(conv, scope, message_ids=[first], origins=["discord-message-2"])
    assert [row["message_id"] for row in union] == [second, first]
    assert [row["message_id"] for row in restarted.load_tool_states(conv, other_scope, message_ids=[first, alien])] == [alien]


def test_repeated_save_replaces_one_answer_state_and_preserves_ordinary_traces(state_database):
    store, sessions, prefix = state_database
    conv = conversation(store, prefix)
    message = store.add_message(conv, "assistant", "answer")
    store.add_agent_traces(conv, message, [{"kind": "tool_call", "tool_name": "calculate", "tool_declared": True,
                                           "content": "ordinary trace"}])
    store.save_tool_state(conv, message, "old-scope", payload("old"), origin="old-origin")
    store.save_tool_state(conv, message, "new-scope", payload("mới"), origin="new-origin")
    assert len(state_rows(sessions, conv)) == 1
    assert [row["kind"] for row in store.get_agent_traces(message)] == ["tool_call"]
    assert store.load_tool_states(conv, "old-scope", message_ids=[message]) == []
    assert store.load_tool_states(conv, "new-scope", message_ids=[message]) == [
        {"message_id": message, "origin": "new-origin", "payload": payload("mới")},
    ]
    with sessions() as session:
        assert session.scalar(select(AgentTrace.content).where(
            AgentTrace.message_id == message, AgentTrace.kind == "tool_call",
        )) == "ordinary trace"


def test_retention_keeps_only_eight_newest_private_envelopes(state_database):
    store, sessions, prefix = state_database
    conv = conversation(store, prefix)
    messages = []
    for i in range(ToolStateLimits().max_envelopes + 2):
        message = store.add_message(conv, "assistant", str(i))
        messages.append(message)
        store.save_tool_state(conv, message, "scope", payload(str(i)))
    assert [row.message_id for row in state_rows(sessions, conv)] == messages[-8:]
    assert [row["message_id"] for row in store.load_tool_states(conv, "scope", message_ids=messages)] == messages[-8:][::-1]
    # Retention is local to the conversation, not a global eviction quota.
    other = conversation(store, prefix, "other")
    message = store.add_message(other, "assistant", "kept elsewhere")
    store.save_tool_state(other, message, "scope", payload())
    assert len(state_rows(sessions, conv)) == 8


def test_expired_state_is_not_loaded_and_next_save_prunes_it_without_deleting_traces(state_database, monkeypatch):
    store, sessions, prefix = state_database
    clock = SimpleNamespace(now=datetime.now(UTC))
    monkeypatch.setattr(postgres_auxiliary_store, "_utc_now", lambda: clock.now)
    conv = conversation(store, prefix)
    old = store.add_message(conv, "assistant", "old")
    store.add_agent_traces(conv, old, [{"kind": "tool_call", "content": "ordinary trace"}])
    store.save_tool_state(conv, old, "scope", payload("old"))
    clock.now += timedelta(seconds=ToolStateLimits().max_age_seconds - 1)
    assert len(store.load_tool_states(conv, "scope", message_ids=[old])) == 1
    clock.now += timedelta(seconds=2)
    assert store.load_tool_states(conv, "scope", message_ids=[old]) == []
    fresh = store.add_message(conv, "assistant", "fresh")
    store.save_tool_state(conv, fresh, "scope", payload("fresh"))
    assert [row.message_id for row in state_rows(sessions, conv)] == [fresh]
    with sessions() as session:
        assert session.scalar(select(AgentTrace.content).where(
            AgentTrace.message_id == old, AgentTrace.kind == "tool_call",
        )) == "ordinary trace"


def test_store_does_not_save_empty_or_oversized_envelopes(state_database):
    store, sessions, prefix = state_database
    conv = conversation(store, prefix)
    message = store.add_message(conv, "assistant", "answer")
    store.save_tool_state(conv, message, "scope", {"v": 1, "groups": []})
    oversized = payload()
    oversized["groups"][0]["content"] = "x" * (ToolStateLimits().max_chars + 1)
    store.save_tool_state(conv, message, "scope", oversized)
    assert state_rows(sessions, conv) == []


@pytest.mark.parametrize("invalid", ["not JSON", "[]", '{"v":2,"groups":[{}]}', "x" * 8001],
                         ids=["invalid-json", "array", "wrong-version", "oversized"])
def test_reader_ignores_malformed_or_oversized_durable_rows(state_database, invalid):
    store, sessions, prefix = state_database
    conv = conversation(store, prefix)
    message = store.add_message(conv, "assistant", "answer")
    with sessions.begin() as session:
        session.add(AgentTrace(conversation_id=conv, message_id=message, step_index=-1, kind=STATE_KIND,
                               arguments={"scope_key": "scope"}, content=invalid, created_at=datetime.now(UTC)))
        session.add(AgentTrace(conversation_id=conv, message_id=message, step_index=0, kind="tool_call",
                               arguments={"scope_key": "scope"}, content=json.dumps(payload()), created_at=datetime.now(UTC)))
    assert store.load_tool_states(conv, "scope", message_ids=[message]) == []


@pytest.mark.parametrize("delete_target", ["message", "conversation"])
def test_private_state_cascades_with_its_answer_or_conversation(state_database, delete_target):
    store, sessions, prefix = state_database
    conv = conversation(store, prefix)
    message = store.add_message(conv, "assistant", "answer")
    store.save_tool_state(conv, message, "scope", payload("private result"))
    if delete_target == "message":
        with sessions.begin() as session:
            session.execute(delete(Message).where(Message.id == message))
        assert store.conversation_exists(conv)
    else:
        assert store.delete_conversation(conv)
        assert not store.conversation_exists(conv)
    assert state_rows(sessions, conv) == []
    assert store.load_tool_states(conv, "scope", message_ids=[message]) == []


def test_private_state_never_writes_its_content_or_kind_to_persistent_summaries(state_database):
    store, sessions, prefix = state_database
    conv = conversation(store, prefix)
    message = store.add_message(conv, "assistant", "answer")
    secret = "private-tool-state-" + uuid4().hex
    store.add_agent_traces(conv, message, [{"kind": "final", "content": "ordinary answer"}])
    store.save_tool_state(conv, message, "scope", payload(secret), origin="origin-" + secret)
    with sessions() as session:
        summaries = list(session.scalars(select(AgentTraceSummary).where(AgentTraceSummary.conversation_id == conv)))
        assert len(summaries) == 1 and summaries[0].kind == "final"
        assert all(secret not in str(getattr(row, column.name)) for row in summaries for column in AgentTraceSummary.__table__.columns)
    assert store.delete_conversation(conv)
    with sessions() as session:
        assert session.scalar(select(AgentTraceSummary.kind).where(AgentTraceSummary.conversation_id == conv)) == "final"
        assert session.scalar(select(AgentTrace.id).where(AgentTrace.conversation_id == conv)) is None


def test_current_document_versions_filter_unavailable_states_and_follow_activation(state_database):
    store, sessions, prefix = state_database
    ids = {}
    with sessions.begin() as session:
        for label, status, has_active in [("active", "indexed", True), ("missing", "indexed", False),
                                          ("deleting", "deleting", True), ("deleted", "deleted", True),
                                          ("uploaded", "uploaded", True)]:
            doc_id = prefix + "-" + label
            ids[label] = doc_id
            session.add(Document(id=doc_id, original_filename=label + ".pdf", stored_filename=label + ".pdf",
                                 status=status, source_available=True))
        session.flush()
        for label, doc_id in ids.items():
            if label == "missing":
                continue
            version_id = doc_id + "-v1"
            session.add(DocumentVersion(id=version_id, document_id=doc_id, version_number=1,
                                        status="active", chunking_config={}))
            session.get(Document, doc_id).active_version_id = version_id
    assert store.state_document_versions(set()) == {}
    assert store.state_document_versions({*ids.values(), prefix + "-absent"}) == {ids["active"]: ids["active"] + "-v1"}
    with sessions.begin() as session:
        session.get(DocumentVersion, ids["active"] + "-v1").status = "superseded"
        new_version = ids["active"] + "-v2"
        session.add(DocumentVersion(id=new_version, document_id=ids["active"], version_number=2,
                                    status="active", chunking_config={}))
        session.get(Document, ids["active"]).active_version_id = new_version
    assert PostgresAuxiliaryStore(sessions).state_document_versions({ids["active"]}) == {ids["active"]: new_version}


def test_concurrent_saves_of_one_answer_leave_one_complete_envelope(state_database):
    store, sessions, prefix = state_database
    conv = conversation(store, prefix)
    message = store.add_message(conv, "assistant", "one persisted answer")
    ready = Barrier(2, timeout=10)
    def save(content):
        ready.wait()
        PostgresAuxiliaryStore(sessions).save_tool_state(conv, message, "scope", payload(content))
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(save, "first complete result")
        second = executor.submit(save, "second complete result")
        first.result(timeout=20)
        second.result(timeout=20)
    assert len(state_rows(sessions, conv)) == 1
    loaded = store.load_tool_states(conv, "scope", message_ids=[message])
    assert len(loaded) == 1
    assert loaded[0]["payload"] in [payload("first complete result"), payload("second complete result")]
