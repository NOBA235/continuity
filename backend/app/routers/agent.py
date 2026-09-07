from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.agents.continuity_agent.runner import run_continuity_check
from app.auth.dependencies import get_current_user, require_editor_or_supervisor
from app.db.clickhouse_client import query
from app.models.schemas import AgentExecutionStep, AgentRunRequest, CurrentUser

logger = logging.getLogger("continuity_agent.routers.agent")
router = APIRouter(prefix="/api/agent", tags=["agent"], dependencies=[Depends(get_current_user)])


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def trigger_continuity_check(
    body: AgentRunRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_editor_or_supervisor),
) -> dict:
    """
    Kick off a continuity check as a background task and return immediately
    with an execution_id. Poll GET /api/agent/executions/{execution_id} (or
    the frontend's Agent Trace panel) to watch steps arrive as the agent runs
    -- each tool call/result is written to ClickHouse as it happens, not
    only once the whole run finishes. Restricted to editor/supervisor
    accounts -- running the agent costs real Gemini API spend per call.
    """
    logger.info(
        "Continuity check requested for %s/%s by %s",
        body.scene_id, body.take_id, current_user.email,
    )
    execution_id = uuid4()
    background_tasks.add_task(
        _run_in_background, body.scene_id, body.take_id, body.compare_against_take_id, execution_id,
    )
    return {"execution_id": str(execution_id), "status": "started"}


def _run_in_background(
    scene_id: str, take_id: str, compare_against_take_id: str | None, execution_id: UUID,
) -> None:
    try:
        asyncio.run(
            run_continuity_check(
                scene_id=scene_id,
                take_id=take_id,
                compare_against_take_id=compare_against_take_id,
                execution_id=execution_id,
            )
        )
    except Exception:  # noqa: BLE001 -- partial trace is still in ClickHouse for inspection
        logger.exception("Continuity check %s failed", execution_id)


@router.get("/executions/{execution_id}", response_model=list[AgentExecutionStep])
def get_execution_trace(execution_id: UUID) -> list[AgentExecutionStep]:
    rows = query(
        "SELECT * FROM agent_execution_log WHERE execution_id = {id:UUID} ORDER BY step_number",
        {"id": str(execution_id)},
    )
    if not rows:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No execution found with id {execution_id} (it may not have started yet)",
        )
    return [AgentExecutionStep.model_validate(r) for r in rows]


@router.get("/executions", response_model=list[str])
def list_recent_executions(scene_id: str, take_id: str, limit: int = 10) -> list[str]:
    rows = query(
        "SELECT DISTINCT execution_id FROM agent_execution_log "
        "WHERE scene_id = {scene_id:String} AND take_id = {take_id:String} "
        "ORDER BY execution_id DESC LIMIT {limit:UInt32}",
        {"scene_id": scene_id, "take_id": take_id, "limit": limit},
    )
    return [str(r["execution_id"]) for r in rows]
