"""Accounts API (P3-1): bootstrap, login, refresh, admin user management.

Login/refresh/register/config are public by necessity; the /users management
endpoints demand an admin. Everything answers 409 AUTH_DISABLED when accounts
are off, so a probing client can tell "feature off" from "bad credentials".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.schemas.auth_schema import (
    CredentialsRequest,
    CreateUserRequest,
    RefreshRequest,
    RoleUpdateRequest,
)
from app.security.auth import auth_enabled, require_admin, resolve_identity
from app.services.auth_service import (
    AuthConflictError,
    AuthService,
    InvalidCredentialsError,
    LoginLockedError,
)

router = APIRouter(prefix="/auth", tags=["auth"])
# The Discord bot's api_client has always fallen back to POST /api/login for a
# JWT — serve that path as an alias so the built-in lane works out of the box.
alias_router = APIRouter(tags=["auth"])


def _service(request: Request) -> AuthService:
    return request.app.state.auth_service


def _require_enabled(request: Request) -> None:
    if not auth_enabled(request):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error_code": "AUTH_DISABLED", "message": "Chế độ tài khoản đang tắt (LOCAL_AI_AUTH_ENABLED=false)."})


@router.get("/config")
def auth_config(request: Request) -> dict[str, object]:
    enabled = auth_enabled(request)
    # has_users=True when disabled so no client ever shows a register form.
    return {"enabled": enabled, "has_users": _service(request).has_users() if enabled else True}


@router.post("/register", status_code=201)
def register(payload: CredentialsRequest, request: Request) -> dict[str, object]:
    _require_enabled(request)
    try:
        return _service(request).register_first_admin(payload.username, payload.password)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"error_code": "INVALID_INPUT", "message": str(error)}) from error
    except AuthConflictError as error:
        raise HTTPException(status_code=409, detail={"error_code": "REGISTRATION_CLOSED", "message": str(error)}) from error


def _login(payload: CredentialsRequest, request: Request) -> dict[str, object]:
    _require_enabled(request)
    try:
        return _service(request).login(payload.username, payload.password)
    except LoginLockedError as error:
        raise HTTPException(status_code=429, detail={"error_code": "LOGIN_LOCKED", "message": str(error)}) from error
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=401, detail={"error_code": "LOGIN_INVALID", "message": str(error)}) from error


@router.post("/login")
def login(payload: CredentialsRequest, request: Request) -> dict[str, object]:
    return _login(payload, request)


@alias_router.post("/api/login")
def login_alias(payload: CredentialsRequest, request: Request) -> dict[str, object]:
    return _login(payload, request)


@router.post("/refresh")
def refresh(payload: RefreshRequest, request: Request) -> dict[str, object]:
    _require_enabled(request)
    try:
        return _service(request).refresh(payload.refresh_token)
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=401, detail={"error_code": "REFRESH_INVALID", "message": str(error)}) from error


@router.post("/logout", status_code=204)
def logout(payload: RefreshRequest, request: Request) -> None:
    _require_enabled(request)
    _service(request).logout(payload.refresh_token)


@router.get("/me")
def me(request: Request) -> dict[str, object]:
    _require_enabled(request)
    identity = resolve_identity(request)
    if not identity.is_user or not identity.user_id:
        raise HTTPException(status_code=401, detail={"error_code": "AUTH_REQUIRED", "message": "Cần đăng nhập."})
    user = _service(request).get_user(identity.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail={"error_code": "TOKEN_INVALID", "message": "Tài khoản không còn tồn tại."})
    return user


@router.get("/users", dependencies=[Depends(require_admin)])
def list_users(request: Request) -> list[dict[str, object]]:
    _require_enabled(request)
    return _service(request).list_users()


@router.post("/users", status_code=201, dependencies=[Depends(require_admin)])
def create_user(payload: CreateUserRequest, request: Request) -> dict[str, object]:
    _require_enabled(request)
    try:
        return _service(request).create_user(payload.username, payload.password, payload.role)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"error_code": "INVALID_INPUT", "message": str(error)}) from error
    except AuthConflictError as error:
        raise HTTPException(status_code=409, detail={"error_code": "USERNAME_TAKEN", "message": str(error)}) from error


@router.patch("/users/{user_id}", dependencies=[Depends(require_admin)])
def set_role(user_id: str, payload: RoleUpdateRequest, request: Request) -> dict[str, object]:
    _require_enabled(request)
    try:
        return _service(request).set_role(user_id, payload.role)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"error_code": "INVALID_INPUT", "message": str(error)}) from error
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=404, detail={"error_code": "USER_NOT_FOUND", "message": "Không tìm thấy tài khoản."}) from error
    except AuthConflictError as error:
        raise HTTPException(status_code=409, detail={"error_code": "LAST_ADMIN", "message": str(error)}) from error
