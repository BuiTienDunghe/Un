"""Layer-1 API key behaviour (P0-2).

The key is set on `app.state.settings` per test rather than through the
environment: `Settings` is cached with `lru_cache`, and the guard reads the
live settings object, so this exercises exactly the production lookup.
"""
from __future__ import annotations

import pytest

KEY = "test-secret-key"

# One representative per protected surface, plus the reads that must stay open.
WRITE_REQUESTS = [
    ("delete", "/conversations/does-not-exist"),
    ("patch", "/conversations/does-not-exist"),
    ("delete", "/documents/does-not-exist"),
    ("patch", "/documents/does-not-exist/retention"),
    ("post", "/documents/index"),
    ("post", "/memory/add"),
    ("delete", "/memory/does-not-exist"),
    ("post", "/api/ocr/jobs"),
    ("post", "/chat"),
    ("post", "/rag/chat"),
    ("post", "/api/discord/sessions/resolve"),
    ("post", "/api/memory-review/candidates/00000000-0000-0000-0000-000000000000/approve"),
    ("post", "/api/memory-review/candidates/00000000-0000-0000-0000-000000000000/reject"),
    ("post", "/api/memory-review/candidates/00000000-0000-0000-0000-000000000000/revert"),
    ("post", "/api/bot/start"),
    ("post", "/api/bot/stop"),
]

READ_REQUESTS = [
    ("get", "/health"),
    ("get", "/models"),
    ("get", "/conversations"),
    ("get", "/documents"),
    ("get", "/api/dashboard/stats"),
    # POST, but a pure read: retrieval without generation or persistence.
    ("post", "/rag/search"),
]


@pytest.fixture
def secured(client):
    client.app.state.settings.local_ai_api_key = KEY
    yield client
    client.app.state.settings.local_ai_api_key = ""
    client.app.state.settings.local_ai_protect_reads = False


@pytest.mark.parametrize("method,path", WRITE_REQUESTS)
def test_a_write_without_the_key_is_rejected(secured, method, path):
    response = secured.request(method, path, json={})

    assert response.status_code == 401
    assert response.json()["error_code"] == "API_KEY_REQUIRED"


@pytest.mark.parametrize("method,path", WRITE_REQUESTS)
def test_a_write_with_a_wrong_key_is_rejected(secured, method, path):
    response = secured.request(method, path, json={}, headers={"X-API-Key": "not-the-key"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "API_KEY_INVALID"


@pytest.mark.parametrize("method,path", WRITE_REQUESTS)
def test_the_right_key_gets_past_the_guard(secured, method, path):
    response = secured.request(method, path, json={}, headers={"X-API-Key": KEY})

    # Past the guard the request meets ordinary validation or 404 handling;
    # what matters here is that it is no longer refused as unauthenticated.
    assert response.status_code != 401


@pytest.mark.parametrize("method,path", READ_REQUESTS)
def test_reads_stay_open_by_default(secured, method, path):
    assert secured.request(method, path).status_code != 401


@pytest.mark.parametrize("method,path", READ_REQUESTS)
def test_protect_reads_closes_everything_except_health_and_models(secured, method, path):
    secured.app.state.settings.local_ai_protect_reads = True

    response = secured.request(method, path)

    # /health and /models are what the launcher, the smoke test and the Settings
    # dialog read before a key can possibly be supplied.
    if path in {"/health", "/models"}:
        assert response.status_code != 401
    else:
        assert response.status_code == 401
        assert response.json()["error_code"] == "API_KEY_REQUIRED"


def test_no_configured_key_leaves_every_endpoint_open(client):
    # The default single-user install must keep working without a key, or the
    # one-click launcher would open a UI that cannot send a message.
    assert client.app.state.settings.local_ai_api_key == ""
    assert client.get("/conversations").status_code == 200
    assert client.delete("/conversations/does-not-exist").status_code == 404


def test_the_key_comparison_is_not_prefix_based(secured):
    for candidate in (KEY[:-1], KEY + "x", KEY.upper(), " "):
        response = secured.delete("/conversations/x", headers={"X-API-Key": candidate})
        assert response.status_code == 401
