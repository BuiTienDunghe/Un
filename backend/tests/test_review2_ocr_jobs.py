"""Review2 OCR jobs: deleting a running job (R6), deleting after a restart and where a
delete may reach (R7), the dpi a job runs at (R8), and the page range (C).

No container: a small FastAPI app with the real OCR router and job service, an in-memory
run store, MOCK_OCR pages, and every folder inside pytest's tmp_path. The runs folder sits
two levels down so even a careless delete cannot leave tmp_path.
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
import tracemalloc
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from app.routers.ocr import router as ocr_router
from app.services.ocr_job_service import OcrJobService
from review2_support import PNG, BlockingOcr, KnownBug, MemoryOcrStore, known_bug, ocr_router_stub, quiet_ocr, wait_idle


def ocr_app(tmp_path, monkeypatch, *, ocr_service=None) -> SimpleNamespace:
    quiet_ocr(monkeypatch)
    runs = tmp_path / "data" / "runs"
    runs.mkdir(parents=True)
    store = MemoryOcrStore()
    app = FastAPI()
    app.state.settings = SimpleNamespace(local_ai_auth_enabled=False, local_ai_api_key="")
    app.state.ocr_job_service = OcrJobService(ocr_router_stub(), runs, store, ocr_service=ocr_service)
    app.include_router(ocr_router)
    return SimpleNamespace(app=app, http=TestClient(app), store=store, runs=runs, tmp=tmp_path,
                           service=lambda: app.state.ocr_job_service)


@pytest.fixture
def ocr(tmp_path, monkeypatch):
    harness = ocr_app(tmp_path, monkeypatch)
    yield harness
    wait_idle(harness.service())


def upload(ocr, *, dpi: int | None = 200, content: bytes = PNG, filename: str = "trang.png"):
    params = {} if dpi is None else {"dpi": dpi}
    return ocr.http.post("/api/ocr/jobs", params=params, files={"file": (filename, content, "image/png")})


def finished_job(ocr) -> str:
    created = upload(ocr)
    assert created.status_code == 201, created.text
    wait_idle(ocr.service())
    job_id = created.json()["id"]
    assert ocr.http.get(f"/api/ocr/jobs/{job_id}").json()["status"] == "completed"
    assert (ocr.runs / job_id).is_dir()
    return job_id


def history_ids(ocr) -> list[str]:
    return [run["id"] for run in ocr.http.get("/api/ocr/history").json()["runs"]]


# ── R6: deleting a job while its worker runs ────────────────────────────────────

@pytest.mark.parametrize("cancel_first", [False, True], ids=["delete", "cancel_then_delete"])
@pytest.mark.xfail(strict=True, raises=KnownBug,
                   reason="review2 R6: a job deleted while it runs is saved again by its worker and comes back")
def test_r6_1_a_job_deleted_while_running_never_comes_back(tmp_path, monkeypatch, cancel_first):
    blocking = BlockingOcr()
    ocr = ocr_app(tmp_path, monkeypatch, ocr_service=blocking)
    try:
        created = upload(ocr)
        assert created.status_code == 201, created.text
        job_id = created.json()["id"]
        assert blocking.entered.wait(5), "the worker never reached the OCR model"
        if cancel_first:
            assert ocr.http.post(f"/api/ocr/jobs/{job_id}/cancel").status_code == 200
        deleted = ocr.http.delete(f"/api/ocr/history/{job_id}")
    finally:
        blocking.release.set()
    wait_idle(ocr.service())
    assert deleted.status_code in (204, 409), deleted.text
    if deleted.status_code == 409:
        # A refusal is valid if the job is left whole.
        assert ocr.http.get(f"/api/ocr/jobs/{job_id}").status_code == 200
        assert job_id in history_ids(ocr) and (ocr.runs / job_id).is_dir()
        return
    gone = (ocr.http.get(f"/api/ocr/jobs/{job_id}").status_code == 404 and job_id not in history_ids(ocr)
            and not (ocr.runs / job_id).exists())
    known_bug(gone, "the delete answered 204 and the job came back once its worker stopped")


def test_r6_2_a_finished_job_deleted_is_gone_from_history_and_disk(ocr):
    job_id = finished_job(ocr)
    assert ocr.http.delete(f"/api/ocr/history/{job_id}").status_code == 204
    assert job_id not in history_ids(ocr)
    assert not (ocr.runs / job_id).exists()
    assert ocr.http.get(f"/api/ocr/jobs/{job_id}").status_code == 404


# ── R7: delete after a restart, and where a delete may reach ────────────────────

def restart(ocr) -> None:
    ocr.app.state.ocr_job_service = OcrJobService(ocr_router_stub(), ocr.runs, ocr.store)


@pytest.mark.xfail(strict=True, raises=KnownBug,
                   reason="review2 R7: after a restart the job is not in memory, so its delete leaves every file on disk")
def test_r7_1_a_job_deleted_right_after_a_restart_leaves_no_folder(ocr):
    job_id = finished_job(ocr)
    restart(ocr)
    assert ocr.http.delete(f"/api/ocr/history/{job_id}").status_code == 204
    assert job_id not in history_ids(ocr)
    known_bug(not (ocr.runs / job_id).exists(), "the job's images and text are still on disk")


def test_r7_2_a_job_opened_after_a_restart_then_deleted_leaves_no_folder(ocr):
    job_id = finished_job(ocr)
    restart(ocr)
    assert ocr.http.get(f"/api/ocr/jobs/{job_id}").status_code == 200
    assert ocr.http.delete(f"/api/ocr/history/{job_id}").status_code == 204
    assert not (ocr.runs / job_id).exists()


TRAVERSALS = [
    ("http", "%2e%2e"),
    ("http", "..%5C..%5Cx"),
    ("direct", ".."),
    ("direct", "..\\..\\x"),
    ("direct", "ABSOLUTE"),
    ("direct", "keep"),
    ("direct", "ocr_" + "z" * 32),
]


@pytest.mark.parametrize(("way", "job_id"), TRAVERSALS, ids=[f"{way}:{job_id}" for way, job_id in TRAVERSALS])
def test_r7_3_a_delete_never_reaches_outside_its_own_job_folder(ocr, way, job_id):
    canaries = [ocr.tmp / "outside.txt", ocr.tmp / "x" / "canary.txt", ocr.tmp / "victim" / "canary.txt",
                ocr.runs / "keep" / "canary.txt", ocr.runs / ("ocr_" + "z" * 32) / "canary.txt",
                ocr.runs / ("ocr_" + uuid4().hex) / "canary.txt"]
    for canary in canaries:
        canary.parent.mkdir(parents=True, exist_ok=True)
        canary.write_text("còn đây", encoding="utf-8")
    if job_id == "ABSOLUTE":
        job_id = str(ocr.tmp / "victim")
    if way == "http":
        ocr.http.delete(f"/api/ocr/history/{job_id}")
    else:
        ocr.service().delete(job_id)
    assert [str(canary) for canary in canaries if not canary.exists()] == []


@pytest.mark.xfail(strict=True, raises=KnownBug,
                   reason="review2 R7: a job's folder is taken from the stored run, so a stored root outside the runs folder is deleted")
def test_r7_4_a_stored_root_outside_the_runs_folder_is_never_deleted(tmp_path, monkeypatch):
    quiet_ocr(monkeypatch)
    runs, victim = tmp_path / "data" / "runs", tmp_path / "victim"
    job_id = "ocr_" + uuid4().hex
    (runs / job_id / "pages").mkdir(parents=True)
    victim.mkdir()
    (victim / "canary.txt").write_text("còn đây", encoding="utf-8")
    store = MemoryOcrStore()
    job = {"id": job_id, "filename": "trang.png", "status": "completed", "root": str(victim),
           "path": str(victim / "input.png"), "pages": [], "events": [], "logs": [], "model": "mock-ocr"}
    store.save_ocr_run(job_id, "trang.png", "completed", "mock-ocr", json.dumps(job))
    service = OcrJobService(ocr_router_stub(), runs, store)  # the API just started
    assert service.view(job_id)["status"] == "completed"
    service.delete(job_id)
    known_bug((victim / "canary.txt").exists(), "deleting the job removed a folder outside the runs folder")


def make_job(service) -> str:
    created = asyncio.run(service.create(UploadFile(file=io.BytesIO(PNG), filename="trang.png"), 200, None, "all"))
    wait_idle(service)
    assert service.view(created["id"])["status"] == "completed"
    return created["id"]


@pytest.mark.xfail(sys.platform == "win32", strict=True, raises=KnownBug,
                   reason="review2 R7: on Windows a file held open survives the delete, and no later delete removes it")
def test_r7_5_a_file_held_open_during_a_delete_is_gone_after_a_later_delete(tmp_path, monkeypatch):
    quiet_ocr(monkeypatch)
    runs, store = tmp_path / "data" / "runs", MemoryOcrStore()
    runs.mkdir(parents=True)
    service = OcrJobService(ocr_router_stub(), runs, store)
    job_id = make_job(service)
    held = open(runs / job_id / "pages" / "page_0001" / "text.txt", "rb")  # noqa: SIM115
    try:
        service.delete(job_id)
    finally:
        held.close()
    # Later: the history is deleted again, and once more after the API restarts.
    service.delete(job_id)
    OcrJobService(ocr_router_stub(), runs, store).delete(job_id)
    left = sorted(str(path.relative_to(runs)) for path in (runs / job_id).rglob("*")) if (runs / job_id).exists() else []
    known_bug(not (runs / job_id).exists(), f"files of the deleted job are still on disk: {left}")


# ── R8: the dpi a job runs at ───────────────────────────────────────────────────

@pytest.mark.parametrize("dpi", [50000, 401, 71, 0, -1])
@pytest.mark.xfail(strict=True, raises=KnownBug, reason="review2 R8: the OCR route takes any dpi; the 72-400 schema is never used")
def test_r8_1_an_out_of_range_dpi_never_runs_a_job_at_that_dpi(ocr, dpi):
    response = upload(ocr, dpi=dpi)
    wait_idle(ocr.service())
    if response.status_code == 422:
        assert ocr.store.runs == {} and list(ocr.runs.iterdir()) == [], "a refused request still made a job"
        return
    assert response.status_code == 201, response.text
    known_bug(72 <= int(response.json()["dpi"]) <= 400, f"a job was made at dpi={response.json()['dpi']}")


@pytest.mark.parametrize("dpi", [72, 200, 400])
def test_r8_2_a_dpi_in_range_makes_a_job(ocr, dpi):
    response = upload(ocr, dpi=dpi)
    assert response.status_code == 201, response.text
    wait_idle(ocr.service())
    assert ocr.http.get(f"/api/ocr/jobs/{response.json()['id']}").json()["status"] == "completed"


# ── C: page ranges ──────────────────────────────────────────────────────────────

def three_page_pdf() -> bytes:
    import fitz
    document = fitz.open()
    for number in range(1, 4):
        document.new_page(width=200, height=200).insert_text((20, 40), f"Trang {number}")
    try:
        return document.tobytes()
    finally:
        document.close()


def run_pdf(service, page_range: str):
    """Make and run a job over a three-page PDF. Returns the finished job, or the ValueError
    the request was refused with."""
    pdf = UploadFile(file=io.BytesIO(three_page_pdf()), filename="ba-trang.pdf")
    try:
        created = asyncio.run(service.create(pdf, 72, page_range, "all"))
    except ValueError as error:
        return error
    wait_idle(service)
    return service.view(created["id"])


@pytest.fixture
def pdf_service(tmp_path, monkeypatch):
    quiet_ocr(monkeypatch)
    service = OcrJobService(ocr_router_stub(), tmp_path / "data" / "runs", MemoryOcrStore())
    yield service
    wait_idle(service)


@pytest.mark.xfail(strict=True, raises=KnownBug,
                   reason="review2 C: the page range is built in full before it is checked against the page count")
def test_c1_a_huge_page_range_is_refused_without_building_it(pdf_service):
    tracemalloc.start()
    try:
        outcome = run_pdf(pdf_service, "1-1000000")
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert isinstance(outcome, ValueError) or outcome["status"] == "failed", "a range past the last page was accepted"
    known_bug(peak < 8 * 2**20, f"refusing it took a {peak / 2**20:.1f} MiB peak")


@pytest.mark.parametrize(("page_range", "pages"), [
    ("1-3", [1, 2, 3]), (" 1 - 2 ", [1, 2]), ("1,1,2", [1, 2]),
    ("5-1", None), ("0", None), ("-1", None), ("1-2-3", None), ("a-b", None), ("1,", None), ("4", None),
])
def test_c2_a_page_range_selects_exactly_its_pages_or_is_refused(pdf_service, page_range, pages):
    outcome = run_pdf(pdf_service, page_range)
    if pages is None:
        assert isinstance(outcome, ValueError) or outcome["status"] == "failed", outcome
    else:
        assert not isinstance(outcome, ValueError) and outcome["status"] == "completed", outcome
        assert [page["page"] for page in outcome["pages"]] == pages
