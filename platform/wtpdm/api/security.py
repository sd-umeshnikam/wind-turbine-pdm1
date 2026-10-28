"""Authentication (bcrypt passwords, signed JWT bearer tokens) and role-based access.

Roles are ordered: viewer < engineer < admin. A viewer reads everything operational, an
engineer also works the alert queue, an admin manages users, retraining and promotion.
The user row is re-read on every request, so deactivation or a role change takes effect
immediately rather than when the token expires.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtpdm.api.deps import db
from wtpdm.db.models import AppUser, Role
from wtpdm.settings import get_settings

ALGORITHM = "HS256"
ISSUER = "wtpdm"
MIN_SECRET_LENGTH = 32
ROLE_RANK = {Role.VIEWER: 0, Role.ENGINEER: 1, Role.ADMIN: 2}
# Verified against when the username is unknown, so a miss costs the same time as a hit.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt()).decode()

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


@dataclass(frozen=True)
class Principal:
    username: str
    display_name: str
    role: Role

    def has(self, role: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    return bcrypt.checkpw(password.encode(), (password_hash or _DUMMY_HASH).encode()) and bool(password_hash)


def jwt_secret() -> str:
    secret = get_settings().jwt_secret.get_secret_value()
    if len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(f"WTPDM_JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters")
    return secret


def create_token(username: str, role: Role, ttl: timedelta | None = None) -> tuple[str, int]:
    """Returns (token, lifetime in seconds)."""
    ttl = ttl or timedelta(minutes=get_settings().jwt_ttl_minutes)
    now = datetime.now(UTC)
    payload = {"sub": username, "role": role.value, "iss": ISSUER, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, jwt_secret(), algorithm=ALGORITHM), int(ttl.total_seconds())


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError on a bad signature, wrong issuer or expiry."""
    return jwt.decode(
        token, jwt_secret(), algorithms=[ALGORITHM], issuer=ISSUER, options={"require": ["exp"]}
    )


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def principal_from_token(token: str | None, s: Session) -> Principal:
    if not token:
        raise _unauthorized()
    try:
        claims = decode_token(token)
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid or expired token") from exc
    user = s.scalars(select(AppUser).where(AppUser.username == claims.get("sub"))).first()
    if user is None or not user.is_active:
        raise _unauthorized("User is unknown or deactivated")
    return Principal(user.username, user.display_name, user.role)


def current_user(
    request: Request, token: str | None = Depends(oauth2), s: Session = Depends(db)
) -> Principal:
    principal = principal_from_token(token, s)
    request.state.user = principal.username  # for the access log
    return principal


def require(role: Role) -> Callable[..., Principal]:
    def dependency(user: Principal = Depends(current_user)) -> Principal:
        if not user.has(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires the {role.value} role")
        return user

    return dependency


viewer = require(Role.VIEWER)
engineer = require(Role.ENGINEER)
admin = require(Role.ADMIN)
