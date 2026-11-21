"""Image storage behind a small interface (ADR-009). Two backends, chosen by STORAGE_BACKEND:
"local" (below) and "r2" (Cloudflare R2, app.integrations.media.r2).

MediaStorage is what the services use: put, get, exists, delete, public_url and list, each with a
visibility ("private" or "public"). The R2 backend keeps one bucket per visibility and implements
the same methods; no service or endpoint changes. Every stored file is tracked in media_objects
(app.models.media); this module only moves bytes.

Local layout under MEDIA_ROOT:
- private/  exact uploaded originals and incoming bulk uploads. Never served over HTTP.
- public/   the sanitised public source of every image, served at IMAGE_PUBLIC_BASE_URL (the API
            itself serves it at /media in development).

Keys are generated here, never taken from a client:
- images: "<owner>/<owner id>/<32 hex>-<12 hex>.<ext>", owner products, categories, brands,
  banners, services or stores (ADR-014 phase 2 logo and cover); the 12 hex characters are the
  start of the SHA-256 of the original upload. A new image always gets a new key, so a URL never
  changes content and needs no cache purge.
- incoming bulk uploads (private only): "incoming/<job id>/<item id>".
Every path is checked against these patterns and confined to its folder, so a stored key can
never reach outside it. Writes go to a temporary file in the same folder and are renamed into
place, so a reader never sees a partial file. Files are never overwritten.
"""

import hashlib
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Literal, Protocol
from urllib.parse import quote

from starlette.staticfiles import StaticFiles

from app.core.config import get_settings

Visibility = Literal["public", "private"]
Owner = Literal["products", "categories", "brands", "banners", "services", "stores"]

UUID_TEXT = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
KEY_PATTERN = re.compile(
    rf"^(?:products|categories|brands|banners|services|stores)/{UUID_TEXT}/"
    rf"[0-9a-f]{{32}}-[0-9a-f]{{12}}"
    r"\.(?:jpg|png|webp)$"
)
INCOMING_KEY_PATTERN = re.compile(rf"^incoming/{UUID_TEXT}/{UUID_TEXT}$")
CONTENT_HASH_LENGTH = 12
COPY_CHUNK_BYTES = 1024 * 1024
# Public keys are immutable (a new image gets a new key), so they may be cached forever.
PUBLIC_CACHE_CONTROL = "public, max-age=31536000, immutable"


class StorageError(Exception):
    """A storage operation failed; the message never contains file contents."""


def new_key(owner: Owner, owner_id: uuid.UUID, extension: str, original: bytes) -> str:
    """A fresh key for one image of `owner_id`; random, so a replacement never reuses a key."""
    digest = hashlib.sha256(original).hexdigest()[:CONTENT_HASH_LENGTH]
    return f"{owner}/{owner_id}/{uuid.uuid4().hex}-{digest}.{extension}"


def incoming_key(job_id: uuid.UUID, item_id: uuid.UUID) -> str:
    return f"incoming/{job_id}/{item_id}"


class MediaStorage(Protocol):
    def put(
        self,
        key: str,
        data: bytes | BinaryIO,
        *,
        visibility: Visibility,
        content_type: str,
        cache_control: str | None = None,
    ) -> None:
        """Store data (bytes, or a binary stream copied in chunks) under a new key. Raises
        StorageError on failure, or if the key already exists; nothing partial is left."""
        ...

    def get(self, key: str, *, visibility: Visibility) -> bytes:
        """The stored bytes. Raises StorageError if missing or unreadable."""
        ...

    def exists(self, key: str, *, visibility: Visibility) -> bool: ...

    def delete(self, key: str, *, visibility: Visibility) -> None:
        """Remove a stored file. A missing file is success; raises StorageError on failure."""
        ...

    def public_url(self, key: str) -> str:
        """Public URL of a public key: IMAGE_PUBLIC_BASE_URL + "/" + key."""
        ...

    def list(self, prefix: str, *, visibility: Visibility) -> Iterator[str]:
        """Every stored key starting with prefix ("" for all)."""
        ...

    def free_bytes(self) -> int | None:
        """Free space where files are written, or None when the backend has no such limit."""
        ...


