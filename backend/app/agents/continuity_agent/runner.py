"""
Executes one continuity-check pass for a given scene/take and persists a
step-by-step trace to ClickHouse's agent_execution_log, which is what the
frontend's "Agent Trace" panel renders.

Uses ADK's own Runner + InMemorySessionService to drive the ReAct loop;
this module's only job is turning the resulting Event stream into rows.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.continuity_agent.agent import AGENT_NAME, get_continuity_agent
from app.db.clickhouse_client import insert_rows

logger = logging.getLogger("continuity_agent.agent_runner")

APP_NAME = "continuity_agent"

LOG_COLUMNS = [
    "execution_id", "agent_name", "scene_id", "take_id", "step_number",
    "step_type", "tool_name", "input_payload", "output_payload",
    "latency_ms", "started_at",
]


def _log_row(
    execution_id: UUID, scene_id: str, take_id: str, step_number: int,
    step_type: str, tool_name: str, input_payload: object, output_payload: object,
    latency_ms: int,
) -> list:
    return [
        str(execution_id), AGENT_NAME, scene_id, take_id, step_number, step_type,
        tool_name,
        json.dumps(input_payload, default=str) if input_payload is not None else "",
        json.dumps(output_payload, default=str) if output_payload is not None else "",
        latency_ms,
        datetime.now(timezone.utc),
    ]


async def run_continuity_check(
    scene_id: str,
    take_id: str,
    compare_against_take_id: str | None = None,
    execution_id: UUID | None = None,
) -> dict:
    """
    Run the continuity agent once and return a summary dict:
    {execution_id, final_report, step_count, anomalies_flagged}

    Pass `execution_id` explicitly when the caller needs to know the id
    before the run finishes (e.g. an API returning 202 Accepted while the
    agent runs in a background task -- see routers/agent.py).
    """
    execution_id = execution_id or uuid4()
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=APP_NAME, user_id="system", session_id=str(execution_id),
    )
    runner = Runner(agent=get_continuity_agent(), app_name=APP_NAME, session_service=session_service)

    task_description = (
        f"Review scene '{scene_id}', take '{take_id}' for continuity anomalies"
        + (f", comparing against take '{compare_against_take_id}'." if compare_against_take_id
           else ", comparing against the most recent prior take you can find for this scene.")
    )
    user_message = types.Content(role="user", parts=[types.Part.from_text(text=task_description)])

    # Write a row before the first model event. Without this, a startup
    # failure left the polling endpoint with no execution to return, causing
    # the dashboard to report repeated 404s instead of the actual failure.
    step_number = 1
    rows: list[list] = [
        _log_row(
            execution_id, scene_id, take_id, step_number, "started", "",
            {"status": "started"}, None, 0,
        )
    ]
    anomalies_flagged = 0
    final_report = ""
    step_started = time.monotonic()

    try:
        async for event in runner.run_async(
            user_id="system", session_id=session.id, new_message=user_message,
        ):
            latency_ms = int((time.monotonic() - step_started) * 1000)
            step_started = time.monotonic()

            function_calls = event.get_function_calls()
            function_responses = event.get_function_responses()

            if function_calls:
                for call in function_calls:
                    step_number += 1
                    rows.append(_log_row(
                        execution_id, scene_id, take_id, step_number, "tool_call",
                        call.name, call.args, None, latency_ms,
                    ))
            if function_responses:
                for fresponse in function_responses:
                    step_number += 1
                    is_anomaly_write = fresponse.name == "flag_continuity_anomaly"
                    if is_anomaly_write and isinstance(fresponse.response, dict) and \
                            fresponse.response.get("status") == "recorded":
                        anomalies_flagged += 1
                    rows.append(_log_row(
                        execution_id, scene_id, take_id, step_number,
                        "anomaly_flagged" if is_anomaly_write else "tool_result",
                        fresponse.name, None, fresponse.response, latency_ms,
                    ))
            if event.content and event.content.parts:
                text_parts = [p.text for p in event.content.parts if getattr(p, "text", None)]
                if text_parts:
                    step_number += 1
                    combined_text = "\n".join(text_parts)
                    is_final = event.is_final_response()
                    if is_final:
                        final_report = combined_text
                    rows.append(_log_row(
                        execution_id, scene_id, take_id, step_number,
                        "final_report" if is_final else "reasoning",
                        "", None, combined_text, latency_ms,
                    ))
            if event.error_message:
                step_number += 1
                rows.append(_log_row(
                    execution_id, scene_id, take_id, step_number, "error",
                    "", None, {"error_code": event.error_code, "message": event.error_message},
                    latency_ms,
                ))
    except Exception as exc:
        step_number += 1
        rows.append(_log_row(
            execution_id, scene_id, take_id, step_number, "error", "",
            None, {"message": str(exc)}, int((time.monotonic() - step_started) * 1000),
        ))
        logger.exception("Continuity check %s failed", execution_id)
        raise
    finally:
        if rows:
            insert_rows("agent_execution_log", LOG_COLUMNS, rows)

    logger.info(
        "Continuity check %s complete for %s/%s: %d step(s), %d anomaly(ies)",
        execution_id, scene_id, take_id, step_number, anomalies_flagged,
    )
    return {
        "execution_id": str(execution_id),
        "final_report": final_report,
        "step_count": step_number,
        "anomalies_flagged": anomalies_flagged,
    }
