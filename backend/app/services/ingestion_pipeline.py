"""
End-to-end ingestion pipeline for one uploaded video (one scene/take).

video file
  -> ffmpeg keyframe extraction (video_processor.py)
  -> per-frame Gemini structured analysis + embedding (gemini_vision.py), run
     with bounded concurrency to respect API rate limits while still handling
     the frame volumes ("millions of frame descriptors") the platform targets
  -> batched insert into ClickHouse frame_metadata
  -> ingestion_jobs status kept current throughout, so the dashboard can
     show live progress instead of a spinner with no feedback
"""
from __future__ import annotations

import json
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from app.config import get_settings
from app.db.clickhouse_client import insert_rows, query
from app.models.schemas import IngestionStatus
from app.observability.metrics import frames_processed_total, ingestion_jobs_failed_total
from app.services import gemini_vision, video_processor

logger = logging.getLogger("continuity_agent.ingestion_pipeline")

FRAME_METADATA_COLUMNS = [
    "scene_id", "take_id", "video_id", "timecode", "frame_number", "timestamp",
    "actor_id", "wardrobe_description", "prop_list", "prop_states",
    "lighting_vector", "embedding", "confidence_score", "gemini_model",
]

# Bounded worker pool for concurrent Gemini calls. Keep this well under the
# project's per-minute rate limit; tune via GEMINI_CONCURRENCY at deploy time.
MAX_CONCURRENT_GEMINI_CALLS = 6


def _update_job(
    job_id: UUID,
    scene_id: str,
    take_id: str,
    source_filename: str,
    storage_key: str,
    status: IngestionStatus,
    total_frames: int = 0,
    processed_frames: int = 0,
    error_message: str = "",
) -> None:
    now = datetime.now(timezone.utc)
    insert_rows(
        "ingestion_jobs",
        ["job_id", "scene_id", "take_id", "source_filename", "storage_key", "status",
         "total_frames", "processed_frames", "error_message", "created_at", "updated_at"],
        [[str(job_id), scene_id, take_id, source_filename, storage_key, status.value,
          total_frames, processed_frames, error_message, now, now]],
    )


def _process_single_frame(
    frame: video_processor.ExtractedFrame,
    scene_id: str,
    take_id: str,
    video_id: str,
    scene_context: str,
) -> list:
    """Analyze + embed one frame; returns a ClickHouse-ready row."""
    settings = get_settings()
    descriptor = gemini_vision.analyze_frame(frame.image_path, scene_context=scene_context)
    embedding = gemini_vision.embed_frame(frame.image_path)

    primary_actor_id = (
        descriptor.actor_positions[0].actor_id if descriptor.actor_positions else "unassigned"
    )
    frame_timestamp = datetime.now(timezone.utc) + timedelta(seconds=frame.timestamp_seconds)

    return [
        scene_id,
        take_id,
        video_id,
        frame.timecode,
        frame.frame_number,
        frame_timestamp,
        primary_actor_id,
        descriptor.wardrobe_description,
        descriptor.prop_list,
        json.dumps({entry.prop: entry.state for entry in descriptor.prop_states}),
        descriptor.lighting_vector,
        embedding,
        descriptor.confidence_score,
        settings.gemini_vision_model,
    ]


def _most_recent_scene_context(scene_id: str, take_id: str) -> str:
    """Pull a short summary of the prior take of this scene, if any, to give
    Gemini continuity context rather than analyzing each take in isolation."""
    rows = query(
        """
        SELECT take_id, count() AS frame_count, max(timestamp) AS last_seen
        FROM frame_metadata
        WHERE scene_id = {scene_id:String} AND take_id != {take_id:String}
        GROUP BY take_id
        ORDER BY last_seen DESC
        LIMIT 1
        """,
        {"scene_id": scene_id, "take_id": take_id},
    )
    if not rows:
        return f"Scene {scene_id}, take {take_id}. No prior takes recorded yet."
    prior = rows[0]
    return (
        f"Scene {scene_id}, take {take_id}. Compare against prior take "
        f"'{prior['take_id']}' ({prior['frame_count']} frames already indexed)."
    )


