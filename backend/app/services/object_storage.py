"""
Where uploaded dailies actually live, abstracted behind one interface so
the rest of the app (ingestion pipeline, video-streaming endpoint) doesn't
care whether it's talking to local disk or Google Cloud Storage.

Local disk is fine for a single backend instance or local dev -- it's
what docker-compose.yml uses. It does not survive horizontal scaling
(a second backend replica can't see the first one's uploads) or backend
redeploys on most container platforms (ephemeral filesystem). Set
STORAGE_BACKEND=gcs for anything beyond a single long-lived instance.
"""
from __future__ import annotations

import logging
import shutil
from abc import ABC, abstractmethod
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from app.config import Settings, get_settings

logger = logging.getLogger("continuity_agent.object_storage")


class StorageBackend(ABC):
    @abstractmethod
    def save_upload(self, storage_key: str, local_source_path: Path) -> None:
        """Persist the file at `local_source_path` as the canonical, durable
        copy referenced by `storage_key`."""

    @abstractmethod
    def download_to_local(self, storage_key: str, destination_dir: Path) -> Path:
        """Ensure a local, seekable copy exists on disk (ffmpeg needs one
        regardless of backend) and return its path."""

    @abstractmethod
    def get_signed_playback_url(self, storage_key: str, expiration_minutes: int) -> str | None:
        """A URL the browser can fetch/Range-request directly, bypassing our
        backend for the actual video bytes. Returns None if the backend has
        no such thing (local disk), in which case the caller should proxy-
        stream the bytes itself instead."""

    @abstractmethod
    def exists(self, storage_key: str) -> bool: ...

    @abstractmethod
    def delete(self, storage_key: str) -> None: ...


class LocalStorageBackend(StorageBackend):
    """`upload_dir` IS the canonical store -- save_upload is a no-op when the
    source is already there (the common case: the upload endpoint stages
    directly into upload_dir), and a copy otherwise."""

    def __init__(self, settings: Settings):
        self._root = settings.upload_dir

    def _path_for(self, storage_key: str) -> Path:
        return self._root / storage_key

    def save_upload(self, storage_key: str, local_source_path: Path) -> None:
        destination = self._path_for(storage_key)
        if destination.resolve() == local_source_path.resolve():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_source_path, destination)

    def download_to_local(self, storage_key: str, destination_dir: Path) -> Path:
        path = self._path_for(storage_key)
        if not path.is_file():
            raise FileNotFoundError(f"No local file for storage key '{storage_key}'")
        return path

    def get_signed_playback_url(self, storage_key: str, expiration_minutes: int) -> str | None:
        return None  # caller proxy-streams from disk instead -- see routers/ingestion.py

    def exists(self, storage_key: str) -> bool:
        return self._path_for(storage_key).is_file()

    def delete(self, storage_key: str) -> None:
        self._path_for(storage_key).unlink(missing_ok=True)


class GcsStorageBackend(StorageBackend):
    """Google Cloud Storage, via the official `google-cloud-storage` SDK.
    Credentials come from the standard GCP auth chain (GOOGLE_APPLICATION_
    CREDENTIALS, workload identity on Cloud Run/GKE, etc.) -- never handled
    or stored by this app directly.
    """

    def __init__(self, settings: Settings):
        # Imported lazily so environments running with STORAGE_BACKEND=local
        # never need google-cloud-storage's transitive deps importable.
        from google.cloud import storage as gcs

        if not settings.gcs_bucket_name:
            raise ValueError("GCS_BUCKET_NAME must be set when STORAGE_BACKEND=gcs")
        self._client = gcs.Client()
        self._bucket = self._client.bucket(settings.gcs_bucket_name)

    def save_upload(self, storage_key: str, local_source_path: Path) -> None:
        blob = self._bucket.blob(storage_key)
        blob.upload_from_filename(str(local_source_path))
        logger.info("Uploaded %s to gs://%s/%s", local_source_path.name, self._bucket.name, storage_key)

    def download_to_local(self, storage_key: str, destination_dir: Path) -> Path:
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / Path(storage_key).name
        blob = self._bucket.blob(storage_key)
        blob.download_to_filename(str(destination))
        return destination

    def get_signed_playback_url(self, storage_key: str, expiration_minutes: int) -> str | None:
        blob = self._bucket.blob(storage_key)
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiration_minutes),
            method="GET",
        )

    def exists(self, storage_key: str) -> bool:
        return self._bucket.blob(storage_key).exists()

    def delete(self, storage_key: str) -> None:
        blob = self._bucket.blob(storage_key)
        if blob.exists():
            blob.delete()


@lru_cache
def get_storage_backend() -> StorageBackend:
    settings = get_settings()
    if settings.storage_backend == "gcs":
        return GcsStorageBackend(settings)
    return LocalStorageBackend(settings)
