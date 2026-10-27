"""Layer-1 access control: a shared API key on every state-changing endpoint.

Scope is deliberately narrow. This stops anyone who can reach port 8000 from
deleting documents or filling the database; it is not multi-user auth. Layer 2
(per-user JWT) reuses the `Authorization: Bearer` header the Discord bot client
already speaks, which is why this layer stays on a header of its own.

Reads are public by default because the whole point of the product is a local
workspace you just open. `LOCAL_AI_PROTECT_READS=true` closes them too for an
installation shared over a LAN.
"""
from __future__ import annotations

import os
from hmac import compare_digest

from fastapi import Header, HTTPException, Request, status

from app.security.auth import auth_enabled, require_identity


def _configured_key(request: Request) -> str:
    settings = getattr(request.app.state, "settings", None)
    return (getattr(settings, "local_ai_api_key", "") or "").strip()


def _reject(error_code: str, message: str) -> HTTPException:
    # Matches the envelope every other endpoint raises, so the web UI's error
    # handling and the bot's `_error_code` parsing both keep working.
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error_code": error_code, "message": message})


def _check(request: Request, provided: str | None) -> None:
    expected = _configured_key(request)
    if not expected:
        # No key configured means this installation opted out. Failing closed
        # here would break the one-click path: the launcher opens the UI in a
        # browser that has no way to read a secret out of .env.
        return
    if not provided:
        raise _reject("API_KEY_REQUIRED", "This endpoint requires the X-API-Key header.")
    # Constant-time so a wrong key cannot be discovered one character at a time.
    if not compare_digest(provided.strip(), expected):
        raise _reject("API_KEY_INVALID", "The provided X-API-Key is not valid.")


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Guard every endpoint that changes state.

    With accounts enabled (P3-1) this fails CLOSED: a valid API key (service
    lane) or a valid Bearer login is required — the legacy no-key fail-open
    path must never apply while the operator believes the box is protected.
    """
    if auth_enabled(request):
        require_identity(request)
        return
    _check(request, x_api_key)


def require_api_key_for_read(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Guard read endpoints. With accounts enabled every read needs an
    identity; otherwise only when the installation opts in via
    LOCAL_AI_PROTECT_READS."""
    if auth_enabled(request):
        require_identity(request)
        return
    settings = getattr(request.app.state, "settings", None)
    if not getattr(settings, "local_ai_protect_reads", False):
        return
    _check(request, x_api_key)


def api_key_headers() -> dict[str, str]:
    """The X-API-Key header the server will actually enforce, if any.

    Reading only os.environ was a silent outage. On 27/08 the operator put
    LOCAL_AI_API_KEY in .env; the server (pydantic-settings, which loads .env)
    began enforcing it, while this harness kept looking at a variable that no
    Scheduled Task exports. Every nightly run from 27/08 to 04/09 died 401 on
    the first upload — a red gate that said nothing at all about retrieval.

    Falling back to Settings reads the same file the server reads, so the two
    cannot drift apart again. An explicit env var still wins, which is what CI
    and one-off runs against another host rely on.
    """
    key = os.environ.get("LOCAL_AI_API_KEY", "").strip()
    if not key:
        try:
            from app.config.settings import get_settings

            key = (get_settings().local_ai_api_key or "").strip()
        except Exception:
            # A run pointed at a remote base URL need not have a local .env or
            # a reachable database. Send no header rather than refuse to start.
            key = ""
    return {"X-API-Key": key} if key else {}
