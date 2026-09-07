"""
Two small pieces of request-scoped observability:

  1. Every request gets a request_id (reused from an incoming X-Request-Id
     header if the caller/load-balancer already set one, otherwise
     generated fresh), bound into structlog's contextvars so every log line
     emitted anywhere during that request -- including deep in the ADK
     agent's tool calls -- carries it automatically, and echoed back in the
     response header so a client can correlate its own logs with ours.
  2. A single structured access log line per request: method, path, status,
     latency_ms, and the same request_id.
"""
from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger("continuity_agent.access")

REQUEST_ID_HEADER = "X-Request-Id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.exception(
                "request_failed", method=request.method, path=request.url.path, latency_ms=latency_ms,
            )
            raise

        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
