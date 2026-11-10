"""Repro (not committed to backend/tests): does the bot editing its own ⏳ message move the channel barrier?

Opus 5.5 finding B, 10/11 on main ed60401. The bot ledgers every message in a listened public channel,
its own included (discord_bot/main.py:919-925, is_bot=True), and ships every edit with content
(main.py:964-978). The progress message is posted after a delay and edited (progress_message.py:92,155).
"""
import json
import time
from uuid import uuid4

from test_source_memory_discord import send, v2client  # noqa: F401  (fixture)


def snowflake():
    return str(((int(time.time() * 1000) - 1420070400000) << 22) + int(uuid4().hex[:5], 16))


def test_bot_editing_its_own_progress_message(v2client):  # noqa: F811
    client, captured, guild = v2client
    svc = client.app.state.source_memory_service
    from app.services.source_memory import MemoryReader
    reader = MemoryReader.discord(guild, 'one', None, 'alice')

    send(client, guild, 'one', 'Mật mã của tôi là sentinel-history-314.')
    send(client, guild, 'one', 'Nhắc lại câu trước giúp tôi.')
    before = json.dumps(captured[-1], ensure_ascii=False)
    print('\nhistory carries the earlier turn before the bot edit:', 'sentinel-history-314' in before)
    _, barrier_before = svc.snapshot(reader)

    # The bot posts "⏳" in the channel; the bot ships it to the ledger like any heard message.
    bot_message = snowflake()
    recorded = client.post('/api/discord/history/messages', json={
        'guild_id': guild, 'channel_id': 'one', 'thread_id': None, 'discord_message_id': bot_message,
        'author_id': 'un-bot', 'author_display_name': 'Ún', 'is_bot': True, 'content': '⏳ Đang đọc tài liệu…',
        'reply_to_message_id': None})
    print('ledger write of the bot message:', recorded.status_code, recorded.json())
    # The progress message is edited (next step label, then the answer replaces it).
    edited = client.post(f'/api/discord/history/messages/{bot_message}/edit', json={'content': 'Câu trả lời cuối.'})
    print('ledger edit of the bot message:', edited.status_code, edited.json())
    _, barrier_after = svc.snapshot(reader)
    print('channel barrier before/after:', barrier_before, '->', barrier_after)

    send(client, guild, 'one', 'Mật mã của tôi là gì?')
    after = json.dumps(captured[-1], ensure_ascii=False)
    print('history carries the earlier turn after the bot edit:', 'sentinel-history-314' in after)
    assert 'sentinel-history-314' in before
    assert barrier_after != barrier_before
    assert 'sentinel-history-314' not in after
