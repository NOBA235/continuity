from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db.clickhouse_client import get_clickhouse_client
from app.db.migrate import run_migrations
from app.observability.logging_config import configure_logging
from app.observability.metrics import configure_metrics
from app.observability.middleware import RequestContextMiddleware
from app.observability.tracing import configure_tracing
from app.routers import agent, anomalies, auth, frames, ingestion

_settings = get_settings()
configure_logging(_settings)
logger = structlog.get_logger("continuity_agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "starting_api",
        clickhouse_host=_settings.clickhouse_host,
        clickhouse_database=_settings.clickhouse_database,
        storage_backend=_settings.storage_backend,
    )
    run_migrations()
    yield
    logger.info("shutting_down_api")


app = FastAPI(
    title="Continuity.Agent",
    description="AI-powered Script Supervisor & Visual Continuity QA platform",
    version="0.1.0",
    lifespan=lifespan,
    root_path=_settings.api_root_path,
)

app.add_middleware(RequestContextMiddleware)

configure_metrics(app, _settings.metrics_enabled)

app.include_router(auth.router)
app.include_router(ingestion.router)
app.include_router(frames.router)
app.include_router(anomalies.router)
app.include_router(agent.router)

configure_tracing(app, _settings)

# Keep CORS outermost so browser clients receive CORS headers even when a
# downstream route raises an unhandled exception and returns HTTP 500.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all so an unexpected error still returns structured JSON (not a
    bare 500 HTML page) and gets logged with whatever request_id the
    RequestContextMiddleware already bound -- structlog's contextvars carry
    it here automatically, no need to thread it through manually."""
    logger.exception("unhandled_exception", path=request.url.path, method=request.method)
    # ServerErrorMiddleware sits outside the user middleware stack, so an
    # exception response produced here can otherwise bypass CORSMiddleware.
    # Preserve CORS headers for configured browser origins so a real backend
    # failure is visible to the client rather than misreported as a CORS one.
    origin = request.headers.get("origin")
    headers: dict[str, str] = {}
    if origin in _settings.cors_allow_origins:
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers=headers,
    )


@app.get("/api/health/live")
def liveness() -> dict:
    """Process is up and serving requests. No dependency checks -- this is
    what a k8s/Cloud Run liveness probe should hit; failing it restarts the
    container, which won't fix a downstream ClickHouse outage."""
    return {"status": "ok"}


@app.get("/api/health/ready")
def readiness() -> JSONResponse:
    """Can this instance actually serve traffic right now? Checks the one
    hard dependency every request needs (ClickHouse). Gemini isn't checked
    here -- it's only touched during ingestion/agent runs, not on the
    request path this probe is meant to gate."""
    checks: dict[str, str] = {}
    healthy = True

    try:
        get_clickhouse_client().ping()
        checks["clickhouse"] = "ok"
    except Exception as exc:  # noqa: BLE001 -- report *why*, don't just fail
        checks["clickhouse"] = f"unreachable: {exc}"
        healthy = False

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )


@app.get("/api/health")
def health_check() -> dict:
    """Kept for simple uptime monitors that just want one boolean-ish
    endpoint; equivalent to /api/health/ready without the dependency detail."""
    return {"status": "ok", "service": "continuity-agent-api"}
