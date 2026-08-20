"""Accounts (P3-1): bootstrap, login, refresh, and admin user management.

Design notes, distilled from the adversarial review of the auth design:
- Registration ONLY bootstraps the very first admin (guarded by a PostgreSQL
  advisory lock so a LAN race cannot mint two admins). Afterwards accounts are
  created by an admin — open registration on a LAN is a land-grab.
- Refresh tokens are long-lived, hashed at rest and revocable, but NOT rotated
  on use: rotation with reuse-detection turns an ordinary multi-tab refresh
  race into a mass logout. Logout revokes; login issues fresh.
- Login flattens timing with a dummy bcrypt check for unknown usernames and
  locks a username out after repeated failures (in-memory — one backend
  process serves this box).
- The last remaining admin can never be demoted (no-recovery lockout guard).
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import UUID

import bcrypt
import jwt as pyjwt
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from app.postgres.models import RefreshToken, User

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")
BOOTSTRAP_LOCK_KEY = 745_301_991
MAX_LOGIN_FAILURES = 5
LOGIN_LOCK_SECONDS = 60.0


class AuthError(Exception):
    pass


class InvalidCredentialsError(AuthError):
    pass


class AuthConflictError(AuthError):
    pass


class LoginLockedError(AuthError):
    pass


def _hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public(user: User) -> dict[str, object]:
    return {
        "id": str(user.id),
        "username": user.username,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


class AuthService:
    def __init__(
        self,
        sessions: sessionmaker,
        *,
        jwt_secret: str,
        access_minutes: int = 15,
        refresh_days: int = 14,
    ) -> None:
        self.sessions = sessions
        self.jwt_secret = jwt_secret
        self.access_minutes = max(1, access_minutes)
        self.refresh_days = max(1, refresh_days)
        self._login_failures: dict[str, tuple[int, float]] = {}
        # Same-cost comparison target for usernames that do not exist.
        self._dummy_hash = bcrypt.hashpw(b"invalid-password-placeholder", bcrypt.gensalt())

    # ── Registration & user management ─────────────────────────────────

    def has_users(self) -> bool:
        with self.sessions() as database:
            return bool(database.scalar(select(func.count()).select_from(User)))

    @staticmethod
    def _validate(username: str, password: str) -> str:
        normalized = username.strip().lower()
        if not USERNAME_PATTERN.fullmatch(normalized):
            raise ValueError("Tên đăng nhập: 3-64 ký tự a-z, 0-9, '._-', bắt đầu bằng chữ hoặc số.")
        if len(password) < 8:
            raise ValueError("Mật khẩu phải có ít nhất 8 ký tự.")
        return normalized

    def register_first_admin(self, username: str, password: str) -> dict[str, object]:
        normalized = self._validate(username, password)
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
        with self.sessions.begin() as database:
            # The advisory lock serializes concurrent bootstrap attempts: only
            # one of two racing "first" registrations sees count == 0.
            database.execute(select(func.pg_advisory_xact_lock(BOOTSTRAP_LOCK_KEY)))
            if database.scalar(select(func.count()).select_from(User)):
                raise AuthConflictError("Đăng ký đã đóng: hệ thống đã có tài khoản. Nhờ quản trị viên tạo giúp.")
            user = User(username=normalized, password_hash=password_hash, role="admin")
            database.add(user)
            database.flush()
            payload = self._issue(database, user)
        return payload

    def create_user(self, username: str, password: str, role: str = "member") -> dict[str, object]:
        normalized = self._validate(username, password)
        if role not in ("admin", "member"):
            raise ValueError("Vai trò phải là admin hoặc member.")
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
        with self.sessions.begin() as database:
            if database.scalar(select(func.count()).select_from(User).where(User.username == normalized)):
                raise AuthConflictError("Tên đăng nhập đã tồn tại.")
            user = User(username=normalized, password_hash=password_hash, role=role)
            database.add(user)
            database.flush()
            return _public(user)

    def list_users(self) -> list[dict[str, object]]:
        with self.sessions() as database:
            return [_public(user) for user in database.scalars(select(User).order_by(User.created_at))]

    def set_role(self, user_id: str, role: str) -> dict[str, object]:
        if role not in ("admin", "member"):
            raise ValueError("Vai trò phải là admin hoặc member.")
        with self.sessions.begin() as database:
            user = database.get(User, UUID(user_id))
            if user is None:
                raise InvalidCredentialsError("user not found")
            if user.role == "admin" and role == "member":
                admins = database.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0
                if admins <= 1:
                    raise AuthConflictError("Không thể giáng cấp quản trị viên cuối cùng.")
            user.role = role
            return _public(user)

    # ── Login / tokens ─────────────────────────────────────────────────

    def login(self, username: str, password: str) -> dict[str, object]:
        key = username.strip().lower()
        failures, locked_until = self._login_failures.get(key, (0, 0.0))
        if failures >= MAX_LOGIN_FAILURES and monotonic() < locked_until:
            raise LoginLockedError("Đăng nhập sai nhiều lần — thử lại sau một phút.")
        with self.sessions() as database:
            user = database.scalar(select(User).where(User.username == key))
        stored_hash = user.password_hash.encode("ascii") if user is not None else self._dummy_hash
        valid = bcrypt.checkpw(password.encode("utf-8"), stored_hash) and user is not None
        if not valid:
            self._login_failures[key] = (failures + 1, monotonic() + LOGIN_LOCK_SECONDS)
            raise InvalidCredentialsError("Tên đăng nhập hoặc mật khẩu không đúng.")
        self._login_failures.pop(key, None)
        with self.sessions.begin() as database:
            stored = database.get(User, user.id)
            stored.last_login_at = datetime.now(UTC)
            # Housekeeping: dead tokens never pile up (adversarial finding).
            database.execute(
                delete(RefreshToken).where(
                    RefreshToken.user_id == user.id,
                    (RefreshToken.expires_at < datetime.now(UTC)) | RefreshToken.revoked_at.is_not(None),
                )
            )
            return self._issue(database, stored)

    def refresh(self, refresh_token: str) -> dict[str, object]:
        token_hash = _hash_refresh(refresh_token)
        with self.sessions() as database:
            row = database.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
            if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
                raise InvalidCredentialsError("Phiên đăng nhập đã hết hạn — hãy đăng nhập lại.")
            user = database.get(User, row.user_id)
            if user is None:
                raise InvalidCredentialsError("Phiên đăng nhập đã hết hạn — hãy đăng nhập lại.")
            return {
                "access_token": self._access_token(user),
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "user": _public(user),
            }

    def logout(self, refresh_token: str) -> None:
        token_hash = _hash_refresh(refresh_token)
        with self.sessions.begin() as database:
            row = database.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
            if row is not None and row.revoked_at is None:
                row.revoked_at = datetime.now(UTC)

    def get_user(self, user_id: str) -> dict[str, object] | None:
        try:
            parsed = UUID(user_id)
        except ValueError:
            return None
        with self.sessions() as database:
            user = database.get(User, parsed)
            return _public(user) if user is not None else None

    def _access_token(self, user: User) -> str:
        now = datetime.now(UTC)
        return pyjwt.encode(
            {
                "sub": str(user.id),
                "username": user.username,
                "role": user.role,
                "type": "access",
                "iat": now,
                "exp": now + timedelta(minutes=self.access_minutes),
            },
            self.jwt_secret,
            algorithm="HS256",
        )

    def _issue(self, database, user: User) -> dict[str, object]:
        refresh_token = secrets.token_urlsafe(48)
        database.add(
            RefreshToken(
                user_id=user.id,
                token_hash=_hash_refresh(refresh_token),
                expires_at=datetime.now(UTC) + timedelta(days=self.refresh_days),
            )
        )
        return {
            "access_token": self._access_token(user),
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": _public(user),
        }
