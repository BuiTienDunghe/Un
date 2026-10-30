"""Ticket 40: the OCR screen copies what a PDF already holds, and reads only the pages that are pictures."""
from __future__ import annotations

import io
import time
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from fastapi import UploadFile

from app.services.ocr_job_service import OcrJobService
from app.services.ocr_service import OcrResult

TEXT = "Đây là một trang có sẵn chữ thật, đủ dài để không cần đọc bằng model nữa. " * 3


class CountingOcr:
    def __init__(self) -> None:
        self.calls = 0

    def config_hash(self, dpi):
        return "hash"

    def render_pages(self, source, dpi, page_numbers=None):
        return [(number, b"png") for number in page_numbers]

    def recognize_png(self, png, dpi, *, allow_mock=False):
        self.calls += 1
        return OcrResult(text="chữ do model đọc", model="m", config_hash="hash", cache_hit=False)


def pdf_with_one_text_page_and_one_blank() -> bytes:
    document = fitz.open()
    document.new_page().insert_textbox(fitz.Rect(40, 40, 560, 400), TEXT, fontname="helv")
    document.new_page()
    return document.tobytes()


def run(tmp_path: Path, force: bool) -> tuple[dict, CountingOcr]:
    ocr = CountingOcr()
    store = SimpleNamespace(save_ocr_run=lambda *args: None, list_ocr_runs=lambda: [])
    service = OcrJobService(SimpleNamespace(models={"ocr": {"name": "m"}}), tmp_path, store, ocr)
    upload = UploadFile(io.BytesIO(pdf_with_one_text_page_and_one_blank()), filename="a.pdf")

    async def create():
        return await service.create(upload, 200, None, "all", force)

    import asyncio

    job_id = asyncio.run(create())["id"]
    deadline = time.monotonic() + 15
    while service.jobs[job_id]["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.02)
    return service.jobs[job_id], ocr


def test_a_page_with_text_skips_the_model_and_a_blank_page_does_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOCK_OCR", raising=False)
    job, ocr = run(tmp_path, False)
    assert job["status"] == "completed" and ocr.calls == 1
    first, second = job["pages"]
    assert first["extraction_method"] == "native" and first["model"] is None and first["text"] != "chữ do model đọc"
    assert second["extraction_method"] == "ocr" and second["text"] == "chữ do model đọc"


def test_forcing_reads_every_page_with_the_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOCK_OCR", raising=False)
    job, ocr = run(tmp_path, True)
    assert ocr.calls == 2 and {page["extraction_method"] for page in job["pages"]} == {"ocr"}
