"""TEMPORARY (Fable review, 10/11/2026): second try at breaking what R2-2 guards. The first
try replaced the function object, which FastAPI had already captured. This one swaps the code
of the captured function, so the route really trusts the token's role. The test must FAIL.
"""
from __future__ import annotations

import pytest

from test_auth_api import auth_on, factory  # noqa: F401
from test_review2_auth import demoted_admin  # noqa: F401
from test_review2_auth import test_r2_2_a_demoted_admin_with_an_old_token_is_refused_the_user_list  # noqa: F401


@pytest.fixture(autouse=True)
def trust_the_token(monkeypatch):
    import app.security.auth as auth

    def require_admin(request):
        if not auth_enabled(request):  # noqa: F821  (resolved in app.security.auth's globals)
            return
        identity = require_identity(request)  # noqa: F821
        if identity.is_service:
            return
        if identity.role != "admin":
            raise _forbidden()  # noqa: F821

    monkeypatch.setattr(auth.require_admin, "__code__", require_admin.__code__)
