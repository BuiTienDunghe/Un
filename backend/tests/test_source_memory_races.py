"""Real PostgreSQL contention: source/ledger lifetimes share one transaction."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
import time
from uuid import uuid4

from sqlalchemy import select

from app.discord.history_service import DiscordHistoryService
from app.postgres.models import DiscordChannelMessage, SourceMemory
from app.services.source_memory import MemoryReader
from tests.test_source_memory import memory  # noqa: F401


def test_concurrent_edit_delete_and_record_delete_never_resurrect(memory):
    history = DiscordHistoryService(memory.sessions)
    history.source_memory = memory
    guild = 'race-'+uuid4().hex[:10]
    reader = MemoryReader.discord(guild, 'one', None, 'alice')
    for index in range(12):
        key = str(((int(time.time()*1000)-1420070400000)<<22)+index)
        text = 'Hãy nhớ tôi không dùng mã cũ'
        if index % 2 == 0:
            assert history.record_message(guild_id=guild,channel_id='one',thread_id=None,
                discord_message_id=key,author_id='alice',author_display_name='Alice',is_bot=False,content=text)
            memory.save(reader,text,source_id=f'discord:{key}')
        barrier = Barrier(2)
        def writer():
            barrier.wait(timeout=5)
            if index % 2 == 0:
                return history.record_edit(discord_message_id=key,content='đã sửa',source_edited_at=datetime.now(UTC))
            return history.record_message(guild_id=guild,channel_id='one',thread_id=None,
                discord_message_id=key,author_id='alice',author_display_name='Alice',is_bot=False,content=text)
        def deleter():
            barrier.wait(timeout=5)
            return history.record_delete(discord_message_id=key,guild_id=guild,channel_id='one')
        with ThreadPoolExecutor(max_workers=2) as executor:
            a,b = executor.submit(writer),executor.submit(deleter)
            a.result(timeout=10)
            assert b.result(timeout=10)
        with memory.sessions() as db:
            row = db.scalar(select(DiscordChannelMessage).where(DiscordChannelMessage.discord_message_id==key))
            assert row.deleted_at is not None and row.content is None
            source = db.get(SourceMemory, f'discord:{key}')
            assert source.status == 'retracted' and source.content == ''


def test_history_tool_checks_tombstone_when_delete_had_no_scope_metadata(memory):
    import json
    from app.discord.source_memory import ScopedSearchHistory
    history = DiscordHistoryService(memory.sessions)
    history.source_memory = memory
    guild = 'delayed-'+uuid4().hex[:10]
    reader = MemoryReader.discord(guild, 'one', None, 'alice')
    key = str(((int(time.time()*1000)-1420070400000)<<22))
    assert not history.record_delete(discord_message_id=key)
    assert history.record_message(guild_id=guild,channel_id='one',thread_id=None,
        discord_message_id=key,author_id='alice',author_display_name='Alice',is_bot=False,
        content='sentinel-deleted-history-327')
    class Output:
        def _dump(self, value, **kwargs): return json.dumps(value)
        def _error(self, *args): raise AssertionError(args)
    result, _, _ = ScopedSearchHistory(memory, history)(Output(), {'query':'sentinel-deleted-history-327'},
        {'_memory_reader':reader, 'guild_id':guild, 'channel_id':'one', 'thread_id':None})
    assert 'sentinel-deleted-history-327' not in result