class LocalMediaStorage:
    """Local disk under MEDIA_ROOT (development; STORAGE_BACKEND=local)."""

    def __init__(self, root: Path, public_base_url: str) -> None:
        self.root = root.resolve()
        self.public_root = self.root / "public"
        self.private_root = self.root / "private"
        self.public_base_url = public_base_url.rstrip("/")

    def _folder(self, visibility: Visibility) -> Path:
        return self.public_root if visibility == "public" else self.private_root

    def path(self, key: str, visibility: Visibility) -> Path:
        """The file for a managed key; ValueError for anything else."""
        managed = KEY_PATTERN.fullmatch(key) or (
            visibility == "private" and INCOMING_KEY_PATTERN.fullmatch(key)
        )
        if not managed:
            raise ValueError("not a media key")
        folder = self._folder(visibility)
        # Lexical containment only: the key patterns allow no "." segments, backslashes or
        # absolute paths, so the joined path stays in its folder. Path.resolve() is not used: on
        # Windows it can return a differently normalised path while another process is creating
        # the same directory, which made concurrent uploads fail (2026-10-26).
        path = Path(os.path.normpath(folder / key))
        if os.path.commonpath([path, folder]) != os.path.normpath(folder):
            raise ValueError("not a media key")
        return path

    def _managed_path(self, key: str, visibility: Visibility) -> Path:
        try:
            return self.path(key, visibility)
        except ValueError:
            raise StorageError("Not a media key.") from None

    def put(
        self,
        key: str,
        data: bytes | BinaryIO,
        *,
        visibility: Visibility,
        content_type: str,
        cache_control: str | None = None,
    ) -> None:
        # content_type and cache_control are metadata for object storage; files on disk get
        # their content type from the extension when served.
        path = self._managed_path(key, visibility)
        if path.exists():
            raise StorageError("A file already exists under this key.")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".upload-", suffix=".tmp")
        except OSError as exc:
            raise StorageError(f"Cannot write the file ({type(exc).__name__}).") from None
        try:
            with os.fdopen(fd, "wb") as handle:
                if isinstance(data, bytes | bytearray):
                    handle.write(data)
                else:
                    shutil.copyfileobj(data, handle, COPY_CHUNK_BYTES)
            os.replace(temp_name, path)
        except BaseException as exc:
            Path(temp_name).unlink(missing_ok=True)
            if isinstance(exc, OSError):
                raise StorageError(f"Cannot write the file ({type(exc).__name__}).") from None
            raise

    def get(self, key: str, *, visibility: Visibility) -> bytes:
        try:
            return self._managed_path(key, visibility).read_bytes()
        except OSError as exc:
            raise StorageError(f"Cannot read the file ({type(exc).__name__}).") from None

    def exists(self, key: str, *, visibility: Visibility) -> bool:
        return self._managed_path(key, visibility).is_file()

    def delete(self, key: str, *, visibility: Visibility) -> None:
        try:
            self._managed_path(key, visibility).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"Cannot delete the file ({type(exc).__name__}).") from None

    def public_url(self, key: str) -> str:
        return f"{self.public_base_url}/{quote(key, safe='/')}"

    def list(self, prefix: str, *, visibility: Visibility) -> Iterator[str]:
        folder = self._folder(visibility)
        if not folder.is_dir():
            return
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.name.startswith(".upload-"):
                continue
            key = path.relative_to(folder).as_posix()
            if key.startswith(prefix):
                yield key

    def free_bytes(self) -> int | None:
        self.root.mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(self.root).free


class PublicMediaFiles(StaticFiles):
    """Serves MEDIA_ROOT/public only (development). MEDIA_ROOT/private is outside the served
    folder, and StaticFiles refuses paths that leave it."""

    def __init__(self, storage: LocalMediaStorage) -> None:
        storage.public_root.mkdir(parents=True, exist_ok=True)
        super().__init__(directory=storage.public_root)


def get_media_storage() -> MediaStorage:
    settings = get_settings()
    if settings.storage_backend == "r2":
        from app.integrations.media.r2 import R2MediaStorage

        # The settings validator guarantees every R2 value below is set.
        secret = settings.r2_secret_access_key
        return R2MediaStorage(
            endpoint=settings.r2_endpoint_url
            or f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            access_key_id=settings.r2_access_key_id or "",
            secret_access_key=secret.get_secret_value() if secret else "",
            public_bucket=settings.r2_public_bucket or "",
            private_bucket=settings.r2_private_bucket or "",
            public_base_url=settings.image_public_base_url,
        )
    return LocalMediaStorage(settings.media_root, settings.image_public_base_url)
