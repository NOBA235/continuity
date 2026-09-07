# Continuity.Agent

AI-powered Script Supervisor & Visual Continuity QA for film/TV post-production.
Ingests dailies video, uses Gemini's multimodal API to extract frame-level
continuity descriptors, indexes them in ClickHouse, and runs a Google ADK
agent — reading through the official ClickHouse MCP server, writing through
a validated native tool — that flags visual continuity breaks across takes.

## Architecture

```
                 ffmpeg keyframe extraction         Gemini 3.x multimodal
  dailies.mp4 ───────────────────────────► frames ──────────────────────► FrameDescriptor
                (video_processor.py)                (gemini_vision.py)     + embedding
                                                                                │
                                                                                ▼
                                                                       ClickHouse
                                                                    frame_metadata
                                                                                │
                              ┌─────────────────────────────────────────────────┤
                              │                                                 │
                     McpToolset (stdio,                              FunctionTool (native)
                    isolated subprocess)                          flag_continuity_anomaly
                  ── mcp-clickhouse server ──                     (Pydantic-validated write)
                  list_databases / list_tables /                              │
                        run_query (read-only)                                 │
                              │                                                 ▼
                              └──────────────► ADK LlmAgent ──────► continuity_anomalies
                                          (continuity_anomaly_agent)  + agent_execution_log

                          Next.js dashboard ◄── FastAPI REST (JWT-authenticated) ◄── all of the above
```

- **Backend**: FastAPI (Python 3.12), orchestrating ingestion and exposing
  the REST API the dashboard uses. JWT-authenticated, structured-logged,
  traced, and metriced (see "Production hardening" below).
