"""
Distributed tracing via OpenTelemetry.

FastAPIInstrumentor auto-creates a span per request; nothing else in this
app needs to be touched for basic request tracing to show up. If
OTEL_EXPORTER_OTLP_ENDPOINT is set (pointing at an OTel Collector, Jaeger,
Cloud Trace's OTLP ingester, etc.), spans ship there over HTTP. If it's
unset -- the default for local dev -- spans render to stdout via
ConsoleSpanExporter instead of being silently dropped, so tracing is
visibly wired up even before you have a collector running.
"""
from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor

from app.config import Settings


def configure_tracing(app: FastAPI, settings: Settings) -> None:
    resource = Resource.create({SERVICE_NAME: settings.otel_service_name})
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter_otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    # Use generic ASGI instrumentation instead of FastAPIInstrumentor. The
    # FastAPI instrumentor currently crashes while resolving CORS OPTIONS
    # requests against included routers with this FastAPI/Starlette version.
    app.add_middleware(OpenTelemetryMiddleware, tracer_provider=provider)
