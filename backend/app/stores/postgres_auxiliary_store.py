"""PostgreSQL persistence for the six auxiliary SQLite domains.

This adapter intentionally mirrors only the methods currently consumed by the
chat, memory, OCR-console and request-log services.  It does not own document
pipeline data and it does not implement a fallback to SQLite.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import String, cast, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from app.postgres.models import AgentTrace, AgentTraceSummary, Conversation, DiscordConversationSession, Document, DocumentVersion, Memory, Message, MessageSource, OcrCache, OcrRun, RequestLog


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

    def add_agent_traces(
        self, conversation_id: str, message_id: int | None, steps: list[dict[str, object]], source: str = "web",
    ) -> None:
        """Persist the agent-loop steps that produced one assistant message: the full
        step in agent_traces (cascades with the conversation) and its content-free
        skeleton in agent_trace_summaries (outlives it), in ONE transaction, so a
        skeleton never exists without the trace it summarises at write time."""
        if not steps:
            return
        now = _utc_now()

        def number(value: object) -> int | None:
            return int(value) if value is not None else None

        def text(value: object, limit: int) -> str | None:
            return str(value)[:limit] if value else None

        with self._sessions.begin() as session:
            for index, step in enumerate(steps):
                kind = str(step.get("kind", "tool_call"))
                tool_name = text(step.get("tool_name"), 128)
                content = str(step["content"]) if step.get("content") is not None else None
                session.add(
                    AgentTrace(
                        conversation_id=conversation_id,
                        message_id=message_id,
                        step_index=index,
                        kind=kind,
                        tool_name=tool_name,
                        arguments=step.get("arguments") if isinstance(step.get("arguments"), dict) else None,
                        content=content,
                        latency_ms=number(step.get("latency_ms")),
                        created_at=now,
                    )
                )
                # Nothing below may carry an argument, a result or an answer
                # (test_agent_trace_summaries scans every text column for a bait).
                shape = step.get("arguments_shape")
                # A tool name is model output: kept only when the step marks it as one of
                # the declared tools, "unknown" otherwise (an invented name can carry words).
                summary_tool = tool_name if step.get("tool_declared") else ("unknown" if tool_name else None)
                session.add(
                    AgentTraceSummary(
                        conversation_id=conversation_id,
                        message_id=message_id,
                        step_index=index,
                        kind=kind,
                        tool_name=summary_tool,
                        latency_ms=number(step.get("latency_ms")),
                        error_code=text(step.get("error_code"), 64),
                        error_type=text(step.get("error_type"), 128),
                        stop_reason=text(step.get("stop_reason"), 32),
                        tokens_in=number(step.get("tokens_in")),
                        tokens_out=number(step.get("tokens_out")),
                        arguments_shape=shape if isinstance(shape, dict) else None,
                        content_sha256=sha256(content.encode("utf-8")).hexdigest() if content is not None else None,
                        source=source,
                        created_at=now,
                    )
                )

    def get_agent_traces(self, message_id: int) -> list[dict[str, object]]:
        with self._sessions() as session:
            rows = list(
                session.scalars(
                    select(AgentTrace).where(AgentTrace.message_id == message_id, AgentTrace.kind != "tool_state").order_by(AgentTrace.step_index)
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


    def get_agent_history(self, conversation_id: str, limit: int) -> list[dict[str, object]]:
        """Text plus trusted IDs, used only by the opt-in continuity path."""
        with self._sessions() as session:
            rows = list(session.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.desc()).limit(limit)))
        rows.reverse()
        return [{"role": row.role, "content": row.content, "message_id": row.id} for row in rows]

    def save_tool_state(self, conversation_id: str, message_id: int, scope: str,
                        payload: dict[str, object], origin: str | None = None) -> None:
        """A bounded private envelope; never put its content in trace summaries."""
        from app.services.tool_state import STATE_KIND, ToolStateLimits
        limits = ToolStateLimits()
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > limits.max_chars or not payload.get("groups"):
            return
        now = _utc_now()
        with self._sessions.begin() as session:
            # Serialize only the short state write/prune, never the model call.
            conversation = session.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
            if conversation is None:
                raise ValueError("tool-state conversation no longer exists")
            message = session.get(Message, message_id, with_for_update=True)
            if message is None or message.conversation_id != conversation_id or message.role != "assistant":
                raise ValueError("tool state must belong to an assistant message in this conversation")
            # Replacement is idempotent for the same persisted answer.
            session.execute(delete(AgentTrace).where(AgentTrace.message_id == message_id, AgentTrace.kind == STATE_KIND))
            session.add(AgentTrace(conversation_id=conversation_id, message_id=message_id, step_index=-1,
                                   kind=STATE_KIND, arguments={"scope_key": scope, "origin": origin},
                                   content=encoded, created_at=now))
            session.flush()
            keep = select(AgentTrace.id).where(AgentTrace.conversation_id == conversation_id, AgentTrace.kind == STATE_KIND).order_by(AgentTrace.id.desc()).limit(limits.max_envelopes)
            session.execute(delete(AgentTrace).where(
                AgentTrace.conversation_id == conversation_id, AgentTrace.kind == STATE_KIND,
                or_(AgentTrace.created_at < now - timedelta(seconds=limits.max_age_seconds), AgentTrace.id.not_in(keep)),
            ))

    def load_tool_states(self, conversation_id: str, scope: str, *, message_ids: list[int] | None = None,
                         origins: list[str] | None = None) -> list[dict[str, object]]:
        from app.services.tool_state import STATE_KIND, ToolStateLimits
        limits = ToolStateLimits()
        selected = []
        if message_ids:
            selected.append(AgentTrace.message_id.in_(message_ids))
        if origins:
            selected.append(AgentTrace.arguments["origin"].astext.in_(origins))
        if not selected:
            return []
        with self._sessions() as session:
            rows = list(session.scalars(select(AgentTrace).where(
                AgentTrace.conversation_id == conversation_id, AgentTrace.kind == STATE_KIND,
                AgentTrace.arguments["scope_key"].astext == scope,
                AgentTrace.created_at >= _utc_now() - timedelta(seconds=limits.max_age_seconds),
                or_(*selected),
            ).order_by(AgentTrace.id.desc()).limit(limits.max_envelopes)))
            result = []
            for row in rows:
                if not row.content or len(row.content) > limits.max_chars:
                    continue
                try:
                    payload = json.loads(row.content)
                except (ValueError, TypeError):
                    continue
                if isinstance(payload, dict) and payload.get("v") == 1 and isinstance(payload.get("groups"), list):
                    result.append({"message_id": row.message_id, "origin": (row.arguments or {}).get("origin"),
                                   "payload": payload})
            return result

    def state_document_versions(self, document_ids: set[str]) -> dict[str, str]:
        """Current canonical versions. History does not confer read permission."""
        if not document_ids:
            return {}
        with self._sessions() as session:
            rows = session.execute(select(Document.id, Document.active_version_id).join(
                DocumentVersion, DocumentVersion.id == Document.active_version_id).where(
                Document.id.in_(document_ids), Document.status == "indexed", Document.active_version_id.is_not(None),
                DocumentVersion.document_id == Document.id, DocumentVersion.status == "active",
            ))
            return {document_id: version_id for document_id, version_id in rows}

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
