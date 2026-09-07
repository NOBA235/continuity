from app.services.video_processor import _get_frame_rate, _seconds_to_smpte


def test_seconds_to_smpte_zero():
    assert _seconds_to_smpte(0.0, 24.0) == "00:00:00:00"


def test_seconds_to_smpte_one_second_at_24fps():
    assert _seconds_to_smpte(1.0, 24.0) == "00:00:01:00"


def test_seconds_to_smpte_rolls_over_minutes():
    # 61.5s at 24fps -> 1 min, 1 sec, 12 frames
    assert _seconds_to_smpte(61.5, 24.0) == "00:01:01:12"


def test_seconds_to_smpte_rolls_over_hours():
    assert _seconds_to_smpte(3661.0, 25.0) == "01:01:01:00"


def test_get_frame_rate_parses_fraction():
    probe = {"streams": [{"codec_type": "video", "avg_frame_rate": "24000/1001"}]}
    fps = _get_frame_rate(probe)
    assert round(fps, 3) == round(24000 / 1001, 3)


def test_get_frame_rate_defaults_when_missing():
    probe = {"streams": [{"codec_type": "video", "avg_frame_rate": "0/0"}]}
    fps = _get_frame_rate(probe)
    assert fps == 25.0


def test_get_frame_rate_raises_without_video_stream():
    import pytest

    from app.services.video_processor import VideoProcessingError

    with pytest.raises(VideoProcessingError):
        _get_frame_rate({"streams": [{"codec_type": "audio"}]})
