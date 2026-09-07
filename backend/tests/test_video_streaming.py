from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.security import create_access_token
from app.config import get_settings
from app.models.schemas import UserRole
from app.routers.ingestion import router as ingestion_router


def _auth_header():
    settings = get_settings()
    token = create_access_token(settings, uuid4(), "viewer@studio-pictures.io", UserRole.viewer)
    return {"Authorization": f"Bearer {token}"}


def _fake_job_row(job_id, storage_key: str, status: str = "completed"):
    now = datetime.now(timezone.utc)
    return {
        "job_id": job_id, "scene_id": "14A", "take_id": "003", "source_filename": "dailies.mp4",
        "storage_key": storage_key, "status": status, "total_frames": 5, "processed_frames": 5,
        "error_message": "", "created_at": now, "updated_at": now,
    }


@pytest.fixture
def client(tmp_path, mocker):
    settings = get_settings()
    mocker.patch.object(settings, "upload_dir", tmp_path)
    mocker.patch("app.routers.ingestion.get_settings", return_value=settings)

    app = FastAPI()
    app.include_router(ingestion_router)
    return TestClient(app)


def _write_fake_video(base_dir: Path, storage_key: str, content: bytes) -> None:
    path = base_dir / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_video_endpoint_requires_authentication(client):
    response = client.get(f"/api/ingestion/jobs/{uuid4()}/video")
    assert response.status_code in (401, 403)


def test_video_endpoint_accepts_query_param_token(client, tmp_path, mocker):
    """<video src="..."> can't set an Authorization header, so this endpoint
    must also accept ?access_token=... -- this is the actual path the
    frontend's VideoPlayer uses (see frontend/lib/api.ts videoStreamUrl)."""
    job_id = uuid4()
    storage_key = f"{job_id}/dailies.mp4"
    payload = b"video-bytes"
    _write_fake_video(tmp_path, storage_key, payload)
    mocker.patch("app.routers.ingestion.query", return_value=[_fake_job_row(job_id, storage_key)])

    settings = get_settings()
    token = create_access_token(settings, uuid4(), "viewer@studio-pictures.io", UserRole.viewer)

    response = client.get(f"/api/ingestion/jobs/{job_id}/video?access_token={token}")

    assert response.status_code == 200
    assert response.content == payload


def test_video_endpoint_rejects_missing_token_in_either_form(client, tmp_path, mocker):
    job_id = uuid4()
    storage_key = f"{job_id}/dailies.mp4"
    _write_fake_video(tmp_path, storage_key, b"x")
    mocker.patch("app.routers.ingestion.query", return_value=[_fake_job_row(job_id, storage_key)])

    response = client.get(f"/api/ingestion/jobs/{job_id}/video")
    assert response.status_code == 401


def test_full_file_when_no_range_header(client, tmp_path, mocker):
    job_id = uuid4()
    storage_key = f"{job_id}/dailies.mp4"
    payload = b"0123456789" * 100
    _write_fake_video(tmp_path, storage_key, payload)
    mocker.patch("app.routers.ingestion.query", return_value=[_fake_job_row(job_id, storage_key)])

    response = client.get(f"/api/ingestion/jobs/{job_id}/video", headers=_auth_header())

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["accept-ranges"] == "bytes"


def test_partial_range_returns_206_with_exact_slice(client, tmp_path, mocker):
    job_id = uuid4()
    storage_key = f"{job_id}/dailies.mp4"
    payload = bytes(range(256)) * 4
    _write_fake_video(tmp_path, storage_key, payload)
    mocker.patch("app.routers.ingestion.query", return_value=[_fake_job_row(job_id, storage_key)])

    response = client.get(
        f"/api/ingestion/jobs/{job_id}/video",
        headers={**_auth_header(), "Range": "bytes=10-19"},
    )

    assert response.status_code == 206
    assert response.content == payload[10:20]
    assert response.headers["content-range"] == f"bytes 10-19/{len(payload)}"
    assert response.headers["content-length"] == "10"


def test_open_ended_range_returns_rest_of_file(client, tmp_path, mocker):
    job_id = uuid4()
    storage_key = f"{job_id}/dailies.mp4"
    payload = b"x" * 500
    _write_fake_video(tmp_path, storage_key, payload)
    mocker.patch("app.routers.ingestion.query", return_value=[_fake_job_row(job_id, storage_key)])

    response = client.get(
        f"/api/ingestion/jobs/{job_id}/video",
        headers={**_auth_header(), "Range": "bytes=490-"},
    )

    assert response.status_code == 206
    assert response.content == payload[490:]
    assert len(response.content) == 10


def test_out_of_bounds_range_is_rejected(client, tmp_path, mocker):
    job_id = uuid4()
    storage_key = f"{job_id}/dailies.mp4"
    payload = b"x" * 100
    _write_fake_video(tmp_path, storage_key, payload)
    mocker.patch("app.routers.ingestion.query", return_value=[_fake_job_row(job_id, storage_key)])

    response = client.get(
        f"/api/ingestion/jobs/{job_id}/video",
        headers={**_auth_header(), "Range": "bytes=90-200"},
    )

    assert response.status_code == 416


def test_missing_job_returns_404(client, mocker):
    mocker.patch("app.routers.ingestion.query", return_value=[])
    response = client.get(f"/api/ingestion/jobs/{uuid4()}/video", headers=_auth_header())
    assert response.status_code == 404


def test_gcs_backend_redirects_to_signed_url(client, mocker):
    job_id = uuid4()
    storage_key = f"{job_id}/dailies.mp4"
    settings = get_settings()
    mocker.patch.object(settings, "storage_backend", "gcs")
    mocker.patch("app.routers.ingestion.get_settings", return_value=settings)
    mocker.patch("app.routers.ingestion.query", return_value=[_fake_job_row(job_id, storage_key)])

    mock_backend = mocker.Mock()
    mock_backend.exists.return_value = True
    mock_backend.get_signed_playback_url.return_value = "https://storage.googleapis.com/signed"
    mocker.patch("app.routers.ingestion.get_storage_backend", return_value=mock_backend)

    response = client.get(
        f"/api/ingestion/jobs/{job_id}/video", headers=_auth_header(), follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://storage.googleapis.com/signed"
