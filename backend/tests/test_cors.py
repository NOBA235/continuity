from fastapi.testclient import TestClient


def test_authenticated_route_includes_cors_header_on_unauthorized_response():
    """Browser clients need CORS headers even when authentication rejects a request."""
    from app.main import app

    response = TestClient(app).get(
        "/api/frames/scenes",
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code in (401, 403)
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
