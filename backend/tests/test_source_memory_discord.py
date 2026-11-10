"""Cold-start composition and actual Discord HTTP turn lifecycle in v2 mode."""
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def v2client(monkeypatch, mock_ollama):
    from app.config.settings import get_settings
    from app.main import app
    if not __import__('os').environ.get('POSTGRES_TEST_URL'):
        pytest.skip('POSTGRES_TEST_URL required')
    get_settings.cache_clear()
    monkeypatch.setenv('SOURCE_MEMORY_ENABLED', 'true')
    monkeypatch.setenv('DISCORD_AGENT_TOOLS_ENABLED', 'false')
    captured = []
    def generate(self, model, messages, options, keep_alive, think=None):
        captured.append(messages)
        return 'Đã xử lý theo nguồn hiện tại.'
    monkeypatch.setattr('app.llm_clients.ollama_client.OllamaClient.chat', generate)
    guild = 'source-v2-'+uuid4().hex[:10]
    try:
        with TestClient(app) as client:
            yield client, captured, guild
    finally:
        from sqlalchemy import delete, select
        from app.postgres.models import DiscordConversationSession, Conversation
        with app.state.postgres_sessions.begin() as db:
            ids = list(db.scalars(select(DiscordConversationSession.backend_conversation_id).where(
                DiscordConversationSession.guild_id == guild)))
            db.execute(delete(DiscordConversationSession).where(DiscordConversationSession.guild_id == guild))
            if ids:
                db.execute(delete(Conversation).where(Conversation.id.in_([str(i) for i in ids])) )
        get_settings.cache_clear()


def send(client, guild, channel, text):
    resolved = client.post('/api/discord/sessions/resolve', json={
        'guild_id':guild, 'channel_id':channel, 'thread_id':None})
    assert resolved.status_code == 200, resolved.text
    session = resolved.json()['session_id']
    message_id = str(((int(time.time()*1000)-1420070400000)<<22) + int(uuid4().hex[:5],16))
    created = client.post(f'/api/discord/sessions/{session}/turns', json={
        'discord_message_id':message_id, 'message':text, 'author_id':'alice', 'author_display_name':'Alice'})
    assert created.status_code in (200, 201), created.text
    turn_id = created.json()['turn_id']
    executed = client.post(f'/api/discord/sessions/turns/{turn_id}/execute')
    assert executed.status_code == 200 and executed.json().get('answer'), executed.text
    completed = client.post(f'/api/discord/sessions/turns/{turn_id}/complete', json={
        'execution_token':executed.json()['execution_token'], 'discord_response_message_ids':['response-'+uuid4().hex]})
    assert completed.status_code == 200, completed.text
    return message_id, turn_id


def test_discord_composition_scope_edit_and_forget(v2client):
    client, captured, guild = v2client
    svc = client.app.state.source_memory_service
    assert svc is not None
    registry = client.app.state.agent_service.registry
    assert type(registry.get('remember').run).__name__ == 'SourceRemember'
    assert type(registry.get('search_history').run).__name__ == 'ScopedSearchHistory'
    message_id, _ = send(client, guild, 'one', 'Hãy nhớ tôi không thích cà phê sentinel-cafe-982.')
    send(client, guild, 'one', 'Tôi thích cà phê nào?')
    assert 'sentinel-cafe-982' in json.dumps(captured[-1], ensure_ascii=False)
    send(client, guild, 'two', 'Tôi thích cà phê nào?')
    assert 'sentinel-cafe-982' not in json.dumps(captured[-1], ensure_ascii=False)
    # A note can originate from a bot turn in a channel with no passive ledger.
    client.post(f'/api/discord/history/messages/{message_id}/edit', json={'content':'đã sửa'})
    send(client, guild, 'one', 'Tôi thích cà phê nào?')
    assert 'sentinel-cafe-982' not in json.dumps(captured[-1], ensure_ascii=False)
    send(client, guild, 'one', 'Hãy nhớ mã riêng tư sentinel-tea-021.')
    send(client, guild, 'one', 'Hãy quên toàn bộ trí nhớ về tôi')
    send(client, guild, 'one', 'Mã riêng tư của tôi là gì?')
    assert 'sentinel-tea-021' not in json.dumps(captured[-1], ensure_ascii=False)


def test_web_auto_capture_and_forget(v2client):
    client, captured, _ = v2client
    first = client.post('/chat', json={'message':'Hãy nhớ tôi không uống trà sentinel-web-633.', 'use_memory':True})
    assert first.status_code == 200, first.text
    cid = first.json()['conversation_id']
    notes = client.get('/memory/notes').json()
    assert any(row['content'].endswith('sentinel-web-633.') for row in notes)
    forgotten = client.post('/chat', json={'message':'Hãy quên toàn bộ trí nhớ về tôi', 'conversation_id':cid})
    assert forgotten.status_code == 200, forgotten.text
    client.post('/chat', json={'message':'Tôi có lưu điều gì?', 'conversation_id':cid, 'use_memory':True})
    assert 'sentinel-web-633' not in json.dumps(captured[-1], ensure_ascii=False)


