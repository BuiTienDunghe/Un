"""PostgreSQL persistence for the six auxiliary SQLite domains.

This adapter intentionally mirrors only the methods currently consumed by the
chat, memory, OCR-console and request-log services.  It does not own document
pipeline data and it does not implement a fallback to SQLite.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import String, cast, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from app.postgres.models import AgentTrace, Conversation, DiscordConversationSession, Memory, Message, MessageSource, OcrCache, OcrRun, RequestLog


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _uuid(value: str) -> UUID:
    return UUID(value)


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

    def create_conversation(self, conversation_id: str, title: str | None = None, user_id: str | None = None) -> None:
        now = _utc_now()
        with self._sessions.begin() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    title=title,
                    user_id=_uuid(user_id) if user_id else None,
                    created_at=now,
                    updated_at=now,
                )
            )

    def conversation_owner(self, conversation_id: str) -> str | None:
        """Owning user id, or None for unowned/legacy rows (P3-1 ownership)."""
        with self._sessions() as session:
            conversation = session.get(Conversation, conversation_id)
            return str(conversation.user_id) if conversation is not None and conversation.user_id else None

    def set_conversation_title(self, conversation_id: str, title: str) -> bool:
        with self._sessions.begin() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            conversation.title = title
            return True

    def add_message(self, conversation_id: str, role: str, content: str, model_used: str | None = None, sources: list[dict[str, object]] | None = None) -> int:
        """Store one message and, in the same transaction, the sources it cited.

        Keeping both writes in one transaction is the point: a persisted answer
        must never appear later without the citations it was grounded in.
        """
        now = _utc_now()
        with self._sessions.begin() as session:
            message = Message(conversation_id=conversation_id, role=role, content=content, model_used=model_used, created_at=now)
            session.add(message)
            session.flush()  # assigns message.id for the source rows below
            for position, source in enumerate(sources or [], start=1):
                session.add(
                    MessageSource(
                        message_id=message.id,
                        position=position,
                        document_id=str(source.get("document_id", "")),
                        chunk_id=str(source.get("chunk_id", "")),
                        filename=str(source.get("filename", "")),
                        page_start=source.get("page_start"),
                        page_end=source.get("page_end"),
                        heading_path=source.get("heading_path"),
                        score=float(source.get("score", 0.0)),
                        excerpt=str(source.get("excerpt", "")),
                        created_at=now,
                    )
                )
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.updated_at = now
            return message.id

    def get_messages(self, conversation_id: str, limit: int) -> list[dict[str, str]]:
        with self._sessions() as session:
            rows = list(session.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.desc()).limit(limit)))
        rows.reverse()
        return [{"role": row.role, "content": row.content} for row in rows]

    def add_agent_traces(self, conversation_id: str, message_id: int | None, steps: list[dict[str, object]]) -> None:
        """Persist the agent-loop steps that produced one assistant message."""
        if not steps:
            return
        now = _utc_now()
        with self._sessions.begin() as session:
            for index, step in enumerate(steps):
                session.add(
                    AgentTrace(
                        conversation_id=conversation_id,
                        message_id=message_id,
                        step_index=index,
                        kind=str(step.get("kind", "tool_call")),
                        tool_name=(str(step["tool_name"]) if step.get("tool_name") else None),
                        arguments=step.get("arguments") if isinstance(step.get("arguments"), dict) else None,
                        content=(str(step["content"]) if step.get("content") is not None else None),
                        latency_ms=(int(step["latency_ms"]) if step.get("latency_ms") is not None else None),
                        created_at=now,
                    )
                )

    def get_agent_traces(self, message_id: int) -> list[dict[str, object]]:
        with self._sessions() as session:
            rows = list(
                session.scalars(
                    select(AgentTrace).where(AgentTrace.message_id == message_id).order_by(AgentTrace.step_index)
                )
            )
            return [
                {
                    "step_index": row.step_index,
                    "kind": row.kind,
                    "tool_name": row.tool_name,
                    "arguments": row.arguments,
                    "content": row.content,
                    "latency_ms": row.latency_ms,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    def list_conversations(self, owner_user_id: str | None = None) -> list[dict[str, object]]:
        conditions = [
            ~exists(
                select(DiscordConversationSession.id).where(
                    cast(DiscordConversationSession.backend_conversation_id, String) == Conversation.id,
                    DiscordConversationSession.origin == "discord",
                )
            )
        ]
        if owner_user_id is not None:
            # P3-1: a member's sidebar shows only their own conversations.
            conditions.append(Conversation.user_id == _uuid(owner_user_id))
        with self._sessions() as session:
            rows = session.execute(
                select(Conversation.id, Conversation.title, Conversation.created_at, Conversation.updated_at, func.count(Message.id).label("message_count"))
                .outerjoin(Message, Message.conversation_id == Conversation.id)
                .where(*conditions)
                .group_by(Conversation.id, Conversation.title, Conversation.created_at, Conversation.updated_at)
                .order_by(Conversation.updated_at.desc())
            ).all()
        return [{"id": row.id, "title": row.title, "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(), "message_count": row.message_count} for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, object] | None:
        with self._sessions() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return None
            messages = list(session.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)))
            # One query for every citation in the conversation, not one per message.
            citations: dict[int, list[dict[str, object]]] = {}
            if messages:
                rows = session.scalars(
                    select(MessageSource)
                    .where(MessageSource.message_id.in_([message.id for message in messages]))
                    .order_by(MessageSource.message_id, MessageSource.position)
                )
                for row in rows:
                    citations.setdefault(row.message_id, []).append(
                        {
                            "document_id": row.document_id,
                            "chunk_id": row.chunk_id,
                            "filename": row.filename,
                            "page_start": row.page_start,
                            "page_end": row.page_end,
                            "heading_path": row.heading_path,
                            "score": row.score,
                            "excerpt": row.excerpt,
                        }
                    )
            return {
                "id": conversation.id,
                "title": conversation.title,
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
                "messages": [
                    {
                        "role": row.role,
                        "content": row.content,
                        "model_used": row.model_used,
                        "created_at": row.created_at.isoformat(),
                        "sources": citations.get(row.id, []),
                    }
                    for row in messages
                ],
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

    def log_request(self, endpoint: str, model_used: str | None, latency_ms: int, status: str, error_code: str | None = None, message_id: int | None = None, tokens_in: int | None = None, tokens_out: int | None = None, prompt_hash: str | None = None) -> None:
        with self._sessions.begin() as session:
            session.add(RequestLog(endpoint=endpoint, model_used=model_used, latency_ms=latency_ms, status=status, error_code=error_code, message_id=message_id, tokens_in=tokens_in, tokens_out=tokens_out, prompt_hash=prompt_hash, created_at=_utc_now()))

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
