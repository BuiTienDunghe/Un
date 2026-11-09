import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.ocr import router as ocr_router
from app.routers.vision import router as vision_router
from app.services.ocr_evidence import parse_evidence
from app.services.ocr_job_service import OcrJobService
from app.services.ocr_service import OcrResult


def test_registered_lfm_reader_disables_thinking_for_bounded_selection(monkeypatch):
    from app.config.model_registry import load_registry
    from app.llm_clients.ollama_client import OllamaClient
    from app.services.model_router import ModelRouter
    from app.services.ocr_reader import read_evidence

    calls = []
    client = OllamaClient("http://localhost:11434", chat_timeout=60, health_timeout=3, retry_count=0)
    monkeypatch.setattr(client, "chat", lambda **kwargs: (calls.append(kwargs) or '{"block_ids":["p1b1"]}'))
    config = dict(load_registry().get("general", "general-lfm-small-v1").config)
    answer = read_evidence(ModelRouter({"ollama": client}, {"general": config}), "Mã phiếu?", [
        {"id": "p1b1", "page": 1, "kind": "text", "text": "Mã phiếu: VT-4068"}])
    assert answer["status"] == "cited"
    assert calls[0]["think"] is False and calls[0]["options"]["num_predict"] == 128
    assert all(set(message) == {"role", "content"} for message in calls[0]["messages"])


def test_archived_evidence_is_read_by_text_model_and_missing_phone_skips_call(tmp_path):
    calls = []
    class Router:
        models = {"general": {"name": "text-only"}}
        def chat_structured(self, mode, messages, schema, **kwargs):
            calls.append(messages)
            return '{"block_ids":["p1b1"]}', "text-only"
    archived = {"id": "ocr_archived", "status": "completed", "pages": [
        {"page": 1, "text": "Người nhận: Phạm Ngọc Quỳnh", "blocks": [
            {"id": "p1b1", "page": 1, "kind": "text", "text": "Người nhận: Phạm Ngọc Quỳnh"}]}]}
    store = SimpleNamespace(list_ocr_runs=lambda: [{"id": "ocr_archived", "result_json": json.dumps(archived)}])
    app = FastAPI()
    app.state.settings = SimpleNamespace(local_ai_auth_enabled=False, local_ai_api_key="")
    app.state.ocr_job_service = OcrJobService(Router(), tmp_path, store)
    app.include_router(ocr_router)
    with TestClient(app) as client:
        response = client.post("/api/ocr/jobs/ocr_archived/ask", json={"question": "Người nhận là ai?"})
        assert response.status_code == 200 and response.json()["status"] == "cited"
        assert response.json()["message"] == "Người nhận: Phạm Ngọc Quỳnh"
        assert all(set(message) == {"role", "content"} for message in calls[0])
        missing = client.post("/api/ocr/jobs/ocr_archived/ask", json={"question": "Số điện thoại người nhận là gì?"})
        assert missing.json()["status"] == "insufficient_evidence" and len(calls) == 1
        assert client.post("/api/ocr/jobs/absent/ask", json={"question": "Ai?"}).status_code == 404
        assert client.post("/api/ocr/jobs/ocr_archived/ask", json={"question": "Ai?", "pages": [9]}).status_code == 422


def test_vision_off_routes_image_to_ocr_without_calling_general():
    calls = []
    class Ocr:
        def recognize_png(self, png, dpi):
            calls.append((png, dpi))
            return OcrResult("Mã: AB-17", "small-ocr", "hash", False, blocks=parse_evidence("Mã: AB-17"))
    app = FastAPI()
    app.state.settings = SimpleNamespace(local_ai_auth_enabled=False, local_ai_api_key="")
    app.state.model_router = SimpleNamespace(models={"general": {"name": "text-only"}, "ocr": {"enabled": True}})
    app.state.ocr_service = Ocr()
    app.include_router(vision_router)
    with TestClient(app) as client:
        response = client.post("/vision/chat", json={"message": "Mã là gì?", "image_base64": "cG5n"})
        assert response.status_code == 200
        assert response.json()["mode"] == "ocr_evidence" and response.json()["message"] == "Mã: AB-17"
        assert calls == [(b"png", 200)]
        assert client.post("/vision/chat", json={"message": "Ai?", "image_base64": "***"}).status_code == 422
