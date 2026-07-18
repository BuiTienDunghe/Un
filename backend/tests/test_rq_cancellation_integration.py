"""Phase 3E cancellation checkpoints through real RQ workers."""

from __future__ import annotations

import threading
from uuid import uuid4

from rq import SimpleWorker
from sqlalchemy import select

from app.postgres.models import Document, DocumentVersion, IngestionRun, Job
from app.postgres.repositories import PostgresDocumentRepository
from app.services.job_queue_service import JobQueueService
from app.utils.chunking import chunk_pages
from tests.worker_integration_support import FakeEmbeddingRouter, FakeQdrantStore, build_worker_service


def _seed(resources, tmp_path, *, active_old=False):
    doc_id = f"doc_{uuid4().hex}"; filename = f"{resources['filename_prefix']}-{doc_id}.txt"
    source = tmp_path / "documents" / doc_id / "original.txt"; source.parent.mkdir(parents=True); source.write_text("cancellation test text", encoding="utf-8")
    with resources["factory"].begin() as session:
        repo = PostgresDocumentRepository(session); doc, version, run = repo.create_upload(doc_id, filename, f"{doc_id}.txt", "text/plain", 1, uuid4().hex * 2)
        if active_old:
            old = DocumentVersion(id=f"ver_old_{uuid4().hex}", document_id=doc_id, version_number=0, status="active")
            session.add(old); session.flush(); repo.replace_chunks(doc_id, old.id, chunk_pages([(1, "old active context", "native")]))
            doc.active_version_id, doc.status = old.id, "indexed"
        else:
            doc.status = "processing"
        job = repo.create_job("extract_document", doc_id, version.id, run.id, 3); session.flush()
        return doc_id, version.id, run.id, job.id


def test_cancel_during_ocr_prevents_index_and_activation(worker_integration_resources, monkeypatch, tmp_path):
    r = worker_integration_resources; doc_id, version_id, run_id, extract_id = _seed(r, tmp_path)
    service = build_worker_service(r, tmp_path, FakeQdrantStore(), FakeEmbeddingRouter())
    entered, release = threading.Event(), threading.Event()

    def controlled_parse(path, on_stage=None, checkpoint=None, long_call=None):
        assert checkpoint and checkpoint(); entered.set(); release.wait(5)
        if not checkpoint(): raise PermissionError("cancelled between OCR pages")
        return [(1, "unexpected second page", "ocr")]

    monkeypatch.setattr(service.parser, "parse", controlled_parse)
    queue = JobQueueService(r["redis_url"], r["prefix"]); import app.workers.tasks as tasks
    monkeypatch.setattr(tasks, "_service", lambda: (service, r["factory"], queue)); queue.enqueue("extract_document", extract_id)
    canceller = threading.Thread(target=lambda: (entered.wait(5), service.cancel_ingestion(run_id), release.set()), daemon=True); canceller.start()
    SimpleWorker([r["ocr_queue"]], connection=r["redis"]).work(burst=True, logging_level="WARNING", with_scheduler=True); canceller.join(5)
    with r["factory"]() as session:
        run, version, job = session.get(IngestionRun, run_id), session.get(DocumentVersion, version_id), session.get(Job, extract_id)
        index_jobs = list(session.scalars(select(Job).where(Job.ingestion_run_id == run_id, Job.job_type == "index_document")))
        assert run.current_stage == "cancelled" and version.status == "staging" and job.status == "cancelled" and not index_jobs


def test_cancel_before_activation_preserves_active_version(worker_integration_resources, monkeypatch, tmp_path):
    r = worker_integration_resources; doc_id, first_version, initial_run_id, _ = _seed(r, tmp_path, active_old=True)
    with r["factory"].begin() as session:
        repo = PostgresDocumentRepository(session)
        initial = repo.get_run(initial_run_id); initial.current_stage, initial.status = "completed", "completed"
        session.get(DocumentVersion, first_version).status = "failed"
        session.flush()
        _, version, run = repo.create_reindex(doc_id)
        session.flush()
        repo.replace_pages(doc_id, version.id, [(1, "new staging content", "native")])
        job = repo.create_job("index_document", doc_id, version.id, run.id, 3); session.flush(); index_id, run_id = job.id, run.id
        old_id = session.get(Document, doc_id).active_version_id
        run.current_stage, run.status = "chunking", "processing"
    entered, release = threading.Event(), threading.Event()

    class BlockingQdrant(FakeQdrantStore):
        def upsert_chunks(self, *args, **kwargs):
            super().upsert_chunks(*args, **kwargs); entered.set(); release.wait(5)

    service = build_worker_service(r, tmp_path, BlockingQdrant(), FakeEmbeddingRouter())
    queue = JobQueueService(r["redis_url"], r["prefix"]); import app.workers.tasks as tasks
    monkeypatch.setattr(tasks, "_service", lambda: (service, r["factory"], queue)); queue.enqueue("index_document", index_id)
    canceller = threading.Thread(target=lambda: (entered.wait(5), service.cancel_ingestion(run_id), release.set()), daemon=True); canceller.start()
    SimpleWorker([r["index_queue"]], connection=r["redis"]).work(burst=True, logging_level="WARNING", with_scheduler=True); canceller.join(5)
    with r["factory"]() as session:
        doc, run, version, job = session.get(Document, doc_id), session.get(IngestionRun, run_id), session.get(DocumentVersion, version.id), session.get(Job, index_id)
        assert doc.active_version_id == old_id and doc.status == "indexed"
        assert run.current_stage == "cancelled" and version.status == "staging" and job.status == "cancelled"
