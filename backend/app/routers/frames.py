from __future__ import annotations

from app.auth.dependencies import get_current_user
from app.db.clickhouse_client import query
from app.models.schemas import FrameMetadataRecord
from fastapi import APIRouter, Depends, Query

router = APIRouter(prefix="/api/frames", tags=["frames"], dependencies=[Depends(get_current_user)])


@router.get("/scenes", response_model=list[str])
def list_scenes() -> list[str]:
    rows = query(
        "SELECT scene_id FROM frame_metadata "
        "UNION DISTINCT SELECT scene_id FROM ingestion_jobs "
        "ORDER BY scene_id"
    )
    return [r["scene_id"] for r in rows]


@router.get("/scenes/{scene_id}/takes", response_model=list[str])
def list_takes(scene_id: str) -> list[str]:
    rows = query(
        "SELECT take_id FROM frame_metadata WHERE scene_id = {scene_id:String} "
        "UNION DISTINCT "
        "SELECT take_id FROM ingestion_jobs WHERE scene_id = {scene_id:String} "
        "ORDER BY take_id",
        {"scene_id": scene_id},
    )
    return [r["take_id"] for r in rows]


@router.get("", response_model=list[FrameMetadataRecord])
def list_frames(
    scene_id: str,
    take_id: str,
    limit: int = Query(2000, le=20000),
    offset: int = 0,
) -> list[FrameMetadataRecord]:
    """
    Frame metadata for one take, ordered by frame_number. `embedding` is
    intentionally excluded from the response payload (it's large and the
    frontend never needs it -- similarity search happens server-side in
    the agent, in ClickHouse).
    """
    rows = query(
        """
        SELECT scene_id, take_id, video_id, timecode, frame_number, timestamp,
               actor_id, wardrobe_description, prop_list, prop_states,
               lighting_vector, confidence_score, gemini_model
        FROM frame_metadata
        WHERE scene_id = {scene_id:String} AND take_id = {take_id:String}
        ORDER BY frame_number
        LIMIT {limit:UInt32} OFFSET {offset:UInt32}
        """,
        {"scene_id": scene_id, "take_id": take_id, "limit": limit, "offset": offset},
    )
    return [FrameMetadataRecord.model_validate(r) for r in rows]
