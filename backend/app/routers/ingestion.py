from __future__ import annotations

import logging
import mimetypes
import re
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse

from app.auth.dependencies import get_current_user, get_current_user_allow_query_token, require_editor_or_supervisor
from app.config import get_settings
from app.db.clickhouse_client import query
from app.models.schemas import CurrentUser, IngestionJob
from app.services.ingestion_pipeline import ingest_video
from app.services.object_storage import get_storage_backend

logger = logging.getLogger("continuity_agent.routers.ingestion")
router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])

_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-\.]+$")


def _validate_id(value: str, field_name: str) -> str:
    if not _SAFE_ID.match(value):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{field_name} must contain only letters, numbers, '-', '_', '.'",
        )
    return value


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_dailies(
    background_tasks: BackgroundTasks,
    scene_id: str = Form(...),
    take_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_editor_or_supervisor),
) -> dict:
    """
    Accept a dailies video file, persist it, and kick off the full ingestion
    pipeline (keyframe extraction -> Gemini analysis -> ClickHouse) as a
    background task. Returns immediately with a job_id the client can poll.

    Restricted to editor/supervisor accounts -- viewers can review dailies
    but not add them.
    """
    _validate_id(scene_id, "scene_id")
    _validate_id(take_id, "take_id")

    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    job_id = uuid4()
    filename = file.filename or "upload.mp4"
    storage_key = f"{job_id}/{filename}"

    # Always stage locally first -- ffmpeg needs a real seekable file on disk
    # regardless of which storage backend is configured (see
    # ingestion_pipeline.ingest_video's docstring for why).
    staging_path = settings.upload_dir / storage_key
    staging_path.parent.mkdir(parents=True, exist_ok=True)

    size_written = 0
    with staging_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size_written += len(chunk)
            if size_written > max_bytes:
                staging_path.unlink(missing_ok=True)
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"File exceeds max upload size of {settings.max_upload_size_mb} MB",
                )
            out.write(chunk)

    logger.info(
        "Accepted upload %s (%d bytes) for %s/%s -> job %s (by %s)",
        filename, size_written, scene_id, take_id, job_id, current_user.email,
    )

    # Persist to the canonical backend *before* kicking off processing, so
    # the upload survives even if ingestion itself fails partway through.
    # For the local backend this is a no-op (staging_path already IS the
    # canonical path); for GCS it uploads the blob now.
    storage = get_storage_backend()
    storage.save_upload(storage_key, staging_path)

    background_tasks.add_task(
        _run_ingestion_safely, staging_path, scene_id, take_id, job_id, storage_key,
    )
    return {"job_id": str(job_id), "scene_id": scene_id, "take_id": take_id}


def _run_ingestion_safely(
    video_path: Path, scene_id: str, take_id: str, job_id: UUID, storage_key: str,
) -> None:
    try:
        ingest_video(video_path, scene_id, take_id, job_id=job_id, storage_key=storage_key)
    except Exception:  # noqa: BLE001 -- ingest_video already records failure state in ClickHouse
        logger.exception("Background ingestion job %s failed", job_id)


@router.get("/jobs/{job_id}", response_model=IngestionJob)
def get_job_status(job_id: UUID, _current_user: CurrentUser = Depends(get_current_user)) -> IngestionJob:
    rows = query(
        "SELECT * FROM ingestion_jobs WHERE job_id = {job_id:UUID} ORDER BY updated_at DESC LIMIT 1",
        {"job_id": str(job_id)},
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No ingestion job found with id {job_id}")
    return IngestionJob.model_validate(rows[0])


@router.get("/jobs", response_model=list[IngestionJob])
def list_jobs(
    scene_id: str | None = None, limit: int = 25,
    _current_user: CurrentUser = Depends(get_current_user),
) -> list[IngestionJob]:
    if scene_id:
        rows = query(
            "SELECT * FROM ingestion_jobs WHERE scene_id = {scene_id:String} "
            "ORDER BY updated_at DESC LIMIT {limit:UInt32}",
            {"scene_id": scene_id, "limit": limit},
        )
    else:
        rows = query(
            "SELECT * FROM ingestion_jobs ORDER BY updated_at DESC LIMIT {limit:UInt32}",
            {"limit": limit},
        )
    return [IngestionJob.model_validate(r) for r in rows]


def _get_job_or_404(job_id: UUID) -> IngestionJob:
    rows = query(
        "SELECT * FROM ingestion_jobs WHERE job_id = {job_id:UUID} ORDER BY updated_at DESC LIMIT 1",
        {"job_id": str(job_id)},
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No ingestion job found with id {job_id}")
    return IngestionJob.model_validate(rows[0])


_CHUNK_SIZE = 1024 * 1024  # 1 MiB per streamed chunk


def _stream_local_file_with_range(video_path: Path, request: Request) -> StreamingResponse:
    """HTTP range-request proxy for the local storage backend. Not used
    for GCS, which serves a signed URL redirect instead (see stream_video)
    -- GCS supports Range requests natively, so proxying through our own
    backend would just double the bandwidth for no benefit."""
    if not video_path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video file not found on disk")

    file_size = video_path.stat().st_size
    content_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"

    range_header = request.headers.get("range")
    start, end = 0, file_size - 1

    if range_header:
        match = re.match(r"bytes=(\d*)-(\d*)", range_header)
        if not match:
            raise HTTPException(status.HTTP_416_RANGE_NOT_SATISFIABLE, "Malformed Range header")
        start_str, end_str = match.groups()
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        if start > end or end >= file_size:
            raise HTTPException(
                status.HTTP_416_RANGE_NOT_SATISFIABLE,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

    chunk_length = end - start + 1

    def iter_range():
        with video_path.open("rb") as f:
            f.seek(start)
            remaining = chunk_length
            while remaining > 0:
                data = f.read(min(_CHUNK_SIZE, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_length),
    }
    status_code = status.HTTP_206_PARTIAL_CONTENT if range_header else status.HTTP_200_OK
    return StreamingResponse(iter_range(), status_code=status_code, media_type=content_type, headers=headers)


@router.get("/jobs/{job_id}/video")
def stream_video(
    job_id: UUID, request: Request,
    _current_user: CurrentUser = Depends(get_current_user_allow_query_token),
):
    """
    Serve the original uploaded dailies file so the dashboard's <video>
    element can play/scrub it.

    Behavior depends on STORAGE_BACKEND:
      - local: proxy-streams the file with HTTP range support.
      - gcs:   302-redirects to a short-lived V4 signed URL; the browser
               then talks to GCS directly (which supports Range requests
               natively), so our backend isn't in the video-bytes path at all.
    """
    settings = get_settings()
    job = _get_job_or_404(job_id)
    storage = get_storage_backend()

    if settings.storage_backend == "gcs":
        if not job.storage_key or not storage.exists(job.storage_key):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No uploaded video found for job {job_id}")
        signed_url = storage.get_signed_playback_url(
            job.storage_key, settings.gcs_signed_url_expiration_minutes,
        )
        return RedirectResponse(signed_url, status_code=status.HTTP_302_FOUND)

    # Local backend: storage_key may be empty for jobs created before this
    # column existed -- fall back to scanning the job's upload directory.
    if job.storage_key:
        video_path = settings.upload_dir / job.storage_key
    else:
        job_dir = settings.upload_dir / str(job_id)
        candidates = sorted(job_dir.iterdir()) if job_dir.is_dir() else []
        if not candidates:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No uploaded video found for job {job_id}")
        video_path = candidates[0]

    return _stream_local_file_with_range(video_path, request)
