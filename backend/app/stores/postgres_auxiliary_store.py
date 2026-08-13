"""PostgreSQL persistence for the six auxiliary SQLite domains.

This adapter intentionally mirrors only the methods currently consumed by the
chat, memory, OCR-console and request-log services.  It does not own document
pipeline data and it does not implement a fallback to SQLite.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import String, cast, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from app.postgres.models import Conversation, DiscordConversationSession, Memory, Message, OcrCache, OcrRun, RequestLog


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PostgresAuxiliaryStore:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sessions = session_factory

    def healthcheck(self) -> bool:
        try:
            with self._sessions() as session:
                session.scalar(select(1))
            return True
        except Exception:
            return False

    # Conversations and messages must use the same transaction/backend.
    def conversation_exists(self, conversation_id: str) -> bool:
        with self._sessions() as session:
            return session.get(Conversation, conversation_id) is not None

    def create_conversation(self, conversation_id: str) -> None:
        now = _utc_now()
        with self._sessions.begin() as session:
            session.add(Conversation(id=conversation_id, created_at=now, updated_at=now))

    def add_message(self, conversation_id: str, role: str, content: str, model_used: str | None = None) -> None:
        now = _utc_now()
        with self._sessions.begin() as session:
            session.add(Message(conversation_id=conversation_id, role=role, content=content, model_used=model_used, created_at=now))
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.updated_at = now

    def get_messages(self, conversation_id: str, limit: int) -> list[dict[str, str]]:
        with self._sessions() as session:
            rows = list(session.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.desc()).limit(limit)))
        rows.reverse()
        return [{"role": row.role, "content": row.content} for row in rows]

    def list_conversations(self) -> list[dict[str, object]]:
        with self._sessions() as session:
            rows = session.execute(
                select(Conversation.id, Conversation.created_at, Conversation.updated_at, func.count(Message.id).label("message_count"))
                .outerjoin(Message, Message.conversation_id == Conversation.id)
                .where(
                    ~exists(
                        select(DiscordConversationSession.id).where(
                            cast(DiscordConversationSession.backend_conversation_id, String) == Conversation.id,
                            DiscordConversationSession.origin == "discord",
                        )
                    )
                )
                .group_by(Conversation.id, Conversation.created_at, Conversation.updated_at)
                .order_by(Conversation.updated_at.desc())
            ).all()
        return [{"id": row.id, "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(), "message_count": row.message_count} for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, object] | None:
        with self._sessions() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return None
            messages = list(session.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)))
            return {
                "id": conversation.id,
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
                "messages": [{"role": row.role, "content": row.content, "model_used": row.model_used, "created_at": row.created_at.isoformat()} for row in messages],
            }

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._sessions.begin() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            session.delete(conversation)  # database FK performs the existing cascade contract
            return True

    # Memories: vectors remain the existing Qdrant responsibility in MemoryService.
    def create_memory(self, memory_id: str, content: str, memory_type: str, importance: float) -> None:
        now = _utc_now()
        with self._sessions.begin() as session:
            session.add(Memory(id=memory_id, content=content, memory_type=memory_type, importance=importance, metadata_json={}, created_at=now, updated_at=now))

    def get_memory(self, memory_id: str) -> dict[str, object] | None:
        with self._sessions() as session:
            row = session.get(Memory, memory_id)
            if row is None:
                return None
            return {"id": row.id, "content": row.content, "memory_type": row.memory_type, "importance": row.importance, "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}

    def update_memory(self, memory_id: str, content: str, memory_type: str, importance: float) -> bool:
        with self._sessions.begin() as session:
            row = session.get(Memory, memory_id)
            if row is None:
                return False
            row.content, row.memory_type, row.importance, row.updated_at = content, memory_type, importance, _utc_now()
            return True

    def delete_memory(self, memory_id: str) -> bool:
        with self._sessions.begin() as session:
            row = session.get(Memory, memory_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def log_request(self, endpoint: str, model_used: str | None, latency_ms: int, status: str, error_code: str | None = None) -> None:
        with self._sessions.begin() as session:
            session.add(RequestLog(endpoint=endpoint, model_used=model_used, latency_ms=latency_ms, status=status, error_code=error_code, created_at=_utc_now()))

    # OCR-console run payload is persisted as its complete JSON object.
    def save_ocr_run(self, run_id: str, filename: str, status: str, model: str, result_json: str) -> None:
        try:
            payload = json.loads(result_json)
        except json.JSONDecodeError as error:
            raise ValueError("OCR run result_json must be valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("OCR run result_json must be a JSON object")
        now = _utc_now()
        statement = insert(OcrRun).values(id=run_id, filename=filename, status=status, model=model, result_json=payload, created_at=now, updated_at=now).on_conflict_do_update(
            index_elements=["id"], set_={"filename": filename, "status": status, "model": model, "result_json": payload, "updated_at": now}
        )
        with self._sessions.begin() as session:
            session.execute(statement)

    def list_ocr_runs(self) -> list[dict[str, object]]:
        with self._sessions() as session:
            rows = list(session.scalars(select(OcrRun).order_by(OcrRun.updated_at.desc())))
        return [{"id": row.id, "filename": row.filename, "status": row.status, "model": row.model, "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(), "result_json": json.dumps(row.result_json, ensure_ascii=False)} for row in rows]

    def delete_ocr_run(self, run_id: str) -> bool:
        with self._sessions.begin() as session:
            row = session.get(OcrRun, run_id)
            if row is None:
                return False
            session.delete(row)
            return True

    # PostgreSQL OCR cache never infers key components missing from the caller.
    def get_ocr_cache_with_key(self, input_hash: str, engine: str, model_name: str, model_revision: str, config_fingerprint: str) -> str | None:
        with self._sessions() as session:
            row = session.scalar(select(OcrCache).where(OcrCache.input_hash == input_hash, OcrCache.engine == engine, OcrCache.model_name == model_name, OcrCache.model_revision == model_revision, OcrCache.config_fingerprint == config_fingerprint))
            return row.text if row else None

    def save_ocr_cache_with_key(self, input_hash: str, engine: str, model_name: str, model_revision: str, config_fingerprint: str, text: str) -> None:
        statement = insert(OcrCache).values(input_hash=input_hash, engine=engine, model_name=model_name, model_revision=model_revision, config_fingerprint=config_fingerprint, text=text).on_conflict_do_update(
            constraint="uq_ocr_cache_key", set_={"text": text, "created_at": _utc_now()}
        )
        with self._sessions.begin() as session:
            session.execute(statement)
