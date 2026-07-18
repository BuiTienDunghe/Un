from app.services.ocr_job_service import OcrJobService
from app.services.ocr_metrics_service import evaluate_ocr
import time


def test_ocr_metrics_are_exact_for_matching_text():
    result = evaluate_ocr("xin chao", "xin chao")
    assert result["cer"] == 0
    assert result["wer"] == 0
    assert result["character_accuracy"] == 1


def test_page_ranges_are_parsed_and_validated():
    assert OcrJobService._select_pages(5, "1-2,4") == [1, 2, 4]
    try:
        OcrJobService._select_pages(5, "6")
    except ValueError:
        pass
    else:
        raise AssertionError("Out-of-range page should be rejected")


def test_mock_ocr_job_creates_page_result(client, monkeypatch):
    monkeypatch.setenv("MOCK_OCR", "true")
    png = b"\x89PNG\r\n\x1a\n" + b"mock"
    response = client.post("/api/ocr/jobs", files={"file": ("sample.png", png, "image/png")})
    assert response.status_code == 201
    job_id = response.json()["id"]
    for _ in range(30):
        job = client.get(f"/api/ocr/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.03)
    assert job["status"] == "completed"
    assert job["pages"][0]["text"].startswith("[MOCK OCR]")


def test_completed_ocr_run_can_be_promoted_without_repeating_ocr(client, mock_ollama, monkeypatch):
    monkeypatch.setenv("MOCK_OCR", "true")
    monkeypatch.setattr("app.stores.qdrant_store.QdrantStore.upsert_chunks", lambda *args, **kwargs: None)
    png = b"\x89PNG\r\n\x1a\n" + str(time.time_ns()).encode("ascii")
    created = client.post("/api/ocr/jobs", files={"file": ("sample.png", png, "image/png")})
    job_id = created.json()["id"]
    for _ in range(30):
        job = client.get(f"/api/ocr/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.03)
    assert job["status"] == "completed"

    promoted = client.post(f"/api/ocr/jobs/{job_id}/promote")
    assert promoted.status_code == 202
    assert promoted.json()["reused_ocr"] is True
    run_id = promoted.json()["ingestion_run_id"]
    for _ in range(30):
        run = client.get(f"/documents/ingestions/{run_id}").json()
        if run["status"] in {"completed", "failed"}:
            break
        time.sleep(0.03)
    assert run["status"] == "completed"
