"""
Pydantic models shared between the ingestion pipeline, the ADK agent tools,
and the FastAPI routers. Keeping one canonical set of models means the
JSON schema handed to Gemini for structured extraction, the rows written to
ClickHouse, and the JSON returned to the frontend all stay in lock-step.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# Frame-level continuity descriptors (the shape Gemini is asked to return)
# ---------------------------------------------------------------------------
class ActorPosition(BaseModel):
    actor_id: str = Field(description="Stable identifier for the actor/character in frame")
    screen_region: str = Field(
        description="Coarse position in frame, e.g. 'foreground-left', 'background-center'"
    )
    posture: str = Field(description="Standing, seated, leaning on counter, etc.")


class FrameDescriptor(BaseModel):
    """Structured output requested from Gemini for a single keyframe."""

    wardrobe_description: str = Field(
        description="Concise description of each visible actor's wardrobe and any visible changes"
    )
    prop_list: list[str] = Field(description="Every distinct prop visible in frame")
    prop_states: dict[str, str] = Field(
        default_factory=dict,
        description="Visual state per prop, e.g. {'wine_glass_fill_level': '50%'}",
    )
    actor_positions: list[ActorPosition] = Field(default_factory=list)
    lighting_description: str = Field(
        description="Key/fill balance, color temperature, direction, practicals visible"
    )
    lighting_vector: list[float] = Field(
        description="Numeric encoding [key_intensity_0to1, fill_intensity_0to1, "
        "color_temp_kelvin/1000, key_angle_degrees/360]"
    )
    confidence_score: float = Field(ge=0.0, le=1.0)


class FrameMetadataRecord(BaseModel):
    """One row of frame_metadata, as returned to API clients."""

    scene_id: str
    take_id: str
    video_id: str
    timecode: str
    frame_number: int
    timestamp: datetime
    actor_id: str
    wardrobe_description: str
    prop_list: list[str]
    prop_states: str
    lighting_vector: list[float]
    confidence_score: float
    gemini_model: str


# ---------------------------------------------------------------------------
# Continuity anomalies
# ---------------------------------------------------------------------------
class AnomalyType(str, Enum):
    prop_mismatch = "prop_mismatch"
    wardrobe_mismatch = "wardrobe_mismatch"
    position_mismatch = "position_mismatch"
    lighting_mismatch = "lighting_mismatch"
    continuity_other = "continuity_other"


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ContinuityAnomaly(BaseModel):
    anomaly_id: UUID | None = None
    scene_id: str
    take_id: str
    compared_take_id: str
    frame_number_a: int
    frame_number_b: int
    timecode_a: str
    timecode_b: str
    anomaly_type: AnomalyType
    description: str
    severity: Severity
    detected_by_agent: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    resolved: bool = False
    resolved_note: str = ""
    detected_at: datetime | None = None


# ---------------------------------------------------------------------------
# Agent execution trace
# ---------------------------------------------------------------------------
class AgentStepType(str, Enum):
    reasoning = "reasoning"
    tool_call = "tool_call"
    tool_result = "tool_result"
    anomaly_flagged = "anomaly_flagged"
    final_report = "final_report"
    error = "error"


class AgentExecutionStep(BaseModel):
    execution_id: UUID
    agent_name: str
    scene_id: str
    take_id: str
    step_number: int
    step_type: AgentStepType
    tool_name: str = ""
    input_payload: str = ""
    output_payload: str = ""
    latency_ms: int = 0
    started_at: datetime


# ---------------------------------------------------------------------------
# Ingestion jobs
# ---------------------------------------------------------------------------
class IngestionStatus(str, Enum):
    pending = "pending"
    extracting_frames = "extracting_frames"
    analyzing = "analyzing"
    completed = "completed"
    failed = "failed"


class IngestionJob(BaseModel):
    job_id: UUID
    scene_id: str
    take_id: str
    source_filename: str
    storage_key: str = ""
    status: IngestionStatus
    total_frames: int = 0
    processed_frames: int = 0
    error_message: str = ""
    created_at: datetime
    updated_at: datetime


class IngestionRequest(BaseModel):
    scene_id: str = Field(min_length=1, max_length=128)
    take_id: str = Field(min_length=1, max_length=128)


class AgentRunRequest(BaseModel):
    scene_id: str
    take_id: str
    compare_against_take_id: str | None = Field(
        default=None,
        description="If omitted, the agent compares this take against the "
        "most recent prior take of the same scene it can find in ClickHouse.",
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    viewer = "viewer"
    editor = "editor"
    supervisor = "supervisor"


# bcrypt silently ignores bytes beyond 72 -- reject up front instead of
# accepting a password whose tail is meaningless to the hash.
_MAX_PASSWORD_BYTES = 72


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(default="", max_length=200)
    role: UserRole = UserRole.viewer

    @field_validator("password")
    @classmethod
    def _password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > _MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must be at most {_MAX_PASSWORD_BYTES} bytes")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserPublic(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    role: UserRole
    created_at: datetime


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class CurrentUser(BaseModel):
    """What the `get_current_user` dependency injects into route handlers --
    decoded straight from JWT claims, no per-request database round trip."""

    user_id: UUID
    email: str
    role: UserRole
