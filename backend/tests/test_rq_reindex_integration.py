"""Phase 3F reindex semantics through the RQ worker pipeline."""
from __future__ import annotations

from uuid import uuid4
from rq import SimpleWorker
from sqlalchemy import select

from app.postgres.models import Document, DocumentVersion, IngestionRun, Job
from app.postgres.repositories import PostgresDocumentRepository
from app.services.job_queue_service import JobQueueService
from app.services.outbox_dispatcher_service import OutboxDispatcherService
from app.services.postgres_retrieval_service import PostgresRetrievalService
from app.utils.chunking import chunk_pages
from tests.worker_integration_support import FakeEmbeddingRouter, FakeQdrantStore, build_worker_service


def _prepare_reindex(resources, tmp_path):
    doc_id=f"doc_{uuid4().hex}"; filename=f"{resources['filename_prefix']}-{doc_id}.txt"
    source=tmp_path/"documents"/doc_id/"original.txt"; source.parent.mkdir(parents=True); source.write_text("new reindex content for worker pipeline", encoding="utf-8")
    with resources["factory"].begin() as s:
        repo=PostgresDocumentRepository(s); doc, first, initial=repo.create_upload(doc_id, filename, f"{doc_id}.txt", "text/plain", 1, uuid4().hex*2)
        old=DocumentVersion(id=f"ver_old_{uuid4().hex}", document_id=doc_id, version_number=0, status="active"); s.add(old); s.flush()
        old_chunks=chunk_pages([(1,"old version remains searchable", "native")]); repo.replace_chunks(doc_id,old.id,old_chunks); s.flush(); old_ids=[x.id for x in repo.chunks_for_version(old.id)]
        first.status="failed"; initial.current_stage,initial.status="failed","failed"; doc.active_version_id,doc.status=old.id,"indexed"; s.flush()
        _,version,run=repo.create_reindex(doc_id); job=repo.create_job("extract_document",doc_id,version.id,run.id,3); s.flush()
        return doc_id,old.id,old_chunks,old_ids,version.id,run.id,job.id


def _run(resources, monkeypatch, tmp_path, router, qdrant, extract_id):
    service=build_worker_service(resources,tmp_path,qdrant,router); queue=JobQueueService(resources["redis_url"],resources["prefix"])
    import app.workers.tasks as tasks
    monkeypatch.setattr(tasks,"_service",lambda:(service,resources["factory"],queue)); queue.enqueue("extract_document",extract_id)
    SimpleWorker([resources["ocr_queue"]],connection=resources["redis"]).work(burst=True,logging_level="WARNING",with_scheduler=True)
    OutboxDispatcherService(resources["factory"],queue).dispatch_pending()
    SimpleWorker([resources["index_queue"]],connection=resources["redis"]).work(burst=True,logging_level="WARNING",with_scheduler=True)


def test_failed_rq_reindex_preserves_previous_active_version(worker_integration_resources,monkeypatch,tmp_path):
    r=worker_integration_resources; doc,old,old_chunks,old_ids,new,run,extract=_prepare_reindex(r,tmp_path)
    class FailingRouter(FakeEmbeddingRouter):
        def embed(self,text): raise ValueError("invalid fixed embedding configuration")
    q=FakeQdrantStore(); q.upsert_chunks(doc,old,"old.txt",old_chunks,[[.1,.2,.3]],chunk_ids=old_ids)
    router=FailingRouter(); _run(r,monkeypatch,tmp_path,router,q,extract)
    with r["factory"]() as s:
        document=s.get(Document,doc); version=s.get(DocumentVersion,new); ingestion=s.get(IngestionRun,run)
        assert document.status=="indexed" and document.active_version_id==old and version.status=="failed" and ingestion.current_stage=="failed"
    results=PostgresRetrievalService(q,FakeEmbeddingRouter(),r["factory"]).retrieve("old",1,doc)
    assert results and results[0]["version_id"]==old


def test_successful_rq_reindex_supersedes_previous_version(worker_integration_resources,monkeypatch,tmp_path):
    r=worker_integration_resources; doc,old,old_chunks,old_ids,new,run,extract=_prepare_reindex(r,tmp_path)
    q=FakeQdrantStore(); q.upsert_chunks(doc,old,"old.txt",old_chunks,[[.1,.2,.3]],chunk_ids=old_ids); router=FakeEmbeddingRouter()
    _run(r,monkeypatch,tmp_path,router,q,extract)
    with r["factory"]() as s:
        document=s.get(Document,doc); versions=list(s.scalars(select(DocumentVersion).where(DocumentVersion.document_id==doc))); jobs=list(s.scalars(select(Job).where(Job.ingestion_run_id==run)))
        assert document.active_version_id==new and s.get(DocumentVersion,new).status=="active" and s.get(DocumentVersion,old).status=="superseded"
        assert len([v for v in versions if v.status=="active"])==1 and all(j.status=="completed" for j in jobs)
    results=PostgresRetrievalService(q,router,r["factory"]).retrieve("new",3,doc)
    assert results and all(row["version_id"]==new for row in results)