- **Agent**: Google ADK (`google-adk`) `LlmAgent`, using Gemini for
  reasoning and tool-calling. Reads ClickHouse via the official
  [`mcp-clickhouse`](https://pypi.org/project/mcp-clickhouse/) MCP server,
  launched as an **isolated** subprocess (see "A real dependency conflict"
  below for why it can't share the backend's own Python environment);
  writes anomalies through a native ADK `FunctionTool` so every write is
  schema-validated before it reaches the database, rather than trusting
  LLM-composed SQL `INSERT`s.
- **Vision**: `google-genai`, calling Gemini for both structured frame
  analysis (`response_schema`-constrained JSON) and multimodal embeddings
  (`gemini-embedding-2`), used for cross-take similarity search directly in
  ClickHouse via `cosineDistance(...)`.
- **Database**: ClickHouse (`MergeTree` family engines — see
  `backend/app/db/schema.sql` for the full native DDL).
- **Frontend**: Next.js 16 (App Router, Turbopack), Tailwind v4, a custom
  video player with a continuity-anomaly "flag rail" on the scrub bar, an
  anomaly log table, and a live agent execution trace viewer.

## What's real here, and what you still need to supply

This is real, typed, tested code with no mocked data paths — but it still
depends on paid external services that only you can provision:

| You need to provide | Used for |
|---|---|
| A ClickHouse instance (Cloud or self-hosted) | All persistence, including user accounts |
| A `GEMINI_API_KEY` (or Vertex AI credentials) | Frame analysis, embeddings, agent reasoning |
| A `JWT_SECRET_KEY` (`openssl rand -hex 32`) | Signing access/refresh tokens |
| ffmpeg on the backend host/image | Keyframe extraction (already in `backend/Dockerfile`) |
| `uv` on PATH for local dev, *or* Docker | Launching the isolated MCP server subprocess |
| A GCS bucket + credentials, if `STORAGE_BACKEND=gcs` | Durable video storage beyond one instance |

Nothing in this codebase falls back to fabricated data if these are
missing — `app/config.py` raises a validation error at startup instead
(verified: see "Verification" below).

## Auth

JWT-based, with three roles: `viewer` (read-only), `editor` (can upload
dailies, resolve anomalies, run the agent), `supervisor` (all of the above,
plus creating accounts). The **first account ever created** on a fresh
database gets no-auth-required bootstrap access and is always granted
`supervisor`, regardless of what role the request asked for — there has to
be one admin who can invite everyone else. Every registration after that
requires a valid supervisor access token (`POST /api/auth/register`).

```bash
# Bootstrap the first account (only works while the users table is empty)
curl -X POST http://localhost:8080/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@studio.com", "password": "a-real-password"}'

curl -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "you@studio.com", "password": "a-real-password"}'
# -> {"access_token": "...", "refresh_token": "...", ...}
```

**Documented limitation**: identity/role checks are decoded straight from
the signed JWT, not looked up in ClickHouse on every request — cheap (one
signature check per request) but it means deactivating an account or
changing its role doesn't take effect until that account's current access
token expires (30 minutes by default). There's no token revocation list.
If you need immediate revocation, the place to add it is
`app/auth/dependencies.py:get_current_user` — check the `jti` claim against
a denylist (Redis, or a ClickHouse table) before trusting the token.

Two more specifics worth knowing:
- The frontend stores tokens in `localStorage` (`lib/auth.ts`) and
  refreshes on a 401/403 automatically. That's the standard tradeoff for a
  token-based SPA (simple, but vulnerable to token theft via XSS) — an
  httpOnly-cookie-based session would close that gap at the cost of more
  moving parts (CSRF handling, same-site cookie config across the
  frontend/backend origins).
- `<video src="...">` can't attach an `Authorization` header, so
  `GET /api/ingestion/jobs/{job_id}/video` is the one endpoint that also
  accepts the token as `?access_token=...`
  (`get_current_user_allow_query_token` in `app/auth/dependencies.py`) —
  every other endpoint requires the header. A token in a URL is more
  likely to end up in access logs or browser history, which is why this
  isn't the default everywhere.

## Object storage

`STORAGE_BACKEND=local` (default) writes uploaded dailies to disk — fine
for local dev or a single long-lived instance. `STORAGE_BACKEND=gcs`
uploads to Google Cloud Storage and serves playback via short-lived V4
signed URLs (`app/services/object_storage.py`); the browser then talks to
GCS directly for the actual video bytes (GCS supports HTTP Range requests
natively), so the backend isn't in the bandwidth path at all. Switching
backends requires no other code changes — the ingestion pipeline and the
video-streaming endpoint both go through the same `StorageBackend`
interface.

## Observability

- **Structured logs** (`structlog`): every line is one JSON object
  (`LOG_FORMAT=json`) or colorized console output (`LOG_FORMAT=console`
  for local dev), and every log line emitted during a request — including
  deep inside the ADK agent's tool calls — carries that request's
  `request_id` automatically via `structlog.contextvars`.
- **Request tracing** (`RequestContextMiddleware`): a `request_id` is
  generated (or reused from an incoming `X-Request-Id` header) per
  request, echoed back in the response headers, and logged alongside
  method/path/status/latency for every request.
- **Distributed tracing** (OpenTelemetry): `FastAPIInstrumentor` spans
  every request automatically. Set `OTEL_EXPORTER_OTLP_ENDPOINT` to ship
  spans to a collector; unset, they print to stdout via
  `ConsoleSpanExporter` so tracing is visibly wired up even without one.
- **Metrics** (`GET /metrics`, Prometheus format): generic HTTP metrics
  (`prometheus-fastapi-instrumentator`) plus business counters —
  `continuity_agent_frames_processed_total`,
  `continuity_agent_anomalies_flagged_total`,
  `continuity_agent_gemini_api_errors_total`,
  `continuity_agent_ingestion_jobs_failed_total` — incremented from the
  actual service code, not derived after the fact.
- **Health checks**, split for how k8s/Cloud Run actually use them:
  `GET /api/health/live` (process is up, no dependency checks — failing
  this restarts the container, which won't fix a ClickHouse outage) vs.
  `GET /api/health/ready` (pings ClickHouse, returns 503 with the specific
  failure if it's unreachable — this is what should gate traffic).

## Quickstart (local dev, Docker)

```bash
cp backend/.env.example backend/.env
# then fill in GEMINI_API_KEY and JWT_SECRET_KEY (openssl rand -hex 32)
docker compose up --build
```

This brings up a local ClickHouse instance, the backend on :8080, and the
dashboard on :3000. Schema migrations run automatically on backend startup
(`app/db/migrate.py`, called from `main.py`'s lifespan handler). The
backend's Docker image bakes in an isolated venv for the MCP server (see
below), so it has no runtime dependency on reaching PyPI.

## Quickstart (without Docker)

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
apt-get install ffmpeg   # or brew install ffmpeg on macOS
pip install uv           # or: curl -LsSf https://astral.sh/uv/install.sh | sh
                          # (launches the isolated MCP server subprocess -- see below)
cp .env.example .env     # fill in CLICKHOUSE_*, GEMINI_API_KEY, JWT_SECRET_KEY
uvicorn app.main:app --reload --port 8080

# Frontend (separate terminal)
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

## Using it

1. Open the dashboard. On first run, use the **First-time setup** tab to
   create the initial (supervisor) account -- this only works once, while
   the `users` table is empty. After that, everyone signs in through
   **Sign in**. Tokens are stored in `localStorage` and refreshed
   automatically on expiry (see "Auth" above for the one limitation this
   implies).
2. Pick (or type) a scene id and take id.
3. Click **Upload dailies** and choose a video file (requires an
   editor/supervisor account -- viewers see this control disabled).
   Ingestion (keyframe extraction → Gemini analysis → ClickHouse) runs as
   a background task; the dashboard polls job status automatically.
4. Once at least two takes of a scene are indexed, click
   **Run continuity check**. The agent's reasoning, tool calls, and any
   anomalies it flags stream into the **Agent Trace** tab in near
   real time; flagged anomalies also appear in the **Continuity Log**
   tab and as colored ticks on the video's scrub bar.

## Running the backend tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest -v
```

69 tests, no external services required (ClickHouse/Gemini/GCS calls are
mocked; the ffmpeg integration test generates its own synthetic clip).

## A real dependency conflict, and how it's handled

`google-adk`'s MCP client code and `mcp-clickhouse`'s server stack (via
`fastmcp`) require **incompatible major versions of the `mcp` SDK** —
`google-adk` imports `mcp.shared.session.ProgressFnT`, which was removed
in `mcp` 2.x, while current `mcp-clickhouse` needs `fastmcp` 4.x, which
needs `mcp` 2.x. They cannot both be installed in one environment.

This is handled by never installing `mcp-clickhouse` alongside the
backend's own dependencies at all — it runs as a fully separate
subprocess with its own isolated environment:
- **Local dev**: `uv run --with mcp-clickhouse mcp-clickhouse` (the
  default `MCP_CLICKHOUSE_COMMAND`/`_ARGS` in `app/config.py`), which `uv`
  resolves into an ephemeral env on first launch.
- **Docker**: the image bakes a dedicated venv at
  `/opt/mcp-clickhouse-venv` at build time (see `backend/Dockerfile`), so
  there's no runtime dependency on reaching PyPI at all.

`requirements.in` pins `mcp==1.29.1` explicitly (the version google-adk's
client code needs) specifically so a future `pip install -r
requirements.in` re-resolve can't silently pull in `mcp` 2.x again and
reintroduce this breakage. `tests/test_app_imports.py` exists because this
exact failure slipped past the rest of the suite the first time — no other
test imports `app.main` together with the agent module, since normal unit
tests mock the agent out. That test now imports both together on every run.

## Verification performed while building this

Rather than assert this all works, here's what was actually checked in a
sandboxed environment with network access to PyPI/npm (but not to
ClickHouse Cloud, the Gemini API, or GCS themselves):

- **Backend**: `pip install`'d the real dependency set (resolving several
  actual version conflicts along the way — see above for the sharpest
  one), then inspected the installed packages' real APIs (`McpToolset` vs.
  the deprecated `MCPToolset`, `mcp-clickhouse`'s actual tool names and env
  vars, `google-genai`'s `Part.from_bytes` / `response.parsed` /
  `embed_content` signatures, `google-cloud-storage`'s `Blob` methods,
  PyJWT's exception hierarchy, `structlog`/OpenTelemetry/Prometheus setup
  patterns) before writing code against any of them.
- **69 backend tests pass** (`cd backend && pytest`), including:
  - an ffmpeg integration test extracting real keyframes with correct
    SMPTE timecodes from a synthetically generated clip;
  - HTTP range-request byte-slicing tests (full file, partial range,
    open-ended range, out-of-bounds range, 404, and a GCS-backend
    signed-URL redirect variant);
  - JWT tests covering token-type confusion (refresh token rejected where
    an access token belongs and vice versa), tampered signatures, wrong
    signing secrets, and expiry;
  - a bootstrap-then-invite-only registration flow test;
  - GCS backend tests with the `google-cloud-storage` client mocked
    (verifying the exact calls: bucket/blob names, V4 signed-URL
    parameters);
  - request-ID propagation, custom Prometheus counters actually appearing
    in `/metrics` output, and liveness/readiness health-check behavior.
  - Writing these caught several real bugs before they shipped: a retry
    filter defined but never wired into `tenacity`'s decorator; a
    deprecated Starlette status constant; a `ReplacingMergeTree` version
    column that would have let every login silently overwrite an
    account's real creation timestamp; and the `mcp` 1.x/2.x conflict
    above, which nothing in the original test suite would have caught.
- **Frontend**: `npm install` (0 vulnerabilities after pinning `postcss`
  past a known high-severity advisory), `tsc --noEmit` (zero errors), and
  `npm run build` (clean Turbopack production build) all pass. The
  custom Tailwind v4 `@theme` color tokens were confirmed to actually
  compile into the output CSS, not just look right in the token
  definitions.

## Production hardening not included here

Auth, cloud storage, and observability (above) were built out in a second
pass, including a login/first-time-setup screen in the dashboard. What's
still intentionally out of scope:

- **No token revocation list** — see the documented tradeoff in "Auth"
  above.
- **CI/CD pipelines and IaC** (Terraform/Pulumi) for the ClickHouse +
  Cloud Run/GKE deployment.
- **Rate limiting** on the upload and agent-run endpoints (both cost real
  Gemini API spend per call; an authenticated-but-malicious or just
  overeager client could run either in a tight loop today).
- **Alerting** on the metrics/traces above — they're exported, but nothing
  is currently configured to page anyone when `ingestion_jobs_failed_total`
  spikes.

## Repo layout

```
backend/
  app/
    config.py                    Settings (env-var driven, fails fast)
    auth/
      security.py                 Password hashing (bcrypt), JWT issuance/verification
      dependencies.py              get_current_user, require_role FastAPI dependencies
    observability/
      logging_config.py            structlog setup (JSON or console)
      middleware.py                 Request-ID propagation + access logging
      tracing.py                    OpenTelemetry FastAPI instrumentation
      metrics.py                    Prometheus /metrics + custom business counters
    db/                            ClickHouse DDL, client, migrations
    models/schemas.py              Shared Pydantic models
    services/
      video_processor.py           ffmpeg keyframe extraction + SMPTE timecoding
      gemini_vision.py             Gemini structured analysis + embeddings
      ingestion_pipeline.py        Orchestrates the above into ClickHouse
      object_storage.py             Local disk / GCS storage backend abstraction
      user_store.py                 ClickHouse-backed user accounts
    agents/continuity_agent/
      agent.py                     ADK LlmAgent + isolated McpToolset wiring
      tools.py                     Native FunctionTool (validated writes)
      prompts.py                   Agent system instructions
      runner.py                    Drives the ADK Runner, persists the trace
    routers/                        FastAPI endpoints (auth, ingestion, frames, anomalies, agent)
  tests/                            pytest suite (69 tests)
frontend/
  app/                              Next.js App Router pages
  components/                       VideoPlayer, AnomalyLogTable, AgentTraceLog, LoginScreen, ...
  lib/                              Typed API client, auth (login/tokens/refresh), shared types/utils
docker-compose.yml                  Local dev stack (backend + frontend + ClickHouse)
```
