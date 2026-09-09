import pytest
from pydantic import ValidationError

from app.models.schemas import (
    AnomalyType,
    ContinuityAnomaly,
    FrameDescriptor,
    PropState,
    Severity,
)


def test_frame_descriptor_accepts_well_formed_payload():
    descriptor = FrameDescriptor(
        wardrobe_description="Detective wears a grey trench coat, top button open.",
        prop_list=["coffee mug", "revolver"],
        prop_states=[PropState(prop="coffee_mug_fill_level", state="80%")],
        actor_positions=[],
        lighting_description="Soft key from camera-left, dim practicals in background.",
        lighting_vector=[0.6, 0.3, 3.2, 45.0],
        confidence_score=0.92,
    )
    assert descriptor.confidence_score == 0.92
    assert "revolver" in descriptor.prop_list


def test_frame_descriptor_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        FrameDescriptor(
            wardrobe_description="x",
            prop_list=[],
            lighting_description="x",
            lighting_vector=[0.1, 0.1, 3.0, 0.0],
            confidence_score=1.5,  # out of [0,1]
        )


def test_continuity_anomaly_requires_valid_enum_values():
    anomaly = ContinuityAnomaly(
        scene_id="14A",
        take_id="003",
        compared_take_id="002",
        frame_number_a=10,
        frame_number_b=42,
        timecode_a="00:00:10:00",
        timecode_b="00:00:42:00",
        anomaly_type=AnomalyType.prop_mismatch,
        description="Wine glass full in take 2, empty in take 3 with no drinking action.",
        severity=Severity.high,
        detected_by_agent="continuity_anomaly_agent",
        confidence_score=0.81,
    )
    assert anomaly.severity is Severity.high

    with pytest.raises(ValidationError):
        ContinuityAnomaly(
            scene_id="14A",
            take_id="003",
            compared_take_id="002",
            frame_number_a=10,
            frame_number_b=42,
            timecode_a="00:00:10:00",
            timecode_b="00:00:42:00",
            anomaly_type="not_a_real_type",  # invalid
            description="x",
            severity=Severity.high,
            detected_by_agent="continuity_anomaly_agent",
            confidence_score=0.81,
        )
