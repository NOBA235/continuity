from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.security import hash_password
from app.routers.auth import router as auth_router


@pytest.fixture
def app():
    fastapi_app = FastAPI()
    fastapi_app.include_router(auth_router)
    return fastapi_app


@pytest.fixture
def client(app):
    return TestClient(app)


def _fake_user_row(email="super@studio-pictures.io", role="supervisor", password="correct-password"):
    return {
        "user_id": uuid4(),
        "email": email,
        "hashed_password": hash_password(password),
        "display_name": "Test User",
        "role": role,
        "is_active": 1,
        "created_at": datetime.now(timezone.utc),
        "last_login_at": None,
    }


def test_register_bootstraps_first_account_as_supervisor_without_auth(client, mocker):
    from app.models.schemas import UserPublic, UserRole

    mocker.patch("app.routers.auth.user_store.count_users", return_value=0)
    mocker.patch("app.routers.auth.user_store.get_user_by_email", return_value=None)
    fake_created_user = UserPublic(
        user_id=uuid4(), email="first@studio-pictures.io", display_name="",
        role=UserRole.supervisor, created_at=datetime.now(timezone.utc),
    )
    created = mocker.patch("app.routers.auth.user_store.create_user", return_value=fake_created_user)

    response = client.post(
        "/api/auth/register",
        json={"email": "first@studio-pictures.io", "password": "a-real-password", "role": "viewer"},
    )

    assert response.status_code == 201
    # Even though the request asked for "viewer", bootstrap always grants supervisor.
    _, kwargs = created.call_args
    assert kwargs["role"].value == "supervisor"


def test_register_after_bootstrap_creates_viewer_without_auth(client, mocker):
    from app.models.schemas import UserPublic, UserRole

    mocker.patch("app.routers.auth.user_store.count_users", return_value=1)
    mocker.patch("app.routers.auth.user_store.get_user_by_email", return_value=None)
    created = mocker.patch(
        "app.routers.auth.user_store.create_user",
        return_value=UserPublic(
            user_id=uuid4(),
            email="second@studio-pictures.io",
            display_name="",
            role=UserRole.viewer,
            created_at=datetime.now(timezone.utc),
        ),
    )

    response = client.post(
        "/api/auth/register",
        json={"email": "second@studio-pictures.io", "password": "a-real-password", "role": "supervisor"},
    )

    assert response.status_code == 201
    _, kwargs = created.call_args
    assert kwargs["role"].value == "viewer"


def test_register_rejects_non_supervisor_token(client, mocker):
    mocker.patch("app.routers.auth.user_store.count_users", return_value=1)
    from app.auth.security import create_access_token
    from app.config import get_settings
    from app.models.schemas import UserRole

    settings = get_settings()
    editor_token = create_access_token(settings, uuid4(), "editor@studio-pictures.io", UserRole.editor)

    response = client.post(
        "/api/auth/register",
        json={"email": "second@studio-pictures.io", "password": "a-real-password"},
        headers={"Authorization": f"Bearer {editor_token}"},
    )

    assert response.status_code == 403


def test_register_rejects_duplicate_email(client, mocker):
    mocker.patch("app.routers.auth.user_store.count_users", return_value=1)
    from app.auth.security import create_access_token
    from app.config import get_settings
    from app.models.schemas import UserRole

    settings = get_settings()
    supervisor_token = create_access_token(settings, uuid4(), "boss@studio-pictures.io", UserRole.supervisor)
    mocker.patch("app.routers.auth.user_store.get_user_by_email", return_value=_fake_user_row())

    response = client.post(
        "/api/auth/register",
        json={"email": "boss@studio-pictures.io", "password": "a-real-password"},
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )

    assert response.status_code == 409


def test_login_succeeds_with_correct_password(client, mocker):
    user_row = _fake_user_row(password="correct-password")
    mocker.patch("app.routers.auth.user_store.get_user_by_email", return_value=user_row)
    mocker.patch("app.routers.auth.user_store.record_login")

    response = client.post(
        "/api/auth/login", json={"email": user_row["email"], "password": "correct-password"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body and "refresh_token" in body
    assert body["token_type"] == "bearer"


def test_login_fails_with_wrong_password(client, mocker):
    user_row = _fake_user_row(password="correct-password")
    mocker.patch("app.routers.auth.user_store.get_user_by_email", return_value=user_row)

    response = client.post(
        "/api/auth/login", json={"email": user_row["email"], "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_login_fails_for_unknown_email_with_same_error_as_wrong_password(client, mocker):
    mocker.patch("app.routers.auth.user_store.get_user_by_email", return_value=None)

    response = client.post(
        "/api/auth/login", json={"email": "nobody@studio-pictures.io", "password": "whatever"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_refresh_issues_new_token_pair(client, mocker):
    from app.auth.security import create_refresh_token
    from app.config import get_settings
    from app.models.schemas import UserRole

    settings = get_settings()
    user_row = _fake_user_row(role="editor")
    refresh_token = create_refresh_token(settings, user_row["user_id"], user_row["email"], UserRole.editor)
    mocker.patch("app.routers.auth.user_store.get_user_by_id", return_value=user_row)

    response = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 200
    assert "access_token" in response.json()


def test_refresh_rejects_an_access_token(client):
    from app.auth.security import create_access_token
    from app.config import get_settings
    from app.models.schemas import UserRole

    settings = get_settings()
    access_token = create_access_token(settings, uuid4(), "e@example-corp.io", UserRole.viewer)

    response = client.post("/api/auth/refresh", json={"refresh_token": access_token})
    assert response.status_code == 401


def test_me_requires_authentication(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 403 or response.status_code == 401  # HTTPBearer default is 403


def test_me_returns_current_user_with_valid_token(client, mocker):
    from app.auth.security import create_access_token
    from app.config import get_settings
    from app.models.schemas import UserRole

    settings = get_settings()
    user_row = _fake_user_row()
    token = create_access_token(settings, user_row["user_id"], user_row["email"], UserRole.supervisor)
    mocker.patch("app.routers.auth.user_store.get_user_by_id", return_value=user_row)

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == user_row["email"]
