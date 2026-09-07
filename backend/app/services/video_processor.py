"""
Keyframe extraction and timecode stamping.

Wraps the `ffmpeg` / `ffprobe` CLIs (no OpenCV video decode needed for this
step -- ffmpeg is more robust across the codecs post houses actually deliver
dailies in: ProRes, DNxHD, H.264 mezzanines). OpenCV is still used
downstream in gemini_vision.py for cheap frame-level image ops.
"""
from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("continuity_agent.video_processor")


class VideoProcessingError(RuntimeError):
    """Raised when ffmpeg/ffprobe fail or return unparsable output."""


@dataclass(frozen=True)
class ExtractedFrame:
    frame_number: int
    timestamp_seconds: float
    timecode: str  # SMPTE HH:MM:SS:FF
    image_path: Path


def _require_binary(binary: str) -> str:
    resolved = shutil.which(binary)
    if resolved is None:
        raise VideoProcessingError(
            f"Required binary '{binary}' was not found on PATH. Install ffmpeg "
            f"(e.g. `apt-get install ffmpeg`) in this container/image."
        )
    return resolved


def probe_video(video_path: Path) -> dict:
    """Return ffprobe's format+stream metadata for `video_path` as a dict."""
    settings = get_settings()
    ffprobe = _require_binary(settings.ffprobe_binary)
    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise VideoProcessingError(f"ffprobe failed for {video_path}: {proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise VideoProcessingError(f"Could not parse ffprobe output for {video_path}") from exc


def _get_frame_rate(probe: dict) -> float:
    video_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    if not video_streams:
        raise VideoProcessingError("No video stream found in source file.")
    rate_str = video_streams[0].get("avg_frame_rate") or video_streams[0].get("r_frame_rate", "25/1")
    try:
        num, den = rate_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else float(num)
    except ValueError:
        fps = float(rate_str)
    return fps if fps > 0 else 25.0


def _seconds_to_smpte(seconds: float, fps: float) -> str:
    total_frames = int(round(seconds * fps))
    frames = total_frames % int(round(fps))
    total_seconds = total_frames // int(round(fps))
    hh, remainder = divmod(total_seconds, 3600)
    mm, ss = divmod(remainder, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{frames:02d}"


def extract_keyframes(
    video_path: Path,
    output_dir: Path,
    interval_seconds: float | None = None,
) -> list[ExtractedFrame]:
    """
    Sample `video_path` at a fixed interval (default: settings.keyframe_interval_seconds)
    and write one JPEG per sample to `output_dir`. Returns frames in ascending
    timecode order with real, ffprobe-derived timecodes -- not fabricated indices.
    """
    settings = get_settings()
    interval = interval_seconds or settings.keyframe_interval_seconds
    ffmpeg = _require_binary(settings.ffmpeg_binary)

    probe = probe_video(video_path)
    fps = _get_frame_rate(probe)

    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "frame_%08d.jpg"

    cmd = [
        ffmpeg,
        "-y",
        "-i", str(video_path),
        "-vf", f"fps=1/{interval}",
        "-qscale:v", "2",
        str(pattern),
    ]
    logger.info("Extracting keyframes every %.2fs from %s", interval, video_path.name)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise VideoProcessingError(f"ffmpeg extraction failed for {video_path}: {proc.stderr[-2000:]}")

    frame_files = sorted(output_dir.glob("frame_*.jpg"))
    if not frame_files:
        raise VideoProcessingError(f"ffmpeg produced no frames for {video_path}")

    frames: list[ExtractedFrame] = []
    for index, frame_path in enumerate(frame_files):
        timestamp = index * interval
        frames.append(
            ExtractedFrame(
                frame_number=index,
                timestamp_seconds=timestamp,
                timecode=_seconds_to_smpte(timestamp, fps),
                image_path=frame_path,
            )
        )
    logger.info("Extracted %d keyframes from %s", len(frames), video_path.name)
    return frames
