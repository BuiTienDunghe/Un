from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentVersion, IngestionRun, Job, new_id
from app.postgres.repositories import InvalidStateTransition, PostgresDocumentRepository

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")

@pytest.fixture
def factory():
    value=create_session_factory(create_postgres_engine(str(URL))); yield value
    with value.begin() as s: s.execute(delete(Document).where(Document.original_filename=="activation-test.txt"))

def _seed(factory, worker="worker-a", lease=True, cancel=False):
    with factory.begin() as s:
        repo=PostgresDocumentRepository(s); doc, old, _ = repo.create_upload("doc_act_"+os.urandom(4).hex(),"activation-test.txt","x.txt","text/plain",1,os.urandom(32).hex())
        old.status="active"; doc.active_version_id=old.id; doc.status="indexed"
        version=DocumentVersion(id=new_id("ver"),document_id=doc.id,version_number=2,status="staging",chunking_config={}); run=IngestionRun(id=new_id("ing"),document_id=doc.id,version_id=version.id,status="processing",current_stage="activating",cancel_requested=cancel)
        job=Job(id=new_id("job"),job_type="index_document",document_id=doc.id,version_id=version.id,ingestion_run_id=run.id,status="running",worker_id=worker,lease_expires_at=datetime.now(UTC)+(timedelta(minutes=1) if lease else -timedelta(seconds=1)),payload={},idempotency_key="test-"+os.urandom(4).hex())
        s.add_all((version,run,job)); s.flush()
        chunk=DocumentChunk(id=new_id("chunk"),chunk_uid="uid-"+os.urandom(8).hex(),document_id=doc.id,version_id=version.id,chunk_index=0,content="x",content_hash="a"*64,block_type="paragraph",extraction_method="native",status="staging")
        s.add(chunk); return doc.id,old.id,version.id,run.id,job.id

@pytest.mark.parametrize("kind",["wrong_worker","expired","cancelled","wrong_type"])
def test_activation_rejects_invalid_ownership(factory,kind):
    _,old,version,run,job=_seed(factory,cancel=kind=="cancelled",lease=kind!="expired")
    with factory.begin() as s:
        row=s.get(Job,job)
        if kind=="wrong_type": row.job_type="extract_document"
        with pytest.raises(InvalidStateTransition): PostgresDocumentRepository(s).activate(run,job,"other" if kind=="wrong_worker" else "worker-a")
    with factory() as s: assert s.get(DocumentVersion,version).status=="staging" and s.get(Document, s.get(IngestionRun,run).document_id).active_version_id==old

def test_activation_succeeds_with_valid_job_ownership(factory):
    doc,old,version,run,job=_seed(factory)
    with factory.begin() as s: PostgresDocumentRepository(s).activate(run,job,"worker-a")
    with factory() as s:
        assert s.get(DocumentVersion,version).status=="active" and s.get(DocumentVersion,old).status=="superseded" and s.get(Document,doc).active_version_id==version and s.get(IngestionRun,run).current_stage=="completed"

def test_two_workers_cannot_activate_same_version(factory):
    _,_,version,run,job=_seed(factory); results=[]; barrier=threading.Barrier(2)
    def call(worker):
        try:
            barrier.wait()
            with factory.begin() as s: PostgresDocumentRepository(s).activate(run,job,worker)
            results.append("ok")
        except InvalidStateTransition: results.append("denied")
    a=threading.Thread(target=call,args=("worker-a",)); b=threading.Thread(target=call,args=("worker-b",)); a.start(); b.start(); a.join(10); b.join(10)
    assert sorted(results)==["denied","ok"]