def queue(client, guild, channel, text, author='alice'):
    session = client.post('/api/discord/sessions/resolve', json={
        'guild_id':guild, 'channel_id':channel, 'thread_id':None}).json()['session_id']
    message_id = str(((int(time.time()*1000)-1420070400000)<<22) + int(uuid4().hex[:5],16))
    created = client.post(f'/api/discord/sessions/{session}/turns', json={
        'discord_message_id':message_id, 'message':text, 'author_id':author, 'author_display_name':author})
    assert created.status_code in (200, 201), created.text
    return message_id, created.json()['turn_id']


@pytest.mark.parametrize('revoke', ['delete', 'edit', 'forget'])
def test_a_turn_revoked_while_queued_never_reaches_the_model(v2client, revoke):
    # Review 10/11 (P1): prepare_turn noticed the stale turn, but execute still sent
    # the old request to the model. It now ends on one fixed sentence.
    from app.discord.source_memory import STALE_TURN_REPLY
    client, captured, guild = v2client
    message_id, turn_id = queue(client, guild, 'one', 'Hãy nhớ mã riêng sentinel-queued-57.')
    if revoke == 'delete':
        client.post(f'/api/discord/history/messages/{message_id}/delete', json={'guild_id':guild, 'channel_id':'one'})
    elif revoke == 'edit':
        client.post(f'/api/discord/history/messages/{message_id}/edit', json={'content':'đã sửa'})
    else:
        client.app.state.source_memory_service.forget_actor(f'discord:{guild}', 'alice')
    calls = len(captured)
    executed = client.post(f'/api/discord/sessions/turns/{turn_id}/execute')
    assert executed.status_code == 200, executed.text
    assert executed.json()['answer'] == STALE_TURN_REPLY
    assert len(captured) == calls
    completed = client.post(f'/api/discord/sessions/turns/{turn_id}/complete', json={
        'execution_token':executed.json()['execution_token'], 'discord_response_message_ids':['response-'+uuid4().hex]})
    assert completed.status_code == 200, completed.text
    # The next, fresh turn still answers normally and never sees the revoked words.
    send(client, guild, 'one', 'Mã riêng của tôi là gì?')
    assert len(captured) == calls + 1
    assert 'sentinel-queued-57' not in json.dumps(captured[-1], ensure_ascii=False)


def ledger(client, guild, channel, author, content, *, bot=False):
    message_id = str(((int(time.time()*1000)-1420070400000)<<22) + int(uuid4().hex[:5],16))
    recorded = client.post('/api/discord/history/messages', json={
        'guild_id':guild, 'channel_id':channel, 'thread_id':None, 'discord_message_id':message_id,
        'author_id':author, 'author_display_name':author, 'is_bot':bot, 'content':content,
        'reply_to_message_id':None})
    assert recorded.status_code == 200 and recorded.json()['recorded'], recorded.text
    return message_id


def channel_barrier(client, guild, channel):
    from app.services.source_memory import MemoryReader
    return client.app.state.source_memory_service.snapshot(MemoryReader.discord(guild, channel, None, 'alice'))[1]


@pytest.mark.parametrize('change', ['edit', 'delete'])
def test_the_bots_own_edits_and_deletes_keep_the_channel_history(v2client, change):
    # Review 10/11 (finding B): the bot edits its "⏳" progress message into the answer and
    # deletes it when discarded. Each event moved the channel barrier, so the next turn
    # lost the whole channel history. A bot's message is never a memory source.
    client, captured, guild = v2client
    send(client, guild, 'one', 'Mật mã của tôi là sentinel-history-314.')
    before = channel_barrier(client, guild, 'one')
    progress = ledger(client, guild, 'one', 'un-bot', 'Đang đọc tài liệu…', bot=True)
    if change == 'edit':
        client.post(f'/api/discord/history/messages/{progress}/edit', json={'content':'Câu trả lời cuối.'})
    else:
        client.post(f'/api/discord/history/messages/{progress}/delete', json={'guild_id':guild, 'channel_id':'one'})
    assert channel_barrier(client, guild, 'one') == before
    send(client, guild, 'one', 'Mật mã của tôi là gì?')
    assert 'sentinel-history-314' in json.dumps(captured[-1], ensure_ascii=False)


def test_an_edit_that_keeps_the_text_keeps_the_channel_history(v2client):
    # A link preview arrives as an edit event carrying the same text; only a real change revokes.
    client, captured, guild = v2client
    send(client, guild, 'one', 'Mật mã của tôi là sentinel-history-271.')
    note = ledger(client, guild, 'one', 'bob', 'Mai họp lúc 9h, xem link này.')
    before = channel_barrier(client, guild, 'one')
    client.post(f'/api/discord/history/messages/{note}/edit', json={'content':'Mai họp lúc 9h, xem link này.'})
    assert channel_barrier(client, guild, 'one') == before
    send(client, guild, 'one', 'Mật mã của tôi là gì?')
    assert 'sentinel-history-271' in json.dumps(captured[-1], ensure_ascii=False)
    # A person changing the words still revokes, as before.
    client.post(f'/api/discord/history/messages/{note}/edit', json={'content':'Mai họp lúc 10h.'})
    assert channel_barrier(client, guild, 'one') != before
