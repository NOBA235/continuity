from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_user, require_editor_or_supervisor
from app.db.clickhouse_client import command, query
from app.models.schemas import ContinuityAnomaly, CurrentUser, Severity

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[ContinuityAnomaly])
def list_anomalies(
    scene_id: str | None = None,
    take_id: str | None = None,
    resolved: bool | None = None,
    min_severity: Severity | None = None,
    limit: int = Query(500, le=5000),
) -> list[ContinuityAnomaly]:
    clauses: list[str] = []
    params: dict[str, object] = {"limit": limit}

    if scene_id:
        clauses.append("scene_id = {scene_id:String}")
        params["scene_id"] = scene_id
    if take_id:
        clauses.append("take_id = {take_id:String}")
        params["take_id"] = take_id
    if resolved is not None:
        clauses.append("resolved = {resolved:UInt8}")
        params["resolved"] = int(resolved)
    if min_severity:
        # Enum8 ordinal comparison: low=1 ... critical=4, matches schema.sql order.
        clauses.append("CAST(severity, 'Int8') >= CAST({min_severity:String}, 'Enum8("
                        "\\'low\\'=1,\\'medium\\'=2,\\'high\\'=3,\\'critical\\'=4)', 'Int8')")
        params["min_severity"] = min_severity.value

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = query(
        f"""
        SELECT anomaly_id, scene_id, take_id, compared_take_id, frame_number_a,
               frame_number_b, timecode_a, timecode_b, anomaly_type, description,
               severity, detected_by_agent, confidence_score, resolved,
               resolved_note, detected_at
        FROM continuity_anomalies
        {where_sql}
        ORDER BY detected_at DESC
        LIMIT {{limit:UInt32}}
        """,
        params,
    )
    return [ContinuityAnomaly.model_validate(r) for r in rows]


class ResolveAnomalyRequest(BaseModel):
    resolved_note: str = ""


@router.post("/{anomaly_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
def resolve_anomaly(
    anomaly_id: UUID,
    body: ResolveAnomalyRequest,
    current_user: CurrentUser = Depends(require_editor_or_supervisor),
) -> None:
    """
    Mark an anomaly resolved via a ClickHouse lightweight UPDATE mutation.
    Mutations are async in ClickHouse (the row updates in the background),
    which is standard and expected for MergeTree tables. Restricted to
    editor/supervisor accounts -- viewers can see the log but not clear it.
    """
    existing = query(
        "SELECT anomaly_id FROM continuity_anomalies WHERE anomaly_id = {id:UUID} LIMIT 1",
        {"id": str(anomaly_id)},
    )
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No anomaly found with id {anomaly_id}")

    note = f"{body.resolved_note} (resolved by {current_user.email})".strip()
    command(
        "ALTER TABLE continuity_anomalies UPDATE resolved = 1, resolved_note = "
        "{note:String} WHERE anomaly_id = {id:UUID}",
        {"note": note, "id": str(anomaly_id)},
    )
