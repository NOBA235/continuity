"""
Password hashing (bcrypt) and JWT issuance/verification (PyJWT).

No custom crypto here -- both primitives are the industry-standard choice
for their job, used exactly as their own docs recommend. The one thing
worth calling out: access and refresh tokens carry a `type` claim so a
refresh token stolen from wherever the client stores it can't be replayed
as an access token (see decode_token's `expected_type` check).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import bcrypt
import jwt

from app.config import Settings
from app.models.schemas import UserRole


class TokenType(str, Enum):
    access = "access"
    refresh = "refresh"


class TokenError(Exception):
    """Raised for any invalid/expired/wrong-type token. Callers map this to 401."""


def hash_password(plain_password: str) -> str:
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed hash in storage -- treat as "does not match", not a crash.
        return False


def _create_token(
    settings: Settings,
    user_id: uuid.UUID,
    email: str,
    role: UserRole,
    token_type: TokenType,
    expires_delta: timedelta,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": role.value,
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(settings: Settings, user_id: uuid.UUID, email: str, role: UserRole) -> str:
    return _create_token(
        settings, user_id, email, role, TokenType.access,
        timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )


def create_refresh_token(settings: Settings, user_id: uuid.UUID, email: str, role: UserRole) -> str:
    return _create_token(
        settings, user_id, email, role, TokenType.refresh,
        timedelta(days=settings.jwt_refresh_token_expire_days),
    )


def decode_token(settings: Settings, token: str, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a token, raising TokenError on any problem
    (expired, malformed, wrong signature, or the wrong `type` claim --
    e.g. a refresh token presented where an access token belongs)."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid token") from exc

    if payload.get("type") != expected_type.value:
        raise TokenError(f"Expected a {expected_type.value} token")
    return payload
