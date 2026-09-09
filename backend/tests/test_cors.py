from uuid import uuid4

from fastapi.testclient import TestClient


def test_unhandled_error_includes_cors_header_for_allowed_origin(mocker):
    from app.auth.security import create_access_token
    from app.config import get_settings
    from app.models.schemas import UserRole
    from app.routers import frames
    import app.main as main

    mocker.patch("app.routers.frames.query", side_effect=RuntimeError("database unavailable"))
    token = create_access_token(get_settings(), uuid4(), "viewer@example.com", UserRole.viewer)

    response = TestClient(main.app, raise_server_exceptions=False).get(
        "/api/frames/scenes",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3000",
        },
    )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
