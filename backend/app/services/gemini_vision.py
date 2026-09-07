"""
Gemini-backed frame analysis.

Two responsibilities:
  1. analyze_frame()  -- multimodal structured extraction of props, wardrobe,
     actor blocking, and lighting from a single keyframe image.
  2. embed_frame()    -- a multimodal embedding of the same keyframe, stored
     alongside the descriptor so the continuity agent (or a human) can do
     nearest-neighbour "does this look different" queries in ClickHouse.

Both call the real Gemini API through google-genai. There is no offline
fallback: if GEMINI_API_KEY is missing or invalid, calls raise immediately
via google.genai.errors.APIError rather than returning fabricated data.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from google import genai
from google.genai import errors, types
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.models.schemas import FrameDescriptor
from app.observability.metrics import gemini_api_errors_total

logger = logging.getLogger("continuity_agent.gemini_vision")

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

_ANALYSIS_INSTRUCTION = """\
You are an expert script supervisor reviewing a single frame of film/TV \
dailies footage for continuity-relevant detail. Examine the image closely \
and report ONLY what is visually verifiable in this exact frame -- do not \
infer plot, dialogue, or anything outside the frame. Be specific about \
prop states (fill levels, open/closed, lit/unlit, position on set), exact \
wardrobe details (garment color/state, accessories, hair/makeup continuity \
markers), each visible actor's screen position and posture, and the \
lighting setup (key/fill balance, color temperature, direction, visible \
practicals). If a value cannot be determined confidently, still provide \
your best estimate and reflect the uncertainty in confidence_score.\
"""


@lru_cache
def _get_client() -> genai.Client:
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, errors.APIError) and getattr(exc, "code", None) in _RETRYABLE_STATUS_CODES


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def analyze_frame(image_path: Path, scene_context: str = "") -> FrameDescriptor:
    """
    Send one keyframe image to Gemini and get back a validated FrameDescriptor.

    `scene_context` is optional free text (e.g. "Scene 14A, Take 3 -- diner
    booth, continuing from Take 2") that helps the model reason about what
    should or shouldn't have changed, without ever being treated as ground
    truth to copy back verbatim.
    """
    client = _get_client()
    settings = get_settings()
    image_bytes = image_path.read_bytes()
    mime_type = "image/jpeg" if image_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"

    prompt_parts: list[types.Part | str] = [_ANALYSIS_INSTRUCTION]
    if scene_context:
        prompt_parts.append(f"Context for this frame: {scene_context}")
    prompt_parts.append(
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    )

    try:
        response = client.models.generate_content(
            model=settings.gemini_vision_model,
            contents=prompt_parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=FrameDescriptor,
                temperature=0.1,
            ),
        )
    except errors.APIError as exc:
        logger.error("Gemini frame analysis failed for %s: %s", image_path.name, exc)
        gemini_api_errors_total.labels(call_type="analyze_frame", status_code=str(exc.code)).inc()
        raise

    parsed = response.parsed
    if parsed is None:
        # Fall back to manual validation in the rare case the SDK couldn't
        # auto-parse (e.g. the model wrapped JSON in prose despite the config).
        parsed = FrameDescriptor.model_validate_json(response.text)
    return parsed  # type: ignore[return-value]


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def embed_frame(image_path: Path) -> list[float]:
    """Return a Gemini Embedding vector for the given keyframe image."""
    client = _get_client()
    settings = get_settings()
    image_bytes = image_path.read_bytes()
    mime_type = "image/jpeg" if image_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"

    try:
        response = client.models.embed_content(
            model=settings.gemini_embedding_model,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
            config=types.EmbedContentConfig(
                output_dimensionality=settings.gemini_embedding_dimensions,
            ),
        )
    except errors.APIError as exc:
        logger.error("Gemini embedding failed for %s: %s", image_path.name, exc)
        gemini_api_errors_total.labels(call_type="embed_frame", status_code=str(exc.code)).inc()
        raise

    if not response.embeddings:
        raise RuntimeError(f"Gemini returned no embedding for {image_path.name}")
    return list(response.embeddings[0].values)
