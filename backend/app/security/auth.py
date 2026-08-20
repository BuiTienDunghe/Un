"""Layer-2 identity (P3-1): JWT user accounts on top of the API-key service lane.

Three identity kinds resolve per request, in priority order:

- ``service``: a valid ``X-API-Key``. This is how the Discord bot, the eval
  harness and the smoke test keep working untouched — the settings validator
  guarantees the key EXISTS whenever auth is enabled, so the service lane can
  never silently die (or, worse, fail open).
- ``user``: a valid ``Authorization: Bearer`` access token (HS256, 15 min).
- ``anonymous``: everything else. With auth disabled this is the normal state
  and nothing here rejects it; with auth enabled the guards fail CLOSED.

A stale Bearer token while auth is DISABLED is deliberately ignored rather
than rejected: toggling accounts off must instantly return the install to
zero-setup behavior for clients still holding old tokens.
"""
from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
from uuid import UUID

import jwt as pyjwt
from fastapi import HTTPException, Request, status

from app.postgres.models import User


@dataclass(frozen=True)
class Identity:
    kind: str  # "anonymous" | "service" | "user"
    user_id: str | None = None
    username: str | None = None
    role: str | None = None

    @property
    def is_service(self) -> bool:
        return self.kind == "service"

    @property
    def is_user(self) -> bool:
        return self.kind == "user"


ANONYMOUS = Identity("anonymous")
SERVICE = Identity("service", role="admin")


def _settings(request: Request):
    return getattr(request.app.state, "settings", None)


def auth_enabled(request: Request) -> bool:
    return bool(getattr(_settings(request), "local_ai_auth_enabled", False))


def _unauthorized(error_code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error_code": error_code, "message": message})


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error_code": "FORBIDDEN", "message": "Chỉ quản trị viên mới dùng được chức năng này."},
    )


def resolve_identity(request: Request) -> Identity:
    """Resolve and cache the caller's identity for this request."""
    cached = getattr(request.state, "identity", None)
    if cached is not None:
        return cached
    identity = _resolve(request)
    request.state.identity = identity
    return identity


def _resolve(request: Request) -> Identity:
    settings = _settings(request)
    expected_key = (getattr(settings, "local_ai_api_key", "") or "").strip()
    provided_key = request.headers.get("x-api-key")
    if expected_key and provided_key and compare_digest(provided_key.strip(), expected_key):
        return SERVICE
    if not auth_enabled(request):
        return ANONYMOUS
    authorization = request.headers.get("authorization") or ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        secret = getattr(settings, "local_ai_jwt_secret", "") or ""
        try:
            claims = pyjwt.decode(token, secret, algorithms=["HS256"])
        except pyjwt.PyJWTError as error:
            raise _unauthorized("TOKEN_INVALID", "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.") from error
        if claims.get("type") != "access" or not claims.get("sub"):
            raise _unauthorized("TOKEN_INVALID", "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
        return Identity(
            "user",
            user_id=str(claims["sub"]),
            username=str(claims.get("username") or ""),
            role=str(claims.get("role") or "member"),
        )
    return ANONYMOUS


def require_identity(request: Request) -> Identity:
    """Fail-closed gate used by every guard once auth is enabled."""
    identity = resolve_identity(request)
    if identity.kind == "anonymous":
        raise _unauthorized("AUTH_REQUIRED", "Cần đăng nhập hoặc X-API-Key hợp lệ.")
    return identity


def require_admin(request: Request) -> None:
    """Admin surface. No-op with auth disabled (single-user mode keeps its
    existing API-key-only protections). Service identity passes. For user
    identity the role is re-read from the DATABASE, so a demotion takes effect
    immediately instead of at access-token expiry."""
    if not auth_enabled(request):
        return
    identity = require_identity(request)
    if identity.is_service:
        return
    sessions = getattr(request.app.state, "postgres_sessions", None)
    stored_role = None
    if sessions is not None and identity.user_id:
        try:
            with sessions() as database:
                user = database.get(User, UUID(identity.user_id))
            stored_role = user.role if user is not None else None
        except ValueError:
            stored_role = None
    if stored_role != "admin":
        raise _forbidden()


def ensure_conversation_access(request: Request, conversation_id: str) -> None:
    """Ownership gate for one conversation (single choke point, used by the
    conversations router AND the chat/RAG paths that accept a conversation_id).

    Members only reach their own rows; unknown ids fall through so the
    endpoint's ordinary 404 fires; other users' rows also 404 — a member must
    not be able to distinguish "not mine" from "does not exist". Legacy rows
    with no owner are admin-only.
    """
    if not auth_enabled(request):
        return
    identity = resolve_identity(request)
    if not identity.is_user or identity.role == "admin":
        return
    store = request.app.state.auxiliary_store
    if not store.conversation_exists(conversation_id):
        return
    if store.conversation_owner(conversation_id) != identity.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "CONVERSATION_NOT_FOUND", "message": f"Conversation {conversation_id} does not exist"},
        )
