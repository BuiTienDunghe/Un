"""Router /research trên một app FastAPI trần với dịch vụ giả — không cần Postgres.

Kiểm tra hợp đồng HTTP (mã trạng thái, `error_code`, hình dữ liệu, SSE của
/research/chat); logic cơ sở dữ liệu nằm trong ResearchService và chỉ chạy được
khi có Postgres.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm_clients.ollama_client import OllamaTimeoutError
from app.main import http_error_handler
from app.routers import research
from app.security.api_key import require_api_key_for_read
from app.services.research_service import NotIndexedError, PaperNotFoundError, ProjectNotFoundError, SummaryMissingError
from fastapi import Depends, HTTPException

NOW = "2026-10-11T08:00:00+00:00"


def _paper_row(**overrides):
    row = {
        "id": "pap_1", "document_id": "doc_1", "short_name": "Attention", "title": "Attention Is All You Need", "authors": "Vaswani et al.",
        "venue": None, "year": 2017, "arxiv_id": "1706.03762", "doi": None, "url": None, "cluster_id": None, "status": "unread", "stars": 0,
        "last_page": 1, "tags": [], "total_pages": 15, "annotation_count": 0, "has_summary": False, "document_status": "indexed", "indexed": True,
        "stages": {"ocr": "done", "metadata": "done", "outline": "done", "summary": "pending"}, "added_at": NOW, "updated_at": NOW,
    }
    row.update(overrides)
    return row


class FakeResearchService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.project = {"id": "prj_1", "name": "RAG tiếng Việt", "description": None, "insights": None, "insights_at": None, "clusters": [], "papers": [_paper_row()], "edges": [], "updated_at": NOW}

    def _check(self, project_id):
        if project_id != "prj_1":
            raise ProjectNotFoundError(project_id)

    def list_projects(self, owner):
        self.calls.append(("list", owner))
        return [{"id": "prj_1", "name": "RAG tiếng Việt", "description": None, "paper_count": 1, "read_count": 0, "updated_at": NOW}]

    def create_project(self, owner, name, description):
        self.calls.append(("create", owner, name, description))
        return {**self.project, "name": name, "description": description, "papers": []}

    def get_project(self, owner, project_id):
        self._check(project_id)
        return self.project

    def patch_project(self, owner, project_id, changes):
        self._check(project_id)
        self.calls.append(("patch_project", changes))
        return {**self.project, **changes}

    def delete_project(self, owner, project_id):
        self._check(project_id)

    def generate_insights(self, owner, project_id):
        self._check(project_id)
        if project_id == "prj_1" and getattr(self, "no_summary", False):
            raise SummaryMissingError(project_id)
        return {"insights": {"overview": "o", "central": "c", "trend": "t", "gap": "g"}, "insights_at": NOW}

    def bibtex(self, owner, project_id):
        self._check(project_id)
        return "@article{Attention2017,\n  title = {Attention Is All You Need}\n}\n"

    def create_cluster(self, owner, project_id, name, color_index):
        self._check(project_id)
        return {"id": "clu_1", "name": name, "color_index": color_index, "position": 0}

    def create_edge(self, owner, project_id, payload):
        self._check(project_id)
        return {"id": "edg_1", **payload, "confidence": None, "source": "manual", "created_at": NOW}

    async def add_paper_files(self, owner, project_id, files, max_bytes):
        self._check(project_id)
        self.calls.append(("upload", [file.filename for file in files], max_bytes))
        return [_paper_row(id=f"pap_{index}", document_status="uploaded", indexed=False) for index, _ in enumerate(files, start=1)]

    def attach_paper(self, owner, project_id, document_id, filename=None):
        self._check(project_id)
        return _paper_row(document_id=document_id)

    def get_paper(self, owner, paper_id):
        if paper_id != "pap_1":
            raise PaperNotFoundError(paper_id)
        return {**_paper_row(), "summary": None, "summary_model": None, "summary_at": None, "outline": {"toc": [], "figures": []}, "note_md": None, "annotations": []}

    def patch_paper(self, owner, paper_id, changes):
        if paper_id != "pap_1":
            raise PaperNotFoundError(paper_id)
        self.calls.append(("patch_paper", changes))
        return _paper_row(**{key: value for key, value in changes.items() if key in _paper_row()})

    def generate_summary(self, owner, paper_id):
        if paper_id == "pap_slow":
            raise OllamaTimeoutError("Ollama không trả lời trước hạn 180 giây.")
        if paper_id != "pap_1":
            raise NotIndexedError(paper_id)
        return {"summary": {"brief": "b", "questions": ["1", "2", "3"]}, "summary_model": "qwen3:8b", "summary_at": NOW}

    def export_markdown(self, owner, paper_id):
        return "# Attention Is All You Need\n"

    def chat_scope(self, owner, scope, target_id):
        if target_id == "prj_empty":
            raise NotIndexedError(target_id)
        return ["doc_1"], {"doc_1": {"paper_id": "pap_1", "short_name": "Attention", "color_index": 2}}


class FakeRagService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def stream_response(self, question, top_k, document_ids, conversation_id=None, user_id=None):
        self.calls.append((question, top_k, document_ids, conversation_id, user_id))
        source = {"document_id": "doc_1", "filename": "attention.pdf", "chunk_id": "chunk_1", "chunk_index": 0, "index_version": 1, "page": 3, "page_start": 3, "page_end": 3, "score": 0.9, "content": "Scaled dot-product attention"}
        return iter(["Xin ", "chào"]), "qwen3:8b", [source], "conv_1", None


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(research.router, dependencies=[Depends(require_api_key_for_read)])
    app.add_exception_handler(HTTPException, http_error_handler)
    app.state.settings = SimpleNamespace(local_ai_auth_enabled=False, local_ai_api_key="", local_ai_protect_reads=False, max_upload_size_bytes=1024)
    app.state.research_service = FakeResearchService()
    app.state.rag_service = FakeRagService()
    with TestClient(app) as client:
        yield client


def test_projects_list_and_create(api):
    assert api.get("/research/projects").json()[0]["paper_count"] == 1
    created = api.post("/research/projects", json={"name": "Mới"})
    assert created.status_code == 201
    assert created.json()["name"] == "Mới" and created.json()["papers"] == []
    assert api.post("/research/projects", json={"name": ""}).status_code == 422


def test_unknown_project_uses_the_research_error_code(api):
    response = api.get("/research/projects/prj_missing")
    assert response.status_code == 404
    assert response.json()["error_code"] == "RESEARCH_PROJECT_NOT_FOUND"
    assert api.delete("/research/projects/prj_missing").json()["error_code"] == "RESEARCH_PROJECT_NOT_FOUND"


def test_project_patch_requires_at_least_one_field(api):
    assert api.patch("/research/projects/prj_1", json={}).status_code == 422
    assert api.patch("/research/projects/prj_1", json={"description": "x"}).json()["description"] == "x"
    assert api.delete("/research/projects/prj_1").status_code == 204


def test_insights_409_when_no_paper_has_a_summary(api):
    api.app.state.research_service.no_summary = True
    response = api.post("/research/projects/prj_1/insights")
    assert response.status_code == 409
    assert response.json()["error_code"] == "RESEARCH_SUMMARY_MISSING"
    api.app.state.research_service.no_summary = False
    assert api.post("/research/projects/prj_1/insights").json()["insights"]["gap"] == "g"


def test_bibtex_is_plain_text(api):
    response = api.get("/research/projects/prj_1/bibtex")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text.startswith("@article{Attention2017,")


def test_clusters_and_edges_validate_their_enums(api):
    assert api.post("/research/projects/prj_1/clusters", json={"name": "Reranker", "color_index": 3}).status_code == 201
    assert api.post("/research/projects/prj_1/clusters", json={"name": "Reranker", "color_index": 9}).status_code == 422
    edge = api.post("/research/projects/prj_1/edges", json={"a_paper_id": "pap_1", "b_paper_id": "pap_2", "type": "builds"})
    assert edge.status_code == 201 and edge.json()["source"] == "manual"
    assert api.post("/research/projects/prj_1/edges", json={"a_paper_id": "pap_1", "b_paper_id": "pap_2", "type": "cites"}).status_code == 422


def test_papers_multipart_upload_returns_one_row_per_file(api):
    response = api.post("/research/projects/prj_1/papers", files=[("files", ("a.pdf", b"%PDF-1.4", "application/pdf")), ("files", ("b.pdf", b"%PDF-1.4", "application/pdf"))])
    assert response.status_code == 201
    rows = response.json()
    assert [row["id"] for row in rows] == ["pap_1", "pap_2"]
    assert rows[0]["stages"]["ocr"] == "done" and rows[0]["indexed"] is False
    assert ("upload", ["a.pdf", "b.pdf"], 1024) in api.app.state.research_service.calls


def test_papers_json_attach_and_fetch_unsupported(api):
    attached = api.post("/research/projects/prj_1/papers", json={"document_id": "doc_9"})
    # Gắn một tài liệu → MỘT PaperRow (spec), khác với multipart trả danh sách.
    assert attached.status_code == 201 and attached.json()["document_id"] == "doc_9"
    fetch = api.post("/research/projects/prj_1/papers", json={"url": "https://arxiv.org/abs/1706.03762"})
    assert fetch.status_code == 501
    assert fetch.json() == {"error": True, "error_code": "RESEARCH_FETCH_UNSUPPORTED", "message": "Máy chủ chạy offline; tải PDF rồi thả vào.", "detail": None}
    assert api.post("/research/projects/prj_1/papers", json={}).status_code == 422
    assert api.post("/research/projects/prj_missing/papers", json={"document_id": "doc_9"}).json()["error_code"] == "RESEARCH_PROJECT_NOT_FOUND"


def test_paper_detail_patch_and_errors(api):
    detail = api.get("/research/papers/pap_1").json()
    assert detail["annotations"] == [] and detail["outline"] == {"toc": [], "figures": []}
    assert api.get("/research/papers/pap_x").json()["error_code"] == "RESEARCH_PAPER_NOT_FOUND"
    assert api.patch("/research/papers/pap_1", json={}).status_code == 422
    assert api.patch("/research/papers/pap_1", json={"stars": 6}).status_code == 422
    patched = api.patch("/research/papers/pap_1", json={"status": "reading", "last_page": 7})
    assert patched.status_code == 200 and patched.json()["last_page"] == 7
    assert ("patch_paper", {"status": "reading", "last_page": 7}) in api.app.state.research_service.calls


def test_summary_maps_service_errors(api):
    assert api.post("/research/papers/pap_1/summary").json()["summary_model"] == "qwen3:8b"
    missing = api.post("/research/papers/pap_2/summary")
    assert missing.status_code == 409 and missing.json()["error_code"] == "RESEARCH_NOT_INDEXED"
    slow = api.post("/research/papers/pap_slow/summary")
    assert slow.status_code == 504 and slow.json()["error_code"] == "MODEL_TIMEOUT"


def test_export_is_markdown(api):
    response = api.get("/research/papers/pap_1/export.md")
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("# ")


def test_chat_streams_rag_events_with_the_papers_map(api):
    with api.stream("POST", "/research/chat", json={"scope": "paper", "id": "pap_1", "question": "Giải thích", "quote": "attention"}) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    events = [line for line in body.split("\n\n") if line]
    assert events[0].startswith("event: meta\n")
    assert '"papers": {"doc_1": {"paper_id": "pap_1", "short_name": "Attention", "color_index": 2}}' in events[0]
    assert '"sources": [{"document_id": "doc_1"' in events[0]
    assert events[1] == 'event: token\ndata: {"content": "Xin "}' and events[2] == 'event: token\ndata: {"content": "chào"}'
    assert events[3].startswith("event: done\n")
    question, top_k, document_ids, conversation_id, user_id = api.app.state.rag_service.calls[0]
    assert question == 'Đoạn trích: "attention"\n\nCâu hỏi: Giải thích' and document_ids == ["doc_1"]


def test_chat_409_when_nothing_in_scope_is_indexed(api):
    response = api.post("/research/chat", json={"scope": "project", "id": "prj_empty", "question": "?"})
    assert response.status_code == 409
    assert response.json()["error_code"] == "RESEARCH_NOT_INDEXED"
    assert api.post("/research/chat", json={"scope": "all", "id": "x", "question": "?"}).status_code == 422


def test_write_routes_require_the_api_key_when_one_is_configured(api):
    api.app.state.settings.local_ai_api_key = "secret"
    assert api.get("/research/projects").status_code == 200
    denied = api.post("/research/projects", json={"name": "x"})
    assert denied.status_code == 401 and denied.json()["error_code"] == "API_KEY_REQUIRED"
    assert api.post("/research/chat", json={"scope": "paper", "id": "pap_1", "question": "?"}).status_code == 401
    assert api.post("/research/projects", json={"name": "x"}, headers={"X-API-Key": "secret"}).status_code == 201


def test_member_identity_scopes_projects_but_admin_sees_everything(api):
    import jwt as pyjwt

    api.app.state.settings.local_ai_auth_enabled = True
    api.app.state.settings.local_ai_jwt_secret = "test-secret"
    member = pyjwt.encode({"sub": "11111111-1111-1111-1111-111111111111", "type": "access", "role": "member", "username": "m"}, "test-secret", algorithm="HS256")
    admin = pyjwt.encode({"sub": "22222222-2222-2222-2222-222222222222", "type": "access", "role": "admin", "username": "a"}, "test-secret", algorithm="HS256")

    assert api.get("/research/projects").status_code == 401  # bật tài khoản → đọc cũng cần danh tính
    assert api.get("/research/projects", headers={"Authorization": f"Bearer {member}"}).status_code == 200
    assert api.post("/research/projects", json={"name": "x"}, headers={"Authorization": f"Bearer {admin}"}).status_code == 201
    calls = api.app.state.research_service.calls
    assert ("list", "11111111-1111-1111-1111-111111111111") in calls
    assert ("create", None, "x", None) in calls
