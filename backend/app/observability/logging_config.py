"""
Structured logging via structlog. Every log line carries whatever is bound
into the current request's context (currently: request_id -- see
middleware.py), rendered as one JSON object per line in production so it's
directly queryable in Cloud Logging / any log aggregator that ingests JSON,
or as human-readable colored output for local dev (LOG_FORMAT=console).

This also routes the stdlib `logging` module (which every third-party
library, and most of this app's own modules, still use via
`logging.getLogger(...)`) through the same structlog processors, so you get
one consistent log format regardless of which module emitted the line.
"""
from __future__ import annotations

import logging
import sys

import structlog

from app.config import Settings


def configure_logging(settings: Settings) -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(settings.log_level.upper())

    # Quiet down noisy third-party loggers that would otherwise dominate
    # output at INFO -- their own logs still flow through if raised to WARNING+.
    for noisy_logger in ("httpx", "httpcore", "google_genai.models"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
