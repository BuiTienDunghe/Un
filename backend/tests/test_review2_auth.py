"""Review2 R2 (an access token keeps the role it was issued with) and R5 (two demotions at
the same moment leave no admin).

Accounts are switched on per test (auth_on); every user is named "p3-..." so auth_on's
teardown removes it, and research projects made here are removed by the fixture.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from review2_support import KnownBug, known_bug
from test_auth_api import auth_on, bearer, factory, register  # noqa: F401  (fixtures and helpers)

PASSWORD = "matkhau-123"


@pytest.fixture
def demoted_admin(client, mock_ollama, auth_on, factory):  # noqa: F811
    """Member A owns a conversation and a research project. B was an admin, logged in as one,
    then was demoted; B still holds the access token issued while it was an admin."""
    from app.postgres.models import ResearchProject
    tag = uuid4().hex[:6]
    root = register(client, f"p3-r2-root-{tag}")
    assert root.status_code == 201, root.text
    root_headers = bearer(root.json()["access_token"])
    users = {}
    for name, role in (("a", "member"), ("b", "admin")):
        username = f"p3-r2-{name}-{tag}"
        created = client.post("/auth/users", json={"username": username, "password": PASSWORD, "role": role},
                              headers=root_headers)
        assert created.status_code == 201, created.text
        login = client.post("/auth/login", json={"username": username, "password": PASSWORD})
        assert login.status_code == 200, login.text
        users[name] = SimpleNamespace(id=created.json()["id"], headers=bearer(login.json()["access_token"]))
    chat = client.post("/chat", json={"message": "Tin riêng của A sentinel-r2-chat."}, headers=users["a"].headers)
    assert chat.status_code == 200, chat.text
    project = client.post("/research/projects", json={"name": "Dự án riêng của A sentinel-r2-project"},
                          headers=users["a"].headers)
    assert project.status_code == 201, project.text
    # While B is an admin it sees A's work; that is the starting point.
    assert chat.json()["conversation_id"] in client.get("/conversations", headers=users["b"].headers).text
    demoted = client.patch(f"/auth/users/{users['b'].id}", json={"role": "member"}, headers=root_headers)
    assert demoted.status_code == 200 and demoted.json()["role"] == "member", demoted.text
    try:
        yield SimpleNamespace(client=client, b=users["b"].headers, conversation=chat.json()["conversation_id"],
                              project=project.json()["id"])
    finally:
        with factory.begin() as session:
            session.execute(delete(ResearchProject).where(ResearchProject.id == project.json()["id"]))


@pytest.mark.parametrize("what", ["conversation_list", "conversation_of_a", "project_list"])
@pytest.mark.xfail(strict=True, raises=KnownBug,
                   reason="review2 R2: the role is read from the access token, so a demoted admin keeps an admin's view for up to 15 minutes")
def test_r2_1_a_demoted_admin_with_an_old_token_no_longer_sees_other_peoples_work(demoted_admin, what):
    client, b = demoted_admin.client, demoted_admin.b
    path, marker = {
        "conversation_list": ("/conversations", demoted_admin.conversation),
        "conversation_of_a": (f"/conversations/{demoted_admin.conversation}", "sentinel-r2-chat"),
        "project_list": ("/research/projects", demoted_admin.project),
    }[what]
    response = client.get(path, headers=b)
    assert response.status_code in (200, 401, 403, 404), response.text
    known_bug(response.status_code != 200 or marker not in response.text,
              f"the demoted admin still sees A's work at {path}")


def test_r2_2_a_demoted_admin_with_an_old_token_is_refused_the_user_list(demoted_admin):
    assert demoted_admin.client.get("/auth/users", headers=demoted_admin.b).status_code == 403


def admins(factory) -> int:  # noqa: F811
    from app.postgres.models import User
    with factory() as session:
        return session.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0


@pytest.mark.xfail(strict=True, raises=KnownBug,
                   reason="review2 R5: set_role counts the admins and updates without a lock, so two demotions at once leave none")
def test_r5_1_two_admins_demoting_each_other_at_once_leave_one_admin(client, auth_on, factory, monkeypatch):  # noqa: F811
    import app.services.auth_service as auth_module
    service = client.app.state.auth_service
    tag = uuid4().hex[:6]
    first = service.create_user(f"p3-r5-x-{tag}", PASSWORD, role="admin")
    second = service.create_user(f"p3-r5-y-{tag}", PASSWORD, role="admin")
    assert admins(factory) == 2, "the whole users table must hold exactly these two admins"

    # Both demotions are past their admin count before either commits: each waits at the
    # last step before commit for the other, at most 2 s (a locking fix makes one wait out).
    original, gate = auth_module._public, threading.Barrier(2, timeout=2)

    def gated(user):
        try:
            gate.wait()
        except threading.BrokenBarrierError:
            pass
        return original(user)

    monkeypatch.setattr(auth_module, "_public", gated)
    outcomes: dict[str, object] = {}

    def demote(actor: str, target: str) -> None:
        try:
            service.set_role(target, "member")
            outcomes[actor] = "demoted"
        except Exception as error:  # noqa: BLE001  (recorded here, judged after join)
            outcomes[actor] = error

    threads = [threading.Thread(target=demote, args=("x", second["id"])),
               threading.Thread(target=demote, args=("y", first["id"]))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    assert not any(thread.is_alive() for thread in threads) and len(outcomes) == 2, outcomes
    # The only refusal is the service's own "last admin" one; any other error in either
    # thread is a real failure, never the known bug and never a pass.
    assert all(outcome == "demoted" or isinstance(outcome, auth_module.AuthConflictError)
               for outcome in outcomes.values()), outcomes
    succeeded = [actor for actor, outcome in outcomes.items() if outcome == "demoted"]
    assert succeeded, f"both demotions were refused, which is neither the bug nor a fix: {outcomes}"
    known_bug(len(succeeded) == 1 and admins(factory) >= 1,
              f"both demotions went through and {admins(factory)} admin(s) remain: {outcomes}")
