"""P3-1: accounts, JWT lane, RBAC matrix, and conversation ownership.

Auth is enabled per-test on the live app settings (monkeypatch reverts it),
so the rest of the suite keeps running in today's open single-user mode.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Conversation, User

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")

SECRET = "unit-test-secret-0123456789abcdef0123456789"
SERVICE_KEY = "service-key-p3"


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


@pytest.fixture
def auth_on(client, factory, monkeypatch):
    settings = client.app.state.settings
    monkeypatch.setattr(settings, "local_ai_auth_enabled", True)
    monkeypatch.setattr(settings, "local_ai_jwt_secret", SECRET)
    monkeypatch.setattr(settings, "local_ai_api_key", SERVICE_KEY)
    monkeypatch.setattr(client.app.state.auth_service, "jwt_secret", SECRET)
    yield
    with factory.begin() as session:
        user_ids = list(session.scalars(select(User.id).where(User.username.like("p3-%"))))
        if user_ids:
            session.execute(delete(Conversation).where(Conversation.user_id.in_(user_ids)))
            session.execute(delete(User).where(User.id.in_(user_ids)))


def register(client, username: str, password: str = "matkhau-123"):
    return client.post("/auth/register", json={"username": username, "password": password})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_auth_disabled_register_409_and_stale_bearer_is_ignored(client, mock_ollama):
    assert register(client, "p3-anyone").status_code == 409
    listed = client.get("/conversations", headers=bearer("stale-token-from-before"))
    assert listed.status_code == 200


def test_bootstrap_first_admin_then_registration_closes(client, mock_ollama, auth_on):
    config = client.get("/auth/config").json()
    assert config == {"enabled": True, "has_users": False}

    first = register(client, f"p3-admin-{uuid4().hex[:6]}")
    assert first.status_code == 201
    body = first.json()
    assert body["user"]["role"] == "admin" and body["access_token"] and body["refresh_token"]

    second = register(client, "p3-too-late")
    assert second.status_code == 409 and second.json()["error_code"] == "REGISTRATION_CLOSED"

    me = client.get("/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200 and me.json()["username"] == body["user"]["username"]


def test_login_refresh_logout_lifecycle_and_api_login_alias(client, mock_ollama, auth_on):
    username = f"p3-user-{uuid4().hex[:6]}"
    register(client, username)

    wrong = client.post("/auth/login", json={"username": username, "password": "sai-mat-khau"})
    assert wrong.status_code == 401 and wrong.json()["error_code"] == "LOGIN_INVALID"

    logged_in = client.post("/auth/login", json={"username": username, "password": "matkhau-123"}).json()
    refreshed = client.post("/auth/refresh", json={"refresh_token": logged_in["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] == logged_in["refresh_token"]  # non-rotating by design
    assert refreshed.json()["access_token"]

    # The Discord bot's built-in fallback lane.
    alias = client.post("/api/login", json={"username": username, "password": "matkhau-123"})
    assert alias.status_code == 200 and alias.json()["access_token"]

    assert client.post("/auth/logout", json={"refresh_token": logged_in["refresh_token"]}).status_code == 204
    dead = client.post("/auth/refresh", json={"refresh_token": logged_in["refresh_token"]})
    assert dead.status_code == 401


def test_rbac_matrix_member_admin_service_and_anonymous(client, mock_ollama, auth_on):
    admin = register(client, f"p3-admin-{uuid4().hex[:6]}").json()
    created = client.post(
        "/auth/users",
        json={"username": f"p3-member-{uuid4().hex[:6]}", "password": "matkhau-123", "role": "member"},
        headers=bearer(admin["access_token"]),
    )
    assert created.status_code == 201
    member = client.post("/auth/login", json={"username": created.json()["username"], "password": "matkhau-123"}).json()
    member_headers = bearer(member["access_token"])

    # Anonymous: fail closed.
    assert client.get("/conversations").status_code == 401
    assert client.post("/chat", json={"message": "hi"}).status_code == 401

    # Member: can chat, cannot touch the shared workspace's destructive or
    # oversight surfaces (the phase acceptance).
    chat = client.post("/chat", json={"message": "xin chào"}, headers=member_headers)
    assert chat.status_code == 200
    conversation_id = chat.json()["conversation_id"]
    assert client.delete("/documents/doc_khong_ton_tai", headers=member_headers).status_code == 403
    assert client.put("/memory/mem_x", json={"content": "x", "memory_type": "fact", "importance": 0.5}, headers=member_headers).status_code == 403
    assert client.get("/api/dashboard/stats", headers=member_headers).status_code == 403
    assert client.get("/api/memory-review/candidates", headers=member_headers).status_code == 403
    assert client.get("/agent/activity", headers=member_headers).status_code == 403
    assert client.get("/metrics", headers=member_headers).status_code == 403
    assert client.get("/auth/users", headers=member_headers).status_code == 403

    # Admin: oversight opens up.
    assert client.get("/api/dashboard/stats", headers=bearer(admin["access_token"])).status_code == 200
    assert client.get("/auth/users", headers=bearer(admin["access_token"])).status_code == 200

    # Service lane (API key): unchanged admin-equivalent access for the bot/tools.
    service_headers = {"X-API-Key": SERVICE_KEY}
    assert client.get("/api/dashboard/stats", headers=service_headers).status_code == 200
    assert client.post("/chat", json={"message": "ping"}, headers=service_headers).status_code == 200

    client.delete(f"/conversations/{conversation_id}", headers=member_headers)


def test_conversation_ownership_isolation(client, mock_ollama, auth_on):
    admin = register(client, f"p3-admin-{uuid4().hex[:6]}").json()
    admin_headers = bearer(admin["access_token"])
    users = {}
    for name in ("a", "b"):
        username = f"p3-{name}-{uuid4().hex[:6]}"
        client.post("/auth/users", json={"username": username, "password": "matkhau-123"}, headers=admin_headers)
        users[name] = client.post("/auth/login", json={"username": username, "password": "matkhau-123"}).json()

    a_headers, b_headers = bearer(users["a"]["access_token"]), bearer(users["b"]["access_token"])
    conversation_id = client.post("/chat", json={"message": "của A"}, headers=a_headers).json()["conversation_id"]

    assert any(item["id"] == conversation_id for item in client.get("/conversations", headers=a_headers).json())
    assert all(item["id"] != conversation_id for item in client.get("/conversations", headers=b_headers).json())
    # B must see 404 (not 403): existence itself is private.
    assert client.get(f"/conversations/{conversation_id}", headers=b_headers).status_code == 404
    assert client.post("/chat", json={"message": "chen vào", "conversation_id": conversation_id}, headers=b_headers).status_code == 404
    assert client.delete(f"/conversations/{conversation_id}", headers=b_headers).status_code == 404
    # Admin retains the full view.
    assert client.get(f"/conversations/{conversation_id}", headers=admin_headers).status_code == 200
    # A manages their own freely.
    assert client.delete(f"/conversations/{conversation_id}", headers=a_headers).status_code == 204


def test_login_lockout_after_repeated_failures(client, mock_ollama, auth_on):
    username = f"p3-brute-{uuid4().hex[:6]}"
    register(client, username)
    for _ in range(5):
        assert client.post("/auth/login", json={"username": username, "password": "doan-mo"}).status_code == 401
    locked = client.post("/auth/login", json={"username": username, "password": "doan-mo"})
    assert locked.status_code == 429 and locked.json()["error_code"] == "LOGIN_LOCKED"


def test_the_last_admin_cannot_be_demoted(client, mock_ollama, auth_on):
    admin = register(client, f"p3-admin-{uuid4().hex[:6]}").json()
    admin_headers = bearer(admin["access_token"])
    demoted = client.patch(f"/auth/users/{admin['user']['id']}", json={"role": "member"}, headers=admin_headers)
    assert demoted.status_code == 409 and demoted.json()["error_code"] == "LAST_ADMIN"
