"""Repro (not committed): a reply turn crashes after claim; does it block the channel?

Second-opinion check 10/11 on main ed60401. Seeds the same `__history__` barrier the
20261109_39 migration seeds for every existing guild, then sends a reply turn of each kind.
"""
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from test_source_memory_discord import v2client  # noqa: F401  (fixture)


def snowflake():
    return str(((int(time.time() * 1000) - 1420070400000) << 22) + int(uuid4().hex[:5], 16))


def session_of(client, guild, channel):
    return client.post('/api/discord/sessions/resolve', json={
        'guild_id': guild, 'channel_id': channel, 'thread_id': None}).json()['session_id']


def enqueue(client, guild, channel, body, reply_to=None):
    message_id = snowflake()
    payload = {'discord_message_id': message_id, 'message': body, 'author_id': 'alice',
               'author_display_name': 'Alice'}
    if reply_to:
        payload['reply_to_discord_message_id'] = reply_to
    created = client.post(f'/api/discord/sessions/{session_of(client, guild, channel)}/turns', json=payload)
    assert created.status_code in (200, 201), created.text
    return message_id, created.json()['turn_id']


def finished_turn(client, guild, channel, body):
    message_id, turn_id = enqueue(client, guild, channel, body)
    executed = client.post(f'/api/discord/sessions/turns/{turn_id}/execute')
    assert executed.status_code == 200, executed.text
    response_id = 'response-' + uuid4().hex
    done = client.post(f'/api/discord/sessions/turns/{turn_id}/complete', json={
        'execution_token': executed.json()['execution_token'], 'discord_response_message_ids': [response_id]})
    assert done.status_code == 200, done.text
    return message_id, response_id


def seed_history_barrier(client, guild):
    # Same statement shape as the migration (line 38), for one guild.
    with client.app.state.postgres_sessions.begin() as db:
        db.execute(text("""INSERT INTO source_memory_states (tenant, audience, epoch, barrier_at)
            VALUES (:t, '__history__', 1, clock_timestamp())
            ON CONFLICT (tenant, audience) DO UPDATE SET epoch = source_memory_states.epoch + 1,
            barrier_at = clock_timestamp()"""), {'t': f'discord:{guild}'})


def turn_row(client, turn_id):
    with client.app.state.postgres_sessions() as db:
        return db.execute(text('SELECT status, attempt_count, lease_expires_at FROM discord_session_turns WHERE id = :i'),
                          {'i': UUID(turn_id)}).one()


@pytest.mark.parametrize('target', ['user_message', 'bot_response', 'not_found'])
def test_reply_crash_then_plain_message(v2client, target):  # noqa: F811
    client, captured, guild = v2client
    user_message, bot_response = finished_turn(client, guild, 'one', 'Câu cũ trước khi nâng cấp.')
    seed_history_barrier(client, guild)
    reply_to = {'user_message': user_message, 'bot_response': bot_response, 'not_found': snowflake()}[target]
    _, reply_turn = enqueue(client, guild, 'one', 'Trả lời tin kia.', reply_to=reply_to)
    calls = len(captured)
    with pytest.raises(AttributeError) as crash:
        client.post(f'/api/discord/sessions/turns/{reply_turn}/execute')
    print(f'\n[{target}] crash: {crash.value}')
    assert len(captured) == calls, 'crash happens before the model call'
    status, attempts, _ = turn_row(client, reply_turn)
    print(f'[{target}] reply turn after crash: status={status} attempts={attempts}')
    assert status == 'running'

    _, plain_turn = enqueue(client, guild, 'one', 'Tin thường gửi tiếp.')
    first = client.post(f'/api/discord/sessions/turns/{plain_turn}/execute')
    print(f'[{target}] plain turn while lease holds: http={first.status_code} status={first.json()["status"]}')
    assert first.json()['status'] == 'queued' and len(captured) == calls

    # The bot gives up on a 500 and never asks for that turn again; let its lease expire.
    with client.app.state.postgres_sessions.begin() as db:
        db.execute(text('UPDATE discord_session_turns SET lease_expires_at = :t WHERE id = :i'),
                   {'t': datetime.now(UTC) - timedelta(seconds=1), 'i': UUID(reply_turn)})
    for _ in range(3):
        again = client.post(f'/api/discord/sessions/turns/{plain_turn}/execute')
    status, attempts, _ = turn_row(client, reply_turn)
    print(f'[{target}] after lease expiry + 3 polls: reply={status}/{attempts} plain={again.json()["status"]}')
    assert again.json()['status'] == 'queued' and len(captured) == calls
    assert status == 'queued'

    # Other channels in the same guild are not blocked.
    _, other = enqueue(client, guild, 'two', 'Kênh khác.')
    other_run = client.post(f'/api/discord/sessions/turns/{other}/execute')
    print(f'[{target}] other channel: status={other_run.json()["status"]}')
    assert other_run.json()['status'] == 'running'
