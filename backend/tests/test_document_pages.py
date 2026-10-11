"""Bốn route trang tài liệu của trình đọc (/documents/{id}/source, pages/{n}.png,
pages/{n}/words, pages/{n}/boxes) trên app FastAPI trần với document_service giả.

Dịch vụ giả chỉ trả đường dẫn tệp — phần PDF thật (render, lớp chữ) chạy thật
bằng PyMuPDF trên một tệp sinh trong tmp_path, nên không chạm `data/`.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.main import http_error_handler
from app.routers import documents
from app.security.api_key import require_api_key_for_read
from app.services.postgres_document_service import DocumentNotFoundError, SourceUnavailableError


def _pdf(path: Path, pages: int = 2) -> Path:
    document = fitz.open()
    for number in range(1, pages + 1):
        page = document.new_page(width=300, height=400)
        page.insert_text((30, 50), f"Trang {number} xin chao", fontsize=14)
    document.save(str(path))
    document.close()
    return path


class FakeDocumentService:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "doc_pdf").mkdir(parents=True, exist_ok=True)
        self.sources = {"doc_pdf": (_pdf(root / "doc_pdf" / "original.pdf"), "paper one.pdf")}
        (root / "doc_txt").mkdir(parents=True, exist_ok=True)
        text = root / "doc_txt" / "original.txt"
        text.write_text("plain", encoding="utf-8")
        self.sources["doc_txt"] = (text, "notes.txt")
        self.locations = {"chunk_1": [{"page": 1, "start": 0, "end": 10}], "chunk_box": [{"page": 2, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.2}]}

    def source_file(self, document_id: str):
        if document_id == "doc_gone":
            raise SourceUnavailableError(document_id)
        if document_id not in self.sources:
            raise DocumentNotFoundError(document_id)
        return self.sources[document_id]

    def page_cache_dir(self, document_id: str) -> Path:
        return self.root / document_id / "pages"

    def chunk_locations(self, document_id: str, chunk_id: str):
        if document_id == "doc_missing":
            raise DocumentNotFoundError(document_id)
        return self.locations.get(chunk_id)


@pytest.fixture
def api(tmp_path):
    app = FastAPI()
    app.include_router(documents.router, dependencies=[Depends(require_api_key_for_read)])
    app.add_exception_handler(HTTPException, http_error_handler)
    app.state.settings = SimpleNamespace(local_ai_auth_enabled=False, local_ai_api_key="", local_ai_protect_reads=False)
    app.state.document_service = FakeDocumentService(tmp_path)
    with TestClient(app) as client:
        yield client


def test_source_is_served_inline_with_its_display_name(api):
    response = api.get("/documents/doc_pdf/source")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert "paper one.pdf" in response.headers["content-disposition"] or "paper%20one.pdf" in response.headers["content-disposition"]
    assert response.content[:5] == b"%PDF-"


def test_source_errors(api):
    gone = api.get("/documents/doc_gone/source")
    assert gone.status_code == 409 and gone.json()["error_code"] == "RESEARCH_SOURCE_UNAVAILABLE"
    missing = api.get("/documents/doc_nope/source")
    assert missing.status_code == 404 and missing.json()["error_code"] == "DOCUMENT_NOT_FOUND"


def test_page_png_renders_clamps_dpi_and_caches(api, tmp_path):
    response = api.get("/documents/doc_pdf/pages/2.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert (tmp_path / "doc_pdf" / "pages" / "2@110.png").is_file()
    assert api.get("/documents/doc_pdf/pages/1.png?dpi=160").status_code == 200
    assert (tmp_path / "doc_pdf" / "pages" / "1@160.png").is_file()
    assert api.get("/documents/doc_pdf/pages/1.png?dpi=10").status_code == 422
    assert api.get("/documents/doc_pdf/pages/1.png?dpi=999").status_code == 422


def test_page_png_404_out_of_range_or_not_a_pdf(api):
    out = api.get("/documents/doc_pdf/pages/3.png")
    assert out.status_code == 404 and out.json()["error_code"] == "DOCUMENT_PAGE_NOT_FOUND"
    assert api.get("/documents/doc_pdf/pages/0.png").json()["error_code"] == "DOCUMENT_PAGE_NOT_FOUND"
    text = api.get("/documents/doc_txt/pages/1.png")
    assert text.status_code == 404 and text.json()["error_code"] == "DOCUMENT_PAGE_NOT_FOUND"
    gone = api.get("/documents/doc_gone/pages/1.png")
    assert gone.status_code == 409 and gone.json()["error_code"] == "RESEARCH_SOURCE_UNAVAILABLE"


def test_page_words_are_unit_scaled(api):
    body = api.get("/documents/doc_pdf/pages/1/words").json()
    assert body["page"] == 1 and body["width"] == 300.0 and body["height"] == 400.0 and body["has_text"] is True
    texts = [word["text"] for word in body["words"]]
    assert texts[:2] == ["Trang", "1"]
    first = body["words"][0]
    assert 0 <= first["x0"] < first["x1"] <= 1 and 0 <= first["y0"] < first["y1"] <= 1
    assert set(first) == {"x0", "y0", "x1", "y1", "text", "block", "line"}
    assert api.get("/documents/doc_pdf/pages/9/words").json()["error_code"] == "DOCUMENT_PAGE_NOT_FOUND"


def test_page_boxes_come_from_chunk_locations(api):
    assert api.get("/documents/doc_pdf/pages/1/boxes", params={"chunk_id": "chunk_1"}).json() == {"boxes": []}
    assert api.get("/documents/doc_pdf/pages/2/boxes", params={"chunk_id": "chunk_box"}).json() == {"boxes": [{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.2}]}
    assert api.get("/documents/doc_pdf/pages/1/boxes", params={"chunk_id": "chunk_box"}).json() == {"boxes": []}
    assert api.get("/documents/doc_pdf/pages/1/boxes", params={"chunk_id": "unknown"}).json() == {"boxes": []}
    assert api.get("/documents/doc_pdf/pages/1/boxes").status_code == 422
    assert api.get("/documents/doc_missing/pages/1/boxes", params={"chunk_id": "c"}).json()["error_code"] == "DOCUMENT_NOT_FOUND"
