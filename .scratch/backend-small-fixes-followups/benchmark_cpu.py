"""Compare main, branch base, and working-tree page listings on a disposable DB."""
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter
import types

repo = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(repo / "backend"), str(repo)]
import fitz
from sqlalchemy import delete, event, select, update
from sqlalchemy.engine import make_url
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Base, Document, DocumentVersion, IngestionRun, ResearchPaper, ResearchProject
from app.services import document_pages
from app.services.postgres_document_service import PostgresDocumentService
from app.services.research_service import ResearchService

url = os.environ["POSTGRES_TEST_URL"]
assert make_url(url).database == "backend_improve_perf_test"
out = repo / "data/evaluation/results/kept/backend-improvements-2026-11-08"
out.mkdir(parents=True, exist_ok=True)
source_dir = repo / "data/logs/backend-improvements-2026-11-08/benchmark-sources"
engine = create_postgres_engine(url)
sessions = create_session_factory(engine)
Base.metadata.create_all(engine)

def baseline(ref):
    source = subprocess.check_output(["git", "show", ref + ":backend/app/services/research_service.py"], cwd=repo).decode("utf-8")
    module = types.ModuleType("app.services.research_snapshot_" + ref)
    module.__file__ = str(repo / "backend/app/services/research_service.py")
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module.ResearchService

classes = {"main": baseline("c01d6dd"), "before": baseline("67260f3"), "after": ResearchService}
n = 100
now = datetime.now(UTC)
with sessions.begin() as s:
    s.execute(delete(ResearchProject))
    s.execute(delete(Document))
    s.add(ResearchProject(id="cpu_project", name="CPU benchmark", created_at=now, updated_at=now))
    docs = [Document(id=f"cpu_{i}", original_filename=f"{i}.pdf", stored_filename=f"{i}.pdf",
                     status="indexed", source_available=True, created_at=now+timedelta(seconds=i), updated_at=now)
            for i in range(n)]
    s.add_all(docs)
    s.flush()
    for i, doc in enumerate(docs):
        folder = source_dir / doc.id
        folder.mkdir(parents=True, exist_ok=True)
        pdf = fitz.open()
        for page in range(8):
            pdf.new_page().insert_text((72, 72), f"CPU fixture {i}, page {page}")
        data = pdf.tobytes()
        pdf.close()
        (folder / "original.pdf").write_bytes(data)
        doc.content_hash = hashlib.sha256(data).hexdigest()
        for version in (1, 2):
            s.add(DocumentVersion(id=f"{doc.id}_v{version}", document_id=doc.id, version_number=version,
                                  status="active" if version == 2 else "superseded", chunking_config={}))
    s.flush()
    completed = datetime.now(UTC)
    for i, doc in enumerate(docs):
        doc.active_version_id = f"{doc.id}_v2"
        doc.indexed_at = completed
        doc.updated_at = completed
        for suffix, stamp, version in [("old", now-timedelta(seconds=2), 1), ("latest", now, 2), ("null", None, 2)]:
            s.add(IngestionRun(id=f"{doc.id}_{suffix}", document_id=doc.id, version_id=f"{doc.id}_v{version}",
                              started_at=stamp, completed_at=completed, status="completed", current_stage="completed",
                              total_pages=8, total_chunks=12, embedded_chunks=12, progress_percent=100))
        s.add(ResearchPaper(id=f"cpu_p{i:04d}", project_id="cpu_project", document_id=doc.id,
                           short_name=str(i), title=str(i), tags=[], added_at=now, updated_at=now))
with engine.begin() as c:
    c.exec_driver_sql("ANALYZE")
documents = PostgresDocumentService(sessions, None, None, None, None, source_dir, 480, 80, None)
metrics = {"selects": 0, "pdf_reads": 0}
def before_execute(_c, _cur, sql, _p, _ctx, _many):
    if sql.lstrip().upper().startswith("SELECT"):
        metrics["selects"] += 1
event.listen(engine, "before_cursor_execute", before_execute)
original_count = document_pages.page_count
def counted(path):
    metrics["pdf_reads"] += 1
    return original_count(path)
document_pages.page_count = counted
records = []
for block, order in enumerate([["main", "before", "after"], ["after", "before", "main"]]):
    for label in order:
        service = classes[label](sessions, documents, ollama_base_url="http://127.0.0.1:1")
        for mode in ("known", "cold", "warm"):
            with sessions.begin() as s:
                s.execute(update(IngestionRun).values(total_pages=8 if mode == "known" else 0))
            service._page_counts.clear()
            def invoke():
                with sessions() as s:
                    papers = list(s.scalars(select(ResearchPaper).order_by(ResearchPaper.id)))
                    return service._paper_rows(s, papers)
            invoke()
            for repeat in range(5):
                if mode == "cold":
                    service._page_counts.clear()
                metrics.update(selects=0, pdf_reads=0)
                start = perf_counter()
                payload = invoke()
                ms = (perf_counter()-start) * 1000
                digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
                records.append({"block": block, "label": label, "mode": mode, "repeat": repeat,
                                "ms": ms, **metrics, "rows": len(payload), "payload_sha256": digest})
        print(json.dumps({"block": block, "label": label}), flush=True)
summary = []
for mode in ("known", "cold", "warm"):
    group = [r for r in records if r["mode"] == mode]
    assert len({r["payload_sha256"] for r in group}) == 1, (mode, "payload mismatch")
    for label in classes:
        rows = [r for r in group if r["label"] == label]
        summary.append({"label": label, "mode": mode, "rows": n, "samples": len(rows),
                        "median_ms": statistics.median(r["ms"] for r in rows),
                        "min_ms": min(r["ms"] for r in rows), "max_ms": max(r["ms"] for r in rows),
                        "selects": sorted({r["selects"] for r in rows}), "pdf_reads": sorted({r["pdf_reads"] for r in rows}),
                        "payload_equal": True})
(out / "benchmark-raw.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
(out / "benchmark-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
engine.dispose()
