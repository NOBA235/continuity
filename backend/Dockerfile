# Continuity.Agent -- backend + ADK agent runtime
FROM python:3.12-slim AS base

# ffmpeg/ffprobe are required by app/services/video_processor.py for keyframe
# extraction; this is not optional at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# --- Isolated venv for the ClickHouse MCP server -------------------------
# google-adk's MCP client code and mcp-clickhouse's server stack (via
# fastmcp) require incompatible major versions of the `mcp` SDK -- see
# app/config.py's mcp_clickhouse_command/_args comment and
# requirements.in's `mcp==1.29.1` pin for the full explanation. Building
# this into the image means the MCP server subprocess never depends on
# reaching PyPI at request time (unlike the local-dev default of
# `uv run --with mcp-clickhouse mcp-clickhouse`, which is convenient for
# zero-setup dev but fetches from PyPI on first launch).
RUN python -m venv /opt/mcp-clickhouse-venv \
    && /opt/mcp-clickhouse-venv/bin/pip install --no-cache-dir mcp-clickhouse==0.6.0
ENV MCP_CLICKHOUSE_COMMAND=/opt/mcp-clickhouse-venv/bin/mcp-clickhouse
# Empty JSON array -- overrides the local-dev default of
# ["run", "--with", "mcp-clickhouse", "mcp-clickhouse"], since the binary
# above is invoked directly with no wrapper arguments.
ENV MCP_CLICKHOUSE_ARGS=[]

COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

# Cloud Run / most container platforms inject $PORT; default to 8080 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
