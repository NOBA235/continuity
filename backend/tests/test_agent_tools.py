from app.agents.continuity_agent import tools


def test_flag_continuity_anomaly_writes_validated_row(mocker):
    mock_insert = mocker.patch("app.agents.continuity_agent.tools.insert_rows", return_value=1)

    result = tools.flag_continuity_anomaly(
        scene_id="14A",
        take_id="003",
        compared_take_id="002",
        frame_number_a=10,
        frame_number_b=42,
        timecode_a="00:00:10:00",
        timecode_b="00:00:42:00",
        anomaly_type="prop_mismatch",
        description="Wine glass full in take 2, empty in take 3 with no drinking action.",
        severity="high",
        confidence_score=0.81,
    )

    assert result["status"] == "recorded"
    mock_insert.assert_called_once()
    table_name, columns, rows = mock_insert.call_args[0]
    assert table_name == "continuity_anomalies"
    assert columns == tools.ANOMALY_COLUMNS
    assert rows[0][columns.index("anomaly_type")] == "prop_mismatch"
    assert rows[0][columns.index("severity")] == "high"


def test_flag_continuity_anomaly_rejects_invalid_enum(mocker):
    mock_insert = mocker.patch("app.agents.continuity_agent.tools.insert_rows")

    result = tools.flag_continuity_anomaly(
        scene_id="14A",
        take_id="003",
        compared_take_id="002",
        frame_number_a=10,
        frame_number_b=42,
        timecode_a="00:00:10:00",
        timecode_b="00:00:42:00",
        anomaly_type="not_a_real_type",
        description="x",
        severity="high",
        confidence_score=0.81,
    )

    assert result["status"] == "rejected"
    mock_insert.assert_not_called()


def test_flag_continuity_anomaly_rejects_out_of_range_confidence(mocker):
    mock_insert = mocker.patch("app.agents.continuity_agent.tools.insert_rows")

    result = tools.flag_continuity_anomaly(
        scene_id="14A",
        take_id="003",
        compared_take_id="002",
        frame_number_a=10,
        frame_number_b=42,
        timecode_a="00:00:10:00",
        timecode_b="00:00:42:00",
        anomaly_type="prop_mismatch",
        description="x",
        severity="high",
        confidence_score=5.0,
    )

    assert result["status"] == "rejected"
    mock_insert.assert_not_called()
