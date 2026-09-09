from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.dependencies import get_current_user
from app.auth.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.config import Settings, get_settings
from app.models.schemas import (
    CurrentUser,
    LoginRequest,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserPublic,
    UserRole,
)
from app.services import user_store

router = APIRouter(prefix="/api/auth", tags=["auth"])

_optional_bearer = HTTPBearer(auto_error=False)


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def register(
    body: UserCreate,
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    settings: Settings = Depends(get_settings),
) -> UserPublic:
    """
    Create an account.

    Anyone may create a regular viewer account. The very first account on a
    fresh deployment is promoted to supervisor so the application always has
    an administrator. A signed-in supervisor can create accounts with any
    role; the role in an unauthenticated request is deliberately ignored so a
    public signup cannot grant itself elevated access.
    """
    is_bootstrap = user_store.count_users() == 0

    if is_bootstrap:
        role = UserRole.supervisor
    elif credentials is None:
        role = UserRole.viewer
    else:
        try:
            payload = decode_token(settings, credentials.credentials, expected_type=TokenType.access)
        except TokenError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
        if payload.get("role") != UserRole.supervisor.value:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only supervisors can create accounts")
        role = body.role

    if user_store.get_user_by_email(body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    return user_store.create_user(
        email=body.email,
        hashed_password=hash_password(body.password),
        display_name=body.display_name,
        role=role,
    )


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, settings: Settings = Depends(get_settings)) -> TokenPair:
    user_row = user_store.get_user_by_email(body.email)
    # Constant-shape failure: don't reveal whether the email exists at all.
    invalid_credentials = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user_row or not verify_password(body.password, user_row["hashed_password"]):
        raise invalid_credentials

    role = UserRole(user_row["role"])
    user_id = user_row["user_id"]
    user_store.record_login(user_row)

    return TokenPair(
        access_token=create_access_token(settings, user_id, user_row["email"], role),
        refresh_token=create_refresh_token(settings, user_id, user_row["email"], role),
        expires_in_seconds=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, settings: Settings = Depends(get_settings)) -> TokenPair:
    try:
        payload = decode_token(settings, body.refresh_token, expected_type=TokenType.refresh)
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    user_row = user_store.get_user_by_id(UUID(payload["sub"]))
    if not user_row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists")

    role = UserRole(user_row["role"])
    user_id = user_row["user_id"]
    # Rotate both tokens on refresh -- the old refresh token is now unusable
    # simply because a *new* one was issued (there's no revocation list; see
    # README's Auth section for that documented limitation).
    return TokenPair(
        access_token=create_access_token(settings, user_id, user_row["email"], role),
        refresh_token=create_refresh_token(settings, user_id, user_row["email"], role),
        expires_in_seconds=settings.jwt_access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserPublic)
def get_me(current_user: CurrentUser = Depends(get_current_user)) -> UserPublic:
    user_row = user_store.get_user_by_id(current_user.user_id)
    if not user_row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists")
    return UserPublic.model_validate(user_row)
