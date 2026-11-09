"""Discord adapters: authority comes from persisted turn metadata, never arguments."""
import re

from sqlalchemy import func, select

from app.postgres.models import DiscordChannelMessage, DiscordConversationSession, DiscordSessionTurn, SourceMemory
from app.services.agent_service import AgentTool, TOOL_UNAVAILABLE_HERE, BAD_ARGUMENTS
from app.services.source_memory import MemoryReader, explicit_remember, explicit_forget, MemoryConflict, SourceMemoryNotFound
from app.discord.history_service import _hit, _or_query_text


def reader_for(session, turn):
    return MemoryReader.discord(session.guild_id, session.channel_id, session.thread_id, turn.author_id or "")

# prepare_turn's answer for a turn queued before a barrier (its message deleted or edited,
# or its memory forgotten): the turn service stops on it and never calls the model.
STALE_TURN = "Lượt cũ đã bị vô hiệu hóa; không phát lại thao tác ghi/quên."
STALE_TURN_REPLY = ("Tin này đã bị xoá, sửa hoặc trí nhớ vừa được quên trước khi Ún kịp trả lời, "
                    "nên Ún không xử lý nó. Bạn gửi lại nếu vẫn cần nhé.")


def prepare_turn(memory, session, turn):
    reader = reader_for(session, turn)
    # request_text may have an appended image slip. Only the typed prefix counts.
    from app.services.agent_service import IMAGE_NOTE
    text = turn.request_text.split(IMAGE_NOTE, 1)[0]
    receipt = ""
    epoch, barrier = memory.snapshot(reader)
    if (barrier and turn.created_at <= barrier) or memory.is_retracted(f"discord:{turn.discord_message_id}"):
        return reader, STALE_TURN
    if explicit_forget(text):
        count = memory.forget_actor(reader.tenant, reader.actor)
        receipt = f"Backend đã quên {count} nguồn được lưu về người đang nói."
    elif reader.actor and explicit_remember(text):
        try:
            item = memory.save(reader, text, source_id=f"discord:{turn.discord_message_id}", expected_epoch=epoch)
            receipt = f"Backend đã lưu nguyên văn source_id={item['id']} revision={item['revision']}."
        except (MemoryConflict, SourceMemoryNotFound):
            receipt = "Nguồn này đã bị sửa/xóa/quên; backend từ chối lưu lại bản cũ."
    return reader, receipt


class ScopedSearchHistory:
    def __init__(self, memory, history):
        self.memory, self.history = memory, history

    def __call__(self, service, arguments, context):
        reader = (context or {}).get("_memory_reader")
        if not isinstance(reader, MemoryReader) or not reader.tenant.startswith("discord:"):
            return service._error(TOOL_UNAVAILABLE_HERE, "Không có phạm vi Discord đáng tin cậy để đọc lịch sử.")
        _, barrier = self.memory.snapshot(reader)
        query = str(arguments.get("query") or "").strip()
        author = str(arguments.get("author_id") or "").strip()
        conditions = [DiscordChannelMessage.guild_id == str((context or {}).get("guild_id")),
            DiscordChannelMessage.channel_id == (context or {}).get("channel_id"),
            DiscordChannelMessage.thread_id == (context or {}).get("thread_id"),
            DiscordChannelMessage.deleted_at.is_(None), DiscordChannelMessage.content.is_not(None),
            ~select(SourceMemory.id).where(
                SourceMemory.id == func.concat("discord:", DiscordChannelMessage.discord_message_id),
                SourceMemory.status == "retracted").exists()]
        if barrier:
            conditions.append(DiscordChannelMessage.sent_at > barrier)
        if author:
            conditions.append(DiscordChannelMessage.author_id == author)
        try:
            limit = min(max(int(arguments.get("limit", 5 if query else 20)), 1), 10 if query else 25)
            days = min(max(int(arguments.get("days") or 0), 0), 3650)
        except (TypeError, ValueError):
            return service._error(BAD_ARGUMENTS, "limit/days phải là số nguyên.")
        if days:
            conditions.append(DiscordChannelMessage.sent_at >= func.now() - func.make_interval(0, 0, 0, days))
        order = [DiscordChannelMessage.sent_at.desc(), DiscordChannelMessage.id.desc()]
        if query:
            token_query = _or_query_text(query)
            if not token_query:
                return service._dump({"result": "không đủ từ khóa"}), None, None
            tsquery = func.to_tsquery("simple", token_query)
            conditions.append(DiscordChannelMessage.content_tokens.op("@@")(tsquery))
            order.insert(0, func.ts_rank(DiscordChannelMessage.content_tokens, tsquery).desc())
        with self.history.sessions() as database:
            rows = list(database.scalars(select(DiscordChannelMessage).where(*conditions).order_by(*order).limit(limit)))
            if not query:
                rows.reverse()
            # Whole quotes only: no suffix clipping that could drop a negation.
            payload, chars = [], 0
            for row in rows:
                hit = _hit(row)
                item = {"source_id": f"discord:{hit.discord_message_id}", "message": hit.content,
                    "author_id": hit.author_id, "sent_at": hit.sent_at.isoformat(), "link": hit.link}
                if chars + len(hit.content) + 300 <= 4800:
                    payload.append(item)
                    chars += len(hit.content) + 300
        return service._dump(payload or {"result": "Không có nguồn còn hiệu lực trong kênh/luồng này."}), None, None


class SourceRemember:
    def __init__(self, memory, sessions):
        self.memory, self.sessions = memory, sessions

    def __call__(self, service, arguments, context):
        from uuid import UUID
        try:
            turn_id = UUID(str((context or {}).get("turn_id")))
        except ValueError:
            return service._error(TOOL_UNAVAILABLE_HERE, "Không có lượt Discord để xác minh người yêu cầu.")
        with self.sessions() as database:
            turn = database.get(DiscordSessionTurn, turn_id)
            session = database.get(DiscordConversationSession, turn.session_id) if turn else None
            if session is None or not turn.author_id or not explicit_remember(turn.request_text):
                return service._error(BAD_ARGUMENTS, "Chỉ lưu khi chính người nói mở đầu bằng yêu cầu ghi nhớ.")
            # Ignore arguments.fact entirely; the model cannot remove 'không'.
            reader, receipt = prepare_turn(self.memory, session, turn)
        return service._dump({"receipt": receipt, "wording": "source_verbatim"}), None, None


def register_tools(registry, memory, history, sessions):
    from app.discord.agent_tools import SEARCH_HISTORY_SCHEMA, ORDER
    from app.discord.remember_tool import REMEMBER_SCHEMA, ORDER as REMEMBER_ORDER
    registry.register(AgentTool(SEARCH_HISTORY_SCHEMA, ScopedSearchHistory(memory, history),
        "Đang tìm nguồn trong kênh này…", state_policy="read"), ORDER)
    registry.register(AgentTool(REMEMBER_SCHEMA, SourceRemember(memory, sessions),
        "Đang kiểm tra nguồn đã lưu…", state_policy="receipt"), REMEMBER_ORDER)
