"""Review2 E: an OCR job has no owner, so with accounts on any member reads, cancels,
exports, evaluates or promotes another member's job.

The real app with accounts on (client + auth_on), MOCK_OCR, a PNG page. The job's folder is
under tmp_path and promotion is recorded instead of run, so nothing outside the test changes.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from review2_support import PNG, KnownBug, known_bug, quiet_ocr, wait_idle
from test_auth_api import SERVICE_KEY, auth_on, bearer, factory, register  # noqa: F401  (fixtures and helpers)

PASSWORD = "matkhau-123"


@pytest.fixture
def job_of_a(client, mock_ollama, auth_on, tmp_path, monkeypatch):  # noqa: F811
    quiet_ocr(monkeypatch)
    service = client.app.state.ocr_job_service
    monkeypatch.setattr(service, "runs_path", tmp_path / "data" / "runs")
    promoted: list[str] = []

    def record_promotion(job):
        promoted.append(str(job["id"]))
        return {"document_id": "doc_review2", "duplicate": False, "reused_ocr": True, "ingestion": None}

    monkeypatch.setattr(client.app.state.document_service, "promote_ocr_run", record_promotion)
    tag = uuid4().hex[:6]
    root = register(client, f"p3-e-root-{tag}")
    assert root.status_code == 201, root.text
    headers = {"admin": bearer(root.json()["access_token"])}
    for name in ("a", "b"):
        username = f"p3-e-{name}-{tag}"
        created = client.post("/auth/users", json={"username": username, "password": PASSWORD}, headers=headers["admin"])
        assert created.status_code == 201 and created.json()["role"] == "member", created.text
        login = client.post("/auth/login", json={"username": username, "password": PASSWORD})
        assert login.status_code == 200, login.text
        headers[name] = bearer(login.json()["access_token"])
    made = client.post("/api/ocr/jobs", files={"file": ("trang.png", PNG, "image/png")}, headers=headers["a"])
    assert made.status_code == 201, made.text
    job_id = made.json()["id"]
    wait_idle(service)
    seen_by_a = client.get(f"/api/ocr/jobs/{job_id}", headers=headers["a"])
    assert seen_by_a.status_code == 200 and seen_by_a.json()["status"] == "completed", seen_by_a.text
    try:
        yield SimpleNamespace(client=client, job_id=job_id, headers=headers, before=seen_by_a.json(), promoted=promoted)
    finally:
        wait_idle(service)
        service.delete(job_id)


ACTIONS = {
    "history": ("get", "/api/ocr/history", None),
    "open": ("get", "/api/ocr/jobs/{job}", None),
    "events": ("get", "/api/ocr/jobs/{job}/events", None),
    "files": ("get", "/api/ocr/jobs/{job}/files/pages/page_0001/original.png", None),
    "export": ("get", "/api/ocr/jobs/{job}/export", None),
    "cancel": ("post", "/api/ocr/jobs/{job}/cancel", None),
    "promote": ("post", "/api/ocr/jobs/{job}/promote", None),
    "evaluate": ("post", "/api/ocr/jobs/{job}/evaluate", {"ground_truth": "Trang thử."}),
}


@pytest.mark.parametrize("action", list(ACTIONS))
@pytest.mark.xfail(strict=True, raises=KnownBug,
                   reason="review2 E: an OCR job has no owner, so any signed-in member can reach another member's job")
def test_e1_a_member_cannot_reach_another_members_ocr_job(job_of_a, action):
    client, job_id = job_of_a.client, job_of_a.job_id
    method, path, body = ACTIONS[action]
    response = client.request(method.upper(), path.format(job=job_id), json=body, headers=job_of_a.headers["b"])
    if action == "history":
        assert response.status_code in (200, 403, 404), response.text
        known_bug(response.status_code != 200 or job_id not in response.text, "B's OCR history lists A's job")
    else:
        known_bug(response.status_code in (403, 404), f"B's {action} on A's job answered {response.status_code}")
    after = client.get(f"/api/ocr/jobs/{job_id}", headers=job_of_a.headers["a"])
    assert after.status_code == 200 and after.json() == job_of_a.before, "A's job changed"
    assert job_of_a.promoted == []


@pytest.mark.parametrize(("who", "status"), [("owner", 200), ("admin", 200), ("service_key", 200), ("anonymous", 401)])
def test_e2_the_owner_an_admin_and_the_service_key_open_the_job_and_nobody_else_without_signing_in(job_of_a, who, status):
    headers = {"owner": job_of_a.headers["a"], "admin": job_of_a.headers["admin"],
               "service_key": {"X-API-Key": SERVICE_KEY}, "anonymous": {}}[who]
    assert job_of_a.client.get(f"/api/ocr/jobs/{job_of_a.job_id}", headers=headers).status_code == status
