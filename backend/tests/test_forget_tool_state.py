"""Forgetting revokes whole machine envelopes in scope, with an honest recount."""
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.postgres.models import AgentTrace, Conversation, DiscordConversationSession, DiscordSessionTurn, Message
from scripts.forget_member import forget
from tests.test_forget_member_copies import factory, world

pytestmark = pytest.mark.skipif(not os.getenv("POSTGRES_TEST_URL"), reason="set POSTGRES_TEST_URL")


@pytest.fixture
def envelopes(factory, world):
    other_conversation, other_session = uuid4(), uuid4()
    other_guild = world["guild"] + "-outside"
    def add_state(database, conversation, content):
        message_id = database.scalar(select(Message.id).where(Message.conversation_id == str(conversation), Message.role == "assistant").limit(1))
        if message_id is None:
            message = Message(conversation_id=str(conversation), role="assistant", content="saved answer")
            database.add(message)
            database.flush()
            message_id = message.id
        row = AgentTrace(conversation_id=str(conversation), message_id=message_id, step_index=-1, kind="tool_state",
                         content=json.dumps({"v": 1, "groups": [{"name": "search_history", "content": content}]}),
                         arguments={"scope_key": "private state routing", "origin": str(uuid4())})
        database.add(row)
        database.flush()
        return row.id
    with factory.begin() as database:
        database.add(Conversation(id=str(other_conversation)))
        database.add(DiscordConversationSession(id=other_session, guild_id=other_guild, channel_id="c2", backend_conversation_id=other_conversation))
        database.flush()
        database.add(DiscordSessionTurn(id=uuid4(), session_id=other_session, discord_message_id=str(uuid4()), sequence_number=1,
                                       request_text="private outside request", response_text="saved outside answer", author_id=world["a"],
                                       author_display_name="Outside", status="completed"))
        scoped_id = add_state(database, world["conversation"], "derived observation from another speaker")
        outside_id = add_state(database, other_conversation, "private outside state")
    yield scoped_id, outside_id
    with factory.begin() as database:
        database.execute(delete(DiscordConversationSession).where(DiscordConversationSession.id == other_session))
        database.execute(delete(Conversation).where(Conversation.id == str(other_conversation)))


def stored_envelopes(factory, identifiers):
    with factory() as database:
        return {row.id: (row.content, row.arguments) for row in database.scalars(select(AgentTrace).where(AgentTrace.id.in_(identifiers)))}


def test_dry_run_counts_a_whole_envelope_once_and_keeps_both_fields(factory, world, envelopes):
    before = stored_envelopes(factory, envelopes)
    report = forget(world["guild"], world["a"], apply=False)
    assert report["planned"]["agent_trace_steps"] == 4  # three legacy copies, one envelope with two fields
    assert report["side_effects"] is False
    assert stored_envelopes(factory, envelopes) == before


def test_apply_clears_content_and_routing_in_scope_but_leaves_other_guild(factory, world, envelopes):
    scoped, outside = envelopes
    before = stored_envelopes(factory, envelopes)
    report = forget(world["guild"], world["a"], apply=True)
    after = stored_envelopes(factory, envelopes)
    assert after[scoped] == (None, None)
    assert after[outside] == before[outside]
    assert report["copies_rewritten"]["agent_trace_steps"] == 4
    assert not any(report["remaining"].values())
    again = forget(world["guild"], world["a"], apply=True)
    assert again["planned"]["agent_trace_steps"] == 0
    assert again["copies_rewritten"]["agent_trace_steps"] == 0


def test_all_guilds_explicitly_revokes_each_guild_envelope(factory, world, envelopes):
    report = forget(world["guild"], world["a"], apply=True, all_guilds=True)
    assert all(values == (None, None) for values in stored_envelopes(factory, envelopes).values())
    assert not any(report["remaining"].values())


def test_deleting_the_conversation_cascades_raw_tool_state(factory, world, envelopes):
    with factory.begin() as database:
        database.execute(delete(Conversation).where(Conversation.id == world["conversation"]))
    assert envelopes[0] not in stored_envelopes(factory, envelopes)
