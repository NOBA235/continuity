from pathlib import Path

from google.genai import errors

from app.models.schemas import FrameDescriptor, PropState
from app.services import gemini_vision


def _sample_descriptor() -> FrameDescriptor:
    return FrameDescriptor(
        wardrobe_description="Grey trench coat, top button open.",
        prop_list=["coffee mug"],
        prop_states=[PropState(prop="coffee_mug_fill_level", state="80%")],
        actor_positions=[],
        lighting_description="Soft key camera-left.",
        lighting_vector=[0.6, 0.3, 3.2, 45.0],
        confidence_score=0.9,
    )


def test_analyze_frame_returns_parsed_descriptor(tmp_path, mocker):
    image_path: Path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpegbytes")

    mock_response = mocker.Mock()
    mock_response.parsed = _sample_descriptor()

    mock_client = mocker.Mock()
    mock_client.models.generate_content.return_value = mock_response
    mocker.patch.object(gemini_vision, "_get_client", return_value=mock_client)
    gemini_vision._get_client.cache_clear() if hasattr(gemini_vision._get_client, "cache_clear") else None

    descriptor = gemini_vision.analyze_frame(image_path, scene_context="Scene 1, Take 1")

    assert descriptor.confidence_score == 0.9
    assert "coffee mug" in descriptor.prop_list
    mock_client.models.generate_content.assert_called_once()
    _, kwargs = mock_client.models.generate_content.call_args
    assert kwargs["config"].response_schema is FrameDescriptor


def test_analyze_frame_falls_back_to_manual_parse_when_sdk_parse_is_none(tmp_path, mocker):
    image_path: Path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpegbytes")

    mock_response = mocker.Mock()
    mock_response.parsed = None
    mock_response.text = _sample_descriptor().model_dump_json()

    mock_client = mocker.Mock()
    mock_client.models.generate_content.return_value = mock_response
    mocker.patch.object(gemini_vision, "_get_client", return_value=mock_client)

    descriptor = gemini_vision.analyze_frame(image_path)
    assert descriptor.wardrobe_description == "Grey trench coat, top button open."


def test_analyze_frame_retries_on_retryable_api_error(tmp_path, mocker):
    image_path: Path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpegbytes")

    mocker.patch("time.sleep", return_value=None)  # skip real backoff during test

    rate_limit_error = errors.APIError(429, {"error": {"message": "rate limited"}})
    mock_response = mocker.Mock()
    mock_response.parsed = _sample_descriptor()

    mock_client = mocker.Mock()
    mock_client.models.generate_content.side_effect = [rate_limit_error, mock_response]
    mocker.patch.object(gemini_vision, "_get_client", return_value=mock_client)

    descriptor = gemini_vision.analyze_frame(image_path)
    assert descriptor.confidence_score == 0.9
    assert mock_client.models.generate_content.call_count == 2


def test_analyze_frame_does_not_retry_non_retryable_error(tmp_path, mocker):
    """A 400 (bad request -- e.g. malformed prompt) should fail immediately;
    retrying it would just waste quota re-sending the same bad request."""
    image_path: Path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpegbytes")

    bad_request_error = errors.APIError(400, {"error": {"message": "invalid argument"}})
    mock_client = mocker.Mock()
    mock_client.models.generate_content.side_effect = bad_request_error
    mocker.patch.object(gemini_vision, "_get_client", return_value=mock_client)

    try:
        gemini_vision.analyze_frame(image_path)
        assert False, "expected APIError to propagate"
    except errors.APIError:
        pass

    assert mock_client.models.generate_content.call_count == 1
