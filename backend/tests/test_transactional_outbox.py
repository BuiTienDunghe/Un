from __future__ import annotations
import os, threading
import pytest
from sqlalchemy import delete, select
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, Job, OutboxEvent
from app.postgres.repositories import PostgresDocumentRepository
from app.services.outbox_dispatcher_service import OutboxDispatcherService

URL=os.getenv("POSTGRES_TEST_URL")
pytestmark=pytest.mark.skipif(not URL,reason="set POSTGRES_TEST_URL")

class Queue:
    def __init__(self, fail=False): self.fail,self.calls=fail,[]
    def enqueue(self, kind, job_id):
        self.calls.append((kind,job_id))
        if self.fail: raise ConnectionError("redis unavailable")
        return job_id

@pytest.fixture
def factory():
    f=create_session_factory(create_postgres_engine(URL)); yield f
    with f.begin() as s: s.execute(delete(Document).where(Document.original_filename.like("outbox-%")))

def seed(factory):
    with factory.begin() as s:
        r=PostgresDocumentRepository(s); d,v,run=r.create_upload("doc_out_"+os.urandom(4).hex(),"outbox-"+os.urandom(4).hex()+".txt","x.txt","text/plain",1,os.urandom(32).hex()); job=r.create_job("extract_document",d.id,v.id,run.id,3); s.flush(); return job.id

def test_job_and_outbox_are_atomic(factory):
    job_id=seed(factory)
    with factory() as s:
        event=s.scalar(select(OutboxEvent).where(OutboxEvent.job_id==job_id)); assert event and event.status=="pending" and event.idempotency_key
    with pytest.raises(RuntimeError):
        with factory.begin() as s:
            r=PostgresDocumentRepository(s); d,v,run=r.create_upload("doc_rollback","outbox-rollback.txt","x.txt","text/plain",1,"b"*64); r.create_job("extract_document",d.id,v.id,run.id,3); raise RuntimeError()
    with factory() as s: assert not s.scalar(select(Job).where(Job.document_id=="doc_rollback")) and not s.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id=="doc_rollback"))

def test_dispatch_success_retry_and_idempotency(factory):
    job_id=seed(factory); bad=Queue(True); dispatcher=OutboxDispatcherService(factory,bad)
    assert dispatcher.dispatch_pending()==0
    with factory() as s:
        event=s.scalar(select(OutboxEvent).where(OutboxEvent.job_id==job_id)); assert event.status=="retrying" and event.attempts==1 and event.last_error and event.available_at
    with factory.begin() as s: s.scalar(select(OutboxEvent).where(OutboxEvent.job_id==job_id)).available_at=None
    good=Queue(); dispatcher=OutboxDispatcherService(factory,good); assert dispatcher.dispatch_pending()==1 and dispatcher.dispatch_pending()==0
    with factory() as s:
        event=s.scalar(select(OutboxEvent).where(OutboxEvent.job_id==job_id)); job=s.get(Job,job_id); assert event.status=="completed" and event.redis_job_id==job_id and job.redis_job_id==job_id
    assert good.calls==[("extract_document",job_id)]

def test_two_dispatchers_publish_event_once(factory):
    job_id=seed(factory); queue=Queue(); barrier=threading.Barrier(2); results=[]
    def run(): barrier.wait(); results.append(OutboxDispatcherService(factory,queue).dispatch_pending())
    ts=[threading.Thread(target=run) for _ in range(2)]; [t.start() for t in ts]; [t.join() for t in ts]
    assert sum(results)==1 and queue.calls==[("extract_document",job_id)]
