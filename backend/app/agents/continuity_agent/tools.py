"""
Native ADK tools for the continuity agent.

Reads happen through the MCP bridge (see agent.py -- MCPToolset wired to the
official `mcp-clickhouse` server, exposing list_databases/list_tables/run_query
as MCP tools per Google's Model Context Protocol). Writes happen here,
through a plain ADK FunctionTool, so every anomaly the agent raises is
validated by Pydantic before it ever reaches ClickHouse -- an LLM-composed
SQL INSERT is not something we want to trust directly, and mcp-clickhouse's
CLICKHOUSE_ALLOW_WRITE_ACCESS is deliberately left False for that reason
(see app/config.py).
"""
from __future__ import annotations

import logging

from pydantic import ValidationError

from app.db.clickhouse_client import insert_rows
from app.models.schemas import AnomalyType, ContinuityAnomaly, Severity
from app.observability.metrics import anomalies_flagged_total

logger = logging.getLogger("continuity_agent.agent_tools")

ANOMALY_COLUMNS = [
    "scene_id", "take_id", "compared_take_id", "frame_number_a", "frame_number_b",
    "timecode_a", "timecode_b", "anomaly_type", "description", "severity",
    "detected_by_agent", "confidence_score",
]


def flag_continuity_anomaly(
    scene_id: str,
    take_id: str,
    compared_take_id: str,
    frame_number_a: int,
    frame_number_b: int,
    timecode_a: str,
    timecode_b: str,
    anomaly_type: str,
    description: str,
    severity: str,
    confidence_score: float,
) -> dict:
    """Record a continuity anomaly you have identified between two frames.

    Call this once per distinct anomaly you find while comparing frames
    across takes (or within a take). Do not call it for differences that
    are expected continuity (e.g. an actor naturally moved between two
    non-adjacent script beats) -- only for inconsistencies that would read
    as a visible error on screen.

    Args:
        scene_id: The scene identifier being reviewed.
        take_id: The take that contains the anomaly.
        compared_take_id: The take (or the same take) frame_b was drawn from.
        frame_number_a: Frame number of the first (reference) frame.
        frame_number_b: Frame number of the second (anomalous) frame.
        timecode_a: SMPTE timecode of frame_number_a.
        timecode_b: SMPTE timecode of frame_number_b.
        anomaly_type: One of prop_mismatch, wardrobe_mismatch,
            position_mismatch, lighting_mismatch, continuity_other.
        description: A specific, screen-legible description of the
            mismatch, e.g. "Wine glass is full in frame A, half-empty in
            frame B with no drinking action between them."
        severity: One of low, medium, high, critical.
        confidence_score: Your confidence in this finding, 0.0-1.0.

    Returns:
        A dict confirming the anomaly was recorded, including its id.
    """
    try:
        anomaly = ContinuityAnomaly(
            scene_id=scene_id,
            take_id=take_id,
            compared_take_id=compared_take_id,
            frame_number_a=frame_number_a,
            frame_number_b=frame_number_b,
            timecode_a=timecode_a,
            timecode_b=timecode_b,
            anomaly_type=AnomalyType(anomaly_type),
            description=description,
            severity=Severity(severity),
            detected_by_agent="continuity_anomaly_agent",
            confidence_score=confidence_score,
        )
    except (ValidationError, ValueError) as exc:
        logger.warning("Rejected malformed anomaly from agent: %s", exc)
        return {"status": "rejected", "reason": str(exc)}

    insert_rows(
        "continuity_anomalies",
        ANOMALY_COLUMNS,
        [[
            anomaly.scene_id, anomaly.take_id, anomaly.compared_take_id,
            anomaly.frame_number_a, anomaly.frame_number_b,
            anomaly.timecode_a, anomaly.timecode_b,
            anomaly.anomaly_type.value, anomaly.description, anomaly.severity.value,
            anomaly.detected_by_agent, anomaly.confidence_score,
        ]],
    )
    logger.info(
        "Flagged %s anomaly (%s) in %s/%s @ %s vs %s",
        anomaly.severity.value, anomaly.anomaly_type.value,
        scene_id, take_id, timecode_a, timecode_b,
    )
    anomalies_flagged_total.labels(severity=anomaly.severity.value).inc()
    return {"status": "recorded", "scene_id": scene_id, "take_id": take_id, "severity": severity}
