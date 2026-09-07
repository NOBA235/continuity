from datetime import timedelta
from pathlib import Path

import pytest

from app.services.object_storage import GcsStorageBackend, LocalStorageBackend


class _FakeSettings:
    def __init__(self, upload_dir: Path, gcs_bucket_name: str | None = None):
        self.upload_dir = upload_dir
        self.gcs_bucket_name = gcs_bucket_name


# --- LocalStorageBackend --------------------------------------------------
def test_local_backend_save_upload_is_noop_when_already_in_place(tmp_path):
    backend = LocalStorageBackend(_FakeSettings(upload_dir=tmp_path))
    storage_key = "job-1/dailies.mp4"
    staged = tmp_path / storage_key
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"video-bytes")

    backend.save_upload(storage_key, staged)  # should not raise, not duplicate

    assert backend.exists(storage_key)
    assert (tmp_path / storage_key).read_bytes() == b"video-bytes"


def test_local_backend_save_upload_copies_when_source_elsewhere(tmp_path):
    backend = LocalStorageBackend(_FakeSettings(upload_dir=tmp_path / "canonical"))
    source = tmp_path / "staging" / "clip.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"clip-bytes")

    backend.save_upload("job-2/clip.mp4", source)

    assert (tmp_path / "canonical" / "job-2" / "clip.mp4").read_bytes() == b"clip-bytes"


def test_local_backend_download_to_local_returns_existing_path(tmp_path):
    backend = LocalStorageBackend(_FakeSettings(upload_dir=tmp_path))
    storage_key = "job-3/take.mp4"
    (tmp_path / "job-3").mkdir()
    (tmp_path / storage_key).write_bytes(b"x")

    resolved = backend.download_to_local(storage_key, tmp_path / "scratch")
    assert resolved == tmp_path / storage_key


def test_local_backend_download_to_local_raises_for_missing_file(tmp_path):
    backend = LocalStorageBackend(_FakeSettings(upload_dir=tmp_path))
    with pytest.raises(FileNotFoundError):
        backend.download_to_local("nope/missing.mp4", tmp_path / "scratch")


def test_local_backend_has_no_signed_url(tmp_path):
    backend = LocalStorageBackend(_FakeSettings(upload_dir=tmp_path))
    assert backend.get_signed_playback_url("anything", 60) is None


def test_local_backend_delete_removes_file(tmp_path):
    backend = LocalStorageBackend(_FakeSettings(upload_dir=tmp_path))
    (tmp_path / "job-4").mkdir()
    (tmp_path / "job-4" / "f.mp4").write_bytes(b"x")

    backend.delete("job-4/f.mp4")
    assert not backend.exists("job-4/f.mp4")

    backend.delete("job-4/does-not-exist.mp4")  # must not raise


# --- GcsStorageBackend (google-cloud-storage client mocked) --------------
def test_gcs_backend_requires_bucket_name():
    with pytest.raises(ValueError, match="GCS_BUCKET_NAME"):
        GcsStorageBackend(_FakeSettings(upload_dir=Path("/tmp"), gcs_bucket_name=None))


def test_gcs_backend_save_upload_calls_blob_upload(mocker, tmp_path):
    mock_client_cls = mocker.patch("google.cloud.storage.Client")
    mock_bucket = mock_client_cls.return_value.bucket.return_value
    mock_blob = mock_bucket.blob.return_value

    backend = GcsStorageBackend(_FakeSettings(upload_dir=tmp_path, gcs_bucket_name="my-bucket"))
    local_file = tmp_path / "dailies.mp4"
    local_file.write_bytes(b"x")

    backend.save_upload("videos/job-1/dailies.mp4", local_file)

    mock_bucket.blob.assert_called_with("videos/job-1/dailies.mp4")
    mock_blob.upload_from_filename.assert_called_once_with(str(local_file))


def test_gcs_backend_download_to_local_calls_blob_download(mocker, tmp_path):
    mock_client_cls = mocker.patch("google.cloud.storage.Client")
    mock_bucket = mock_client_cls.return_value.bucket.return_value
    mock_blob = mock_bucket.blob.return_value

    backend = GcsStorageBackend(_FakeSettings(upload_dir=tmp_path, gcs_bucket_name="my-bucket"))
    dest_dir = tmp_path / "scratch"

    resolved = backend.download_to_local("videos/job-1/dailies.mp4", dest_dir)

    assert resolved == dest_dir / "dailies.mp4"
    mock_blob.download_to_filename.assert_called_once_with(str(dest_dir / "dailies.mp4"))


def test_gcs_backend_generates_v4_signed_url_with_expiration(mocker, tmp_path):
    mock_client_cls = mocker.patch("google.cloud.storage.Client")
    mock_bucket = mock_client_cls.return_value.bucket.return_value
    mock_blob = mock_bucket.blob.return_value
    mock_blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed-url"

    backend = GcsStorageBackend(_FakeSettings(upload_dir=tmp_path, gcs_bucket_name="my-bucket"))
    url = backend.get_signed_playback_url("videos/job-1/dailies.mp4", expiration_minutes=45)

    assert url == "https://storage.googleapis.com/signed-url"
    _, kwargs = mock_blob.generate_signed_url.call_args
    assert kwargs["version"] == "v4"
    assert kwargs["method"] == "GET"
    assert kwargs["expiration"] == timedelta(minutes=45)


def test_gcs_backend_delete_only_calls_delete_when_blob_exists(mocker, tmp_path):
    mock_client_cls = mocker.patch("google.cloud.storage.Client")
    mock_bucket = mock_client_cls.return_value.bucket.return_value
    mock_blob = mock_bucket.blob.return_value
    mock_blob.exists.return_value = False

    backend = GcsStorageBackend(_FakeSettings(upload_dir=tmp_path, gcs_bucket_name="my-bucket"))
    backend.delete("videos/job-1/dailies.mp4")

    mock_blob.delete.assert_not_called()