def ingest_video(
    video_path: Path,
    scene_id: str,
    take_id: str,
    job_id: UUID | None = None,
    storage_key: str = "",
) -> UUID:
    """
    Run the full pipeline synchronously and return the job_id. Intended to be
    invoked from a FastAPI BackgroundTask or a worker queue -- see
    routers/ingestion.py.

    `video_path` must already be a local, seekable file regardless of the
    configured storage backend -- the caller (routers/ingestion.py) is
    responsible for staging it there and for durably persisting it via
    `object_storage.save_upload()` *before* calling this function, so the
    upload survives even if ingestion itself fails partway through. When
    STORAGE_BACKEND=gcs, this function deletes the local staging copy once
    processing finishes, since GCS is the durable copy at that point.
    """
    settings = get_settings()
    job_id = job_id or uuid4()
    video_id = f"{scene_id}_{take_id}_{video_path.stem}"

    def update(status: IngestionStatus, **kwargs) -> None:
        _update_job(job_id, scene_id, take_id, video_path.name, storage_key, status, **kwargs)

    update(IngestionStatus.extracting_frames)

    try:
        frame_output_dir = settings.frame_cache_dir / str(job_id)
        frames = video_processor.extract_keyframes(video_path, frame_output_dir)
    except Exception as exc:  # noqa: BLE001 -- surface any extraction failure to the job row
        logger.exception("Keyframe extraction failed for job %s", job_id)
        update(IngestionStatus.failed, error_message=f"Keyframe extraction failed: {exc}")
        ingestion_jobs_failed_total.labels(scene_id=scene_id).inc()
        raise

    update(IngestionStatus.analyzing, total_frames=len(frames))

    scene_context = _most_recent_scene_context(scene_id, take_id)
    rows: list[list] = []
    processed = 0
    failures: list[str] = []

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_GEMINI_CALLS) as pool:
        future_to_frame = {
            pool.submit(_process_single_frame, frame, scene_id, take_id, video_id, scene_context): frame
            for frame in frames
        }
        for future in as_completed(future_to_frame):
            frame = future_to_frame[future]
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001
                logger.error("Gemini analysis failed for frame %s: %s", frame.frame_number, exc)
                failures.append(f"frame {frame.frame_number}: {exc}")
            processed += 1
            if processed % 25 == 0 or processed == len(frames):
                update(IngestionStatus.analyzing, total_frames=len(frames), processed_frames=processed)

    if rows:
        insert_rows("frame_metadata", FRAME_METADATA_COLUMNS, rows)
        frames_processed_total.labels(scene_id=scene_id).inc(len(rows))

    # Keyframe JPEGs are only needed for the duration of analysis -- never
    # served back to the frontend -- so they're cleaned up regardless of
    # storage backend. The source video's fate depends on the backend: see
    # the cleanup block below.
    shutil.rmtree(frame_output_dir, ignore_errors=True)

    if failures and not rows:
        update(
            IngestionStatus.failed, total_frames=len(frames), processed_frames=processed,
            error_message="; ".join(failures[:10]),
        )
        ingestion_jobs_failed_total.labels(scene_id=scene_id).inc()
        raise RuntimeError(f"All {len(failures)} frame analyses failed for job {job_id}")

    update(
        IngestionStatus.completed, total_frames=len(frames), processed_frames=len(rows),
        error_message="; ".join(failures[:10]) if failures else "",
    )
    logger.info(
        "Ingestion job %s complete: %d/%d frames indexed for %s/%s",
        job_id, len(rows), len(frames), scene_id, take_id,
    )

    if settings.storage_backend == "gcs" and storage_key:
        try:
            video_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove local staging copy for job %s", job_id)

    return job_id
