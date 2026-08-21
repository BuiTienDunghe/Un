from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.orm import Session

from app.postgres.models import Document, DocumentChunk, DocumentPage, DocumentVersion, IngestionRun, Job, OutboxEvent, new_id


VERSION_TRANSITIONS = {"staging": {"active", "failed", "deleted"}, "active": {"superseded", "deleted"}, "superseded": {"deleted"}, "failed": {"staging", "deleted"}, "deleted": set()}
RUN_STAGES = {"queued", "parsing", "ocr", "chunking", "embedding", "qdrant_upsert", "activating", "completed", "failed", "cancelled"}
RUN_TRANSITIONS = {
    "queued": {"parsing", "failed", "cancelled"},
    "parsing": {"ocr", "chunking", "failed", "cancelled"},
    "ocr": {"chunking", "failed", "cancelled"},
    "chunking": {"embedding", "failed", "cancelled"},
    "embedding": {"qdrant_upsert", "failed", "cancelled"},
    "qdrant_upsert": {"activating", "failed", "cancelled"},
    "activating": {"completed", "failed", "cancelled"},
    "completed": set(), "failed": set(), "cancelled": set(),
}


class InvalidStateTransition(ValueError):
    pass


class PostgresDocumentRepository:
    """Short PostgreSQL transactions for the versioned document pipeline."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_document(self, document_id: str) -> Document | None:
        return self.session.get(Document, document_id)

    def find_document_by_hash(self, content_hash: str) -> Document | None:
        return self.session.scalar(select(Document).where(Document.content_hash == content_hash, Document.status != "deleted"))

    def find_document_by_display_filename(self, normalized_filename: str) -> Document | None:
        result = self.session.scalar(select(Document).where(Document.display_filename_normalized == normalized_filename, Document.status != "deleted"))
        # Pre-identity rows from migrations before 20260719_10 may not have a
        # normalized key.  The fallback keeps them visible until renamed.
        return result or self.session.scalar(select(Document).where(func.lower(func.trim(Document.original_filename)) == normalized_filename, Document.status != "deleted"))

    def create_upload(self, document_id: str, filename: str, stored_filename: str, mime_type: str | None, file_size: int, content_hash: str, normalized_filename: str | None = None) -> tuple[Document, DocumentVersion, IngestionRun]:
        document = Document(id=document_id, original_filename=filename, display_filename_normalized=normalized_filename, stored_filename=stored_filename, mime_type=mime_type, file_size=file_size, content_hash=content_hash, status="uploaded")
        version = DocumentVersion(id=new_id("ver"), document_id=document_id, version_number=1, status="staging", chunking_config={})
        run = IngestionRun(id=new_id("ing"), document_id=document_id, version_id=version.id, status="queued", current_stage="queued")
        self.session.add_all((document, version, run))
        return document, version, run

    def create_reindex(self, document_id: str) -> tuple[Document, DocumentVersion, IngestionRun]:
        document = self.session.scalar(select(Document).where(Document.id == document_id).with_for_update())
        if document is None:
            raise KeyError(document_id)
        if document.status in {"deleting", "deleted"}:
            raise InvalidStateTransition("cannot reindex a deleting or deleted document")
        pending = self.session.scalar(select(IngestionRun.id).where(IngestionRun.document_id == document_id, IngestionRun.current_stage.not_in(("completed", "failed", "cancelled"))))
        if pending:
            raise InvalidStateTransition("document already has an active ingestion run")
        number = int(self.session.scalar(select(func.coalesce(func.max(DocumentVersion.version_number), 0)).where(DocumentVersion.document_id == document_id)) or 0) + 1
        version = DocumentVersion(id=new_id("ver"), document_id=document_id, version_number=number, status="staging", chunking_config={})
        run = IngestionRun(id=new_id("ing"), document_id=document_id, version_id=version.id, status="queued", current_stage="queued")
        self.session.add_all((version, run))
        return document, version, run

    def get_run(self, run_id: str) -> IngestionRun | None:
        return self.session.get(IngestionRun, run_id)

    def latest_run(self, document_id: str) -> IngestionRun | None:
        return self.session.scalar(select(IngestionRun).where(IngestionRun.document_id == document_id).order_by(IngestionRun.started_at.desc().nullslast(), IngestionRun.id.desc()).limit(1))

    def set_stage(self, run_id: str, stage: str, **values: object) -> IngestionRun:
        if stage not in RUN_STAGES:
            raise InvalidStateTransition(f"unknown ingestion stage: {stage}")
        run = self.session.get(IngestionRun, run_id)
        if run is None:
            raise KeyError(run_id)
        if stage != run.current_stage and stage not in RUN_TRANSITIONS[run.current_stage]:
            raise InvalidStateTransition(f"cannot transition ingestion run {run.current_stage} -> {stage}")
        run.current_stage = stage
        run.status = "failed" if stage == "failed" else ("cancelled" if stage == "cancelled" else ("completed" if stage == "completed" else "processing"))
        if stage == "parsing" and run.started_at is None:
            run.started_at = datetime.now(UTC)
        for key, value in values.items():
            setattr(run, key, value)
        return run

    def replace_pages(self, document_id: str, version_id: str, pages: list[tuple[int | None, str, str]]) -> None:
        self.session.execute(delete(DocumentPage).where(DocumentPage.version_id == version_id))
        self.session.add_all(DocumentPage(id=new_id("page"), document_id=document_id, version_id=version_id, page_number=index, selected_text=text, ocr_text=text if method == "ocr" else None, native_text=text if method != "ocr" else None, extraction_method=method, status="completed") for index, (_, text, method) in enumerate(pages, start=1))

    def replace_chunks(self, document_id: str, version_id: str, chunks: list[object]) -> None:
        self.session.execute(delete(DocumentChunk).where(DocumentChunk.version_id == version_id))
        records = []
        for index, chunk in enumerate(chunks):
            content = str(getattr(chunk, "content"))
            uid = str(uuid5(NAMESPACE_URL, f"local-ai-core:{document_id}:{version_id}:{index}"))
            records.append(DocumentChunk(id=new_id("chunk"), chunk_uid=uid, document_id=document_id, version_id=version_id, chunk_index=index, content=content, retrieval_context=getattr(chunk, "retrieval_context", None), content_hash=sha256(content.encode()).hexdigest(), page_start=getattr(chunk, "page_start"), page_end=getattr(chunk, "page_end"), section_title=getattr(chunk, "section_title"), block_type=str(getattr(chunk, "block_type")), extraction_method=str(getattr(chunk, "extraction_method")), status="staging"))
        self.session.add_all(records)

    def pages_for_version(self, version_id: str) -> list[DocumentPage]:
        return list(self.session.scalars(select(DocumentPage).where(DocumentPage.version_id == version_id).order_by(DocumentPage.page_number)))

    def chunks_for_version(self, version_id: str) -> list[DocumentChunk]:
        return list(self.session.scalars(select(DocumentChunk).where(DocumentChunk.version_id == version_id).order_by(DocumentChunk.chunk_index)))

    def fail_run(self, run_id: str, error_code: str, error_message: str) -> None:
        run = self.session.get(IngestionRun, run_id)
        if run is None:
            return
        version, document = self.session.get(DocumentVersion, run.version_id), self.session.get(Document, run.document_id)
        self.set_stage(run_id, "failed", error_code=error_code, error_message=error_message, completed_at=datetime.now(UTC))
        if version and version.status == "staging":
            version.status = "failed"
        if document and not document.active_version_id:
            document.status, document.error_message = "failed", error_message
        elif document:
            # A failed reindex must never make a still-active version appear unavailable.
            document.status, document.error_message = "indexed", error_message

    def retry_run(self, run_id: str) -> IngestionRun:
        run = self.session.get(IngestionRun, run_id)
        if run is None:
            raise KeyError(run_id)
        version = self.session.get(DocumentVersion, run.version_id)
        if run.current_stage not in {"failed", "cancelled"} or not version or version.status not in {"failed", "staging"}:
            raise InvalidStateTransition("only failed or cancelled staging versions can be retried")
        version.status = "staging"
        run.status, run.current_stage, run.error_code, run.error_message = "queued", "queued", None, None
        run.attempt += 1
        run.total_pages = run.processed_pages = run.ocr_pages = run.total_chunks = run.embedded_chunks = run.progress_percent = 0
        return run

    def activate(self, run_id: str, job_id: str | None = None, worker_id: str | None = None, system_context: bool = False) -> Document:
        run = self.session.scalar(select(IngestionRun).where(IngestionRun.id == run_id).with_for_update())
        if run is None:
            raise KeyError(run_id)
        version = self.session.scalar(select(DocumentVersion).where(DocumentVersion.id == run.version_id).with_for_update())
        document = self.session.scalar(select(Document).where(Document.id == run.document_id).with_for_update())
        job = self.session.scalar(select(Job).where(Job.id == job_id).with_for_update()) if job_id else None
        now = datetime.now(UTC)
        owned = bool(job and worker_id and job.job_type == "index_document" and job.ingestion_run_id == run.id and job.version_id == run.version_id and job.status == "running" and job.worker_id == worker_id and job.lease_expires_at and job.lease_expires_at > now)
        if not owned and not system_context:
            raise InvalidStateTransition("activation requires valid index job ownership")
        if not document or not version or document.status in {"deleting", "deleted"} or run.cancel_requested or run.current_stage in {"cancelled", "failed"} or version.status != "staging" or run.current_stage != "activating" or version.document_id != document.id:
            raise InvalidStateTransition("run is not eligible for activation")
        if not self.session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.version_id == version.id)):
            raise InvalidStateTransition("cannot activate a version without chunks")
        if document.active_version_id:
            old = self.session.get(DocumentVersion, document.active_version_id)
            if old and old.status == "active":
                old.status, old.superseded_at = "superseded", datetime.now(UTC)
        version.status, version.activated_at = "active", datetime.now(UTC)
        document.active_version_id, document.status, document.indexed_at, document.error_message = version.id, "indexed", datetime.now(UTC), None
        self.set_stage(run_id, "completed", completed_at=datetime.now(UTC), progress_percent=100)
        return document

    def activate_verified_legacy_migration(self, run_id: str) -> Document:
        """One-time Phase-5C activation for a pre-verified legacy run.

        This is deliberately separate from worker activation: it locks the same
        document/run/version rows but accepts only historical `indexed` runs,
        requires no existing active version, and never creates a job or changes
        an ingestion run back into a processing state.
        """
        run = self.session.scalar(select(IngestionRun).where(IngestionRun.id == run_id).with_for_update())
        if run is None:
            raise KeyError(run_id)
        version = self.session.scalar(select(DocumentVersion).where(DocumentVersion.id == run.version_id).with_for_update())
        document = self.session.scalar(select(Document).where(Document.id == run.document_id).with_for_update())
        if not document or not version or document.status in {"deleting", "deleted"}:
            raise InvalidStateTransition("legacy migration document is not eligible for activation")
        if document.active_version_id is not None or version.status != "staging":
            raise InvalidStateTransition("legacy migration requires one inactive staging version")
        if run.status != "indexed" or run.current_stage != "indexed" or run.cancel_requested:
            raise InvalidStateTransition("legacy migration run is not verified indexed state")
        if not self.session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.version_id == version.id)):
            raise InvalidStateTransition("cannot activate legacy migration without chunks")
        now = datetime.now(UTC)
        version.status, version.activated_at = "active", now
        document.active_version_id, document.status, document.indexed_at, document.error_message = version.id, "indexed", now, None
        return document

    def active_versions(self, document_ids: list[str] | None = None) -> dict[str, str]:
        statement = select(Document.id, Document.active_version_id).where(Document.status == "indexed", Document.active_version_id.is_not(None))
        if document_ids is not None:
            statement = statement.where(Document.id.in_(document_ids))
        return {str(doc_id): str(version_id) for doc_id, version_id in self.session.execute(statement)}

    def get_active_chunks_by_keys(self, keys: list[tuple[str, str, int]]) -> dict[tuple[str, str, int], DocumentChunk]:
        if not keys:
            return {}
        ids = list({key[0] for key in keys})
        active = self.active_versions(ids)
        rows = self.session.scalars(select(DocumentChunk).where(DocumentChunk.document_id.in_(ids), DocumentChunk.version_id.in_(list(active.values())))).all()
        wanted = set(keys)
        return {(row.document_id, row.version_id, row.chunk_index): row for row in rows if (row.document_id, row.version_id, row.chunk_index) in wanted}

    def active_chunk_snapshot(self, document_ids: list[str] | None = None) -> list[tuple[Document, DocumentVersion, DocumentChunk]]:
        """Return only chunks belonging to the authoritative active version.

        The join to ``documents.active_version_id`` is intentional: a version
        marked active but not selected by its document must never be searchable.
        """
        statement = (
            select(Document, DocumentVersion, DocumentChunk)
            .join(DocumentVersion, DocumentVersion.id == Document.active_version_id)
            .join(DocumentChunk, and_(DocumentChunk.document_id == Document.id, DocumentChunk.version_id == DocumentVersion.id))
            .where(Document.status == "indexed", DocumentVersion.status == "active")
            .order_by(Document.id, DocumentChunk.chunk_index)
        )
        if document_ids is not None:
            if not document_ids:
                return []
            statement = statement.where(Document.id.in_(document_ids))
        return list(self.session.execute(statement).tuples())

    def active_chunk_fingerprint(self) -> tuple[tuple[object, ...], ...]:
        """Cheap aggregate identity of the active retrieval corpus.

        One grouped query replaces scanning every chunk row. ``updated_at`` is
        deliberately excluded: retrieval touches bump it via ``onupdate`` and
        must never invalidate the sparse index. Renames and source removal are
        covered by ``original_filename``/``source_available``.
        """
        statement = (
            select(
                Document.id,
                DocumentVersion.id,
                Document.original_filename,
                Document.source_available,
                DocumentVersion.activated_at,
                func.count(DocumentChunk.id),
                func.max(DocumentChunk.created_at),
            )
            .join(DocumentVersion, DocumentVersion.id == Document.active_version_id)
            .join(DocumentChunk, and_(DocumentChunk.document_id == Document.id, DocumentChunk.version_id == DocumentVersion.id))
            .where(Document.status == "indexed", DocumentVersion.status == "active")
            .group_by(Document.id, DocumentVersion.id, Document.original_filename, Document.source_available, DocumentVersion.activated_at)
            .order_by(Document.id, DocumentVersion.id)
        )
        return tuple(tuple(row) for row in self.session.execute(statement))

    def active_chunks_by_ids(self, chunk_ids: list[str]) -> dict[str, tuple[Document, DocumentVersion, DocumentChunk]]:
        if not chunk_ids:
            return {}
        rows = self.session.execute(
            select(Document, DocumentVersion, DocumentChunk)
            .join(DocumentVersion, DocumentVersion.id == Document.active_version_id)
            .join(DocumentChunk, and_(DocumentChunk.document_id == Document.id, DocumentChunk.version_id == DocumentVersion.id))
            .where(Document.status == "indexed", DocumentVersion.status == "active", DocumentChunk.id.in_(set(chunk_ids)))
        ).tuples()
        return {chunk.id: (document, version, chunk) for document, version, chunk in rows}

    def touch_documents(self, document_ids: set[str]) -> None:
        if document_ids:
            self.session.execute(update(Document).where(Document.id.in_(document_ids), Document.status == "indexed").values(last_accessed_at=datetime.now(UTC)))

    def create_job(self, job_type: str, document_id: str, version_id: str, run_id: str, max_attempts: int) -> Job:
        key = f"{job_type}:{version_id}:{run_id}"
        existing = self.session.scalar(select(Job).where(Job.idempotency_key == key))
        if existing:
            if existing.status in {"failed", "cancelled", "completed"}:
                # An explicit retry of the same run reuses the durable job
                # identity: reset it to queued with a fresh attempt budget and
                # republish its outbox event so the dispatcher picks it up.
                existing.status, existing.attempts = "queued", 0
                existing.error_code = existing.error_message = None
                existing.worker_id = existing.redis_job_id = None
                existing.lease_expires_at = existing.heartbeat_at = None
                existing.started_at = existing.completed_at = existing.available_at = None
                event = self.session.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == f"job_enqueue:{key}"))
                if event:
                    event.status, event.available_at, event.last_error = "pending", None, None
                else:
                    self.create_job_outbox_event(existing)
            return existing
        job = Job(id=new_id("job"), job_type=job_type, document_id=document_id, version_id=version_id, ingestion_run_id=run_id, status="queued", max_attempts=max_attempts, idempotency_key=key, payload={})
        self.session.add(job)
        self.create_job_outbox_event(job)
        return job

    def create_document_delete_job(self, document_id: str, max_attempts: int) -> Job:
        key = f"delete_document:{document_id}"
        existing = self.session.scalar(select(Job).where(Job.idempotency_key == key))
        if existing: return existing
        # Delete lifecycle is owned by the PostgreSQL cleanup worker, not the
        # OCR/index RQ queues.  Do not publish it through the generic outbox
        # dispatcher (which intentionally only knows extract/index tasks).
        job = Job(id=new_id("job"), job_type="delete_document", document_id=document_id, status="queued", max_attempts=max_attempts, idempotency_key=key, payload={})
        self.session.add(job)
        return job

    def create_job_outbox_event(self, job: Job) -> OutboxEvent:
        key = f"job_enqueue:{job.idempotency_key}"
        event = self.session.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == key))
        if event:
            return event
        event = OutboxEvent(
            id=new_id("outbox"), event_type="JOB_ENQUEUE_REQUESTED", aggregate_type="job",
            aggregate_id=job.id, idempotency_key=key, job_id=job.id,
            payload={"job_id": job.id, "job_type": job.job_type}, status="pending",
        )
        self.session.add(event)
        return event

    def get_job(self, job_id: str, lock: bool = False) -> Job | None:
        statement = select(Job).where(Job.id == job_id)
        if lock:
            statement = statement.with_for_update(skip_locked=True)
        return self.session.scalar(statement)

    def start_job(self, job_id: str, worker_id: str, lease_seconds: int) -> Job | None:
        now = datetime.now(UTC)
        from datetime import timedelta
        statement = update(Job).where(Job.id == job_id, Job.status.in_(("queued", "retrying"))).values(status="running", worker_id=worker_id, started_at=func.coalesce(Job.started_at, now), heartbeat_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds), attempts=Job.attempts + 1).returning(Job.id)
        claimed = self.session.scalar(statement)
        return self.session.get(Job, claimed) if claimed else None

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int) -> bool:
        from datetime import timedelta
        now = datetime.now(UTC)
        result = self.session.execute(update(Job).where(Job.id == job_id, Job.status == "running", Job.worker_id == worker_id).values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds)))
        return bool(result.rowcount)

    def worker_owns_job(self, job_id: str, worker_id: str) -> bool:
        job = self.session.get(Job, job_id)
        return bool(job and job.status == "running" and job.worker_id == worker_id and job.lease_expires_at and job.lease_expires_at > datetime.now(UTC))

    def complete_job(self, job_id: str) -> None:
        job = self.session.get(Job, job_id)
        if job:
            job.status, job.completed_at = "completed", datetime.now(UTC)

    def complete_owned_job(self, job_id: str, worker_id: str) -> bool:
        now = datetime.now(UTC)
        result = self.session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "running", Job.worker_id == worker_id, Job.lease_expires_at > now)
            .values(status="completed", completed_at=now)
        )
        return bool(result.rowcount)

    def cancel_job(self, job_id: str) -> None:
        job = self.session.get(Job, job_id)
        if job and job.status not in {"completed", "failed", "cancelled"}:
            job.status, job.completed_at = "cancelled", datetime.now(UTC)
            job.worker_id, job.lease_expires_at, job.heartbeat_at = None, None, None

    def fail_job(self, job_id: str, code: str, message: str, retry: bool = False) -> None:
        job = self.session.get(Job, job_id)
        if job:
            job.status, job.error_code, job.error_message = ("retrying" if retry else "failed"), code, message

    def retry_job(self, job_id: str, code: str, message: str, delay_seconds: int) -> bool:
        from datetime import timedelta
        job = self.session.get(Job, job_id)
        if not job or job.status in {"completed", "failed", "cancelled", "cancel_requested"} or job.attempts >= job.max_attempts:
            return False
        job.status, job.error_code, job.error_message = "retrying", code, message
        job.available_at, job.redis_job_id = datetime.now(UTC) + timedelta(seconds=delay_seconds), None
        return True

    def queued_jobs_without_redis(self) -> list[Job]:
        return list(
            self.session.scalars(
                select(Job).where(
                    Job.job_type.in_(("extract_document", "index_document")),
                    Job.status.in_(("queued", "retrying")),
                    Job.redis_job_id.is_(None),
                )
            )
        )

    def request_cancel(self, run_id: str) -> None:
        for job in self.session.scalars(select(Job).where(Job.ingestion_run_id == run_id, Job.status.in_(("queued", "running", "retrying")))):
            job.status = "cancel_requested"
        run = self.session.get(IngestionRun, run_id)
        if run:
            run.cancel_requested = True

    def cancellation_requested(self, run_id: str) -> bool:
        run = self.session.get(IngestionRun, run_id)
        return bool(run and run.cancel_requested)

    def pending_outbox_events(self, limit: int = 100) -> list[OutboxEvent]:
        return list(self.session.scalars(select(OutboxEvent).where(OutboxEvent.status == "pending").order_by(OutboxEvent.created_at).limit(limit)))
