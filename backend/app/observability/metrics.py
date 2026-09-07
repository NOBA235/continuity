"""
Prometheus metrics, exposed at GET /metrics.

prometheus-fastapi-instrumentator handles the generic HTTP layer (request
count/latency/size by method+path+status) automatically. The counters
below are the business-specific ones nothing generic would give you --
incremented from the service code that actually knows when these things
happen (ingestion_pipeline.py, gemini_vision.py).
"""
from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator

frames_processed_total = Counter(
    "continuity_agent_frames_processed_total",
    "Keyframes successfully analyzed by Gemini and written to ClickHouse.",
    ["scene_id"],
)

gemini_api_errors_total = Counter(
    "continuity_agent_gemini_api_errors_total",
    "Gemini API calls that raised an error, by call type and status code.",
    ["call_type", "status_code"],
)

anomalies_flagged_total = Counter(
    "continuity_agent_anomalies_flagged_total",
    "Continuity anomalies written by the agent, by severity.",
    ["severity"],
)

ingestion_jobs_failed_total = Counter(
    "continuity_agent_ingestion_jobs_failed_total",
    "Ingestion jobs that ended in the 'failed' status.",
    ["scene_id"],
)


def configure_metrics(app: FastAPI, enabled: bool) -> None:
    if not enabled:
        return
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
