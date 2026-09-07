"""
Centralized application configuration.

Every external dependency (ClickHouse, Gemini) is configured exclusively
through environment variables. Nothing here is a stand-in value -- if a
required variable is missing, the app fails fast at startup rather than
silently falling back to a mock.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- ClickHouse -----------------------------------------------------
    clickhouse_host: str = Field(..., description="ClickHouse server hostname")
    clickhouse_port: int = Field(8443, description="ClickHouse HTTP(S) port")
    clickhouse_user: str = Field("default")
    clickhouse_password: str = Field(...)
    clickhouse_database: str = Field("continuity_agent")
    clickhouse_secure: bool = Field(True, description="Use HTTPS for ClickHouse")

    # --- Gemini / google-genai -------------------------------------------
    gemini_api_key: str = Field(..., description="Gemini Developer API key")
    # Frame-level extraction runs against every keyframe of every take, so it
    # defaults to a cost-efficient Flash-tier model. Override per deployment.
    gemini_vision_model: str = Field("gemini-3.6-flash")
    # The continuity-reasoning agent gets the strongest available model since
    # it runs once per scene/take, not once per frame.
    gemini_agent_model: str = Field("gemini-3-pro-preview")
    # Natively multimodal embedding model, used to embed each keyframe so
    # continuity_agent can do nearest-neighbour comparisons across takes.
    gemini_embedding_model: str = Field("gemini-embedding-2")
    gemini_embedding_dimensions: int = Field(768, ge=128, le=3072)

    # --- Video / ingestion pipeline --------------------------------------
    ffmpeg_binary: str = Field("ffmpeg")
    ffprobe_binary: str = Field("ffprobe")
    keyframe_interval_seconds: float = Field(
        1.0, gt=0, description="Sampling interval for keyframe extraction"
    )
    upload_dir: Path = Field(Path("/tmp/continuity-agent/uploads"))
    frame_cache_dir: Path = Field(Path("/tmp/continuity-agent/frames"))
    max_upload_size_mb: int = Field(4096)

    # --- MCP bridge (Agent -> ClickHouse) ---------------------------------
    # google-adk's MCP client code and mcp-clickhouse's server stack (via
    # fastmcp) require incompatible major versions of the `mcp` SDK, so the
    # server must run in a separate process with its own isolated
    # dependencies -- it is deliberately NOT installed into this backend's
    # own requirements.txt. Local dev default: `uv run --with mcp-clickhouse
    # mcp-clickhouse`, which uv resolves into an ephemeral isolated env with
    # zero setup. Production Dockerfile overrides both of these to point at
    # a venv baked into the image at build time instead (see Dockerfile),
    # so there's no runtime dependency on reaching PyPI.
    mcp_clickhouse_command: str = Field("uv")
    mcp_clickhouse_args: list[str] = Field(
        default_factory=lambda: ["run", "--with", "mcp-clickhouse", "mcp-clickhouse"]
    )
    mcp_clickhouse_allow_write: bool = Field(
        False,
        description=(
            "Whether the agent's MCP-backed ClickHouse tool may execute "
            "writes. Kept False by default: the agent writes anomalies "
            "through the dedicated flag_continuity_anomaly FunctionTool "
            "instead, which validates payloads before insert."
        ),
    )

    # --- Auth (JWT) -----------------------------------------------------
    jwt_secret_key: str = Field(
        ..., min_length=32,
        description="HMAC signing secret for access/refresh tokens. Generate "
        "with e.g. `openssl rand -hex 32`. Rotating this invalidates every "
        "outstanding token immediately.",
    )
    jwt_algorithm: str = Field("HS256")
    jwt_access_token_expire_minutes: int = Field(30)
    jwt_refresh_token_expire_days: int = Field(14)

    # --- Object storage (uploaded dailies) ---------------------------------
    storage_backend: Literal["local", "gcs"] = Field(
        "local",
        description="Where uploaded video files live. 'local' writes to "
        "upload_dir on the backend's own disk -- fine for a single instance "
        "or local dev, not for horizontal scaling. 'gcs' uploads to Google "
        "Cloud Storage and serves playback via short-lived V4 signed URLs.",
    )
    gcs_bucket_name: str | None = Field(None)
    gcs_signed_url_expiration_minutes: int = Field(60)

    # --- Observability ------------------------------------------------------
    log_level: str = Field("INFO")
    log_format: Literal["json", "console"] = Field(
        "json", description="'console' is easier to read locally; 'json' is "
        "what you want piped into Cloud Logging / any log aggregator."
    )
    otel_service_name: str = Field("continuity-agent-api")
    otel_exporter_otlp_endpoint: str | None = Field(
        None,
        description="OTLP HTTP endpoint (e.g. http://otel-collector:4318). "
        "If unset, traces are printed to stdout via ConsoleSpanExporter "
        "instead of dropped -- useful for local dev, not for production.",
    )
    metrics_enabled: bool = Field(True, description="Expose GET /metrics (Prometheus format).")

    # --- API ---------------------------------------------------------------
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    api_root_path: str = Field("")

    @field_validator("upload_dir", "frame_cache_dir", mode="after")
    @classmethod
    def _ensure_dir_exists(cls, value: Path) -> Path:
        value.mkdir(parents=True, exist_ok=True)
        return value

    @model_validator(mode="after")
    def _require_bucket_when_gcs_backend(self) -> "Settings":
        if self.storage_backend == "gcs" and not self.gcs_bucket_name:
            raise ValueError("GCS_BUCKET_NAME is required when STORAGE_BACKEND=gcs")
        return self


@lru_cache
def get_settings() -> Settings:
    """Settings are cached for the process lifetime -- construct once."""
    return Settings()  # type: ignore[call-arg]
