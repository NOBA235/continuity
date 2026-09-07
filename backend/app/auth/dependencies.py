"""
FastAPI dependencies that turn a Bearer token into a CurrentUser, and that
gate specific endpoints by role.

Deliberately stateless: role/identity come straight from the signed JWT's
claims, not a per-request ClickHouse lookup. That keeps auth overhead to a
cheap signature check on every request, at the cost of a real, documented
tradeoff -- see README's "Auth" section -- a role change or account
deactivation doesn't take effect until the user's current access token
expires (default 30 minutes).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.security import TokenError, TokenType, decode_token
from app.config import Settings, get_settings
from app.models.schemas import CurrentUser, UserRole

_bearer_scheme = HTTPBearer(auto_error=True, description="Access token from POST /api/auth/login")
_optional_bearer_scheme = HTTPBearer(auto_error=False)


def _resolve_current_user(token: str, settings: Settings) -> CurrentUser:
    try:
        payload = decode_token(settings, token, expected_type=TokenType.access)
    except TokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        return CurrentUser(user_id=UUID(payload["sub"]), email=payload["email"], role=payload["role"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Malformed token payload",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    return _resolve_current_user(credentials.credentials, settings)


def get_current_user_allow_query_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """
    Same as get_current_user, but also accepts `?access_token=...` as a
    fallback when no Authorization header is present.

    Only use this on endpoints a browser element fetches directly without
    custom headers -- e.g. `<video src="...">` -- where attaching a Bearer
    header from JS isn't possible. Everywhere else, get_current_user (header
    only) is the right choice: a token embedded in a URL is more likely to
    end up in server access logs, browser history, or a Referer header.
    """
    token = credentials.credentials if credentials else request.query_params.get("access_token")
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing bearer token (header or ?access_token= query param)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _resolve_current_user(token, settings)


def require_role(*allowed_roles: UserRole):
    """Dependency factory: `Depends(require_role(UserRole.supervisor, UserRole.editor))`
    -- 403s any authenticated user whose role isn't in the allowed set."""

    def _check(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role '{current_user.role.value}' cannot perform this action "
                f"(requires one of: {', '.join(r.value for r in allowed_roles)})",
            )
        return current_user

    return _check


# Shorthand for the common "anyone who isn't a read-only viewer" gate, used
# on upload / resolve / run-agent endpoints.
require_editor_or_supervisor = require_role(UserRole.editor, UserRole.supervisor)
require_supervisor = require_role(UserRole.supervisor)
