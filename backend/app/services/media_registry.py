"""Stored image files and their registry rows (ADR-009; checkpoint 1b topic 1, 2026-10-26).

Every stored image is two files under one key: the exact upload (private) and its sanitised
public source. Adding or replacing an image runs in three steps:

1. stage_image: insert both media_objects rows as 'pending' and commit (TX-A), then write both
   files. If a write fails, the files written so far and the rows are removed best-effort; what
   cannot be removed stays 'pending' and the cleanup worker sweeps it after an hour.
2. In the caller's transaction (TX-B): link the image row to the staged objects, activate them
   (activate), and retire the objects it no longer uses (retire: 'deleting').
3. If TX-B fails, the caller calls discard_staged: the new files and rows are removed
   best-effort, and anything left is swept.

Files are never deleted in a request: the cleanup worker (app.services.media_cleanup) deletes a
'deleting' object's file and then its row, so a replaced image stays reachable until the
replacement is committed, and a rolled-back request never loses a live file.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, update
from sqlalchemy.orm import Session

from app.db.transaction import atomic
from app.integrations.media import PUBLIC_CACHE_CONTROL, MediaStorage, Owner, new_key
from app.models.media import MediaObject
from app.services.image_processing import ProcessedImage

logger = logging.getLogger("app.media")


@dataclass(frozen=True)
class StagedImage:
    """Both files of one image, written and registered as 'pending'."""

    original_id: uuid.UUID
    public_id: uuid.UUID
    key: str  # the same key in private (original) and public (public source) storage
    width: int  # of the public source
    height: int
    content_type: str
    sha256: str  # of the exact original upload: identifies the image's content
    bytes: int  # size of the original upload

    @property
    def ids(self) -> tuple[uuid.UUID, uuid.UUID]:
        return (self.original_id, self.public_id)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stage_image(
    db: Session,
    storage: MediaStorage,
    owner: Owner,
    owner_id: uuid.UUID,
    processed: ProcessedImage,
) -> StagedImage:
    """TX-A, then the file writes. Raises if a write fails (after cleaning up)."""
    key = new_key(owner, owner_id, processed.extension, processed.original)
    original_sha = sha256_hex(processed.original)
    with atomic(db):
        original = MediaObject(
            storage_key=key,
            visibility="private",
            kind="original",
            state="pending",
            sha256=original_sha,
            bytes=len(processed.original),
            content_type=processed.content_type,
            owner_type=owner,
            owner_id=owner_id,
        )
        public = MediaObject(
            storage_key=key,
            visibility="public",
            kind="public_source",
            state="pending",
            sha256=sha256_hex(processed.public),
            bytes=len(processed.public),
            width=processed.width,
            height=processed.height,
            content_type=processed.content_type,
            owner_type=owner,
            owner_id=owner_id,
        )
        db.add_all([original, public])
        db.flush()
    staged = StagedImage(
        original_id=original.id,
        public_id=public.id,
        key=key,
        width=processed.width,
        height=processed.height,
        content_type=processed.content_type,
        sha256=original_sha,
        bytes=len(processed.original),
    )
    try:
        storage.put(
            key, processed.original, visibility="private", content_type=processed.content_type
        )
        storage.put(
            key,
            processed.public,
            visibility="public",
            content_type=processed.content_type,
            cache_control=PUBLIC_CACHE_CONTROL,
        )
    except BaseException:
        discard_staged(db, storage, staged)
        raise
    return staged


def activate(db: Session, staged: StagedImage) -> None:
    """In TX-B: the staged objects are now in use."""
    activated = db.execute(
        update(MediaObject)
        .where(MediaObject.id.in_(staged.ids), MediaObject.state == "pending")
        .values(state="active", updated_at=func.now())
    ).rowcount  # type: ignore[attr-defined]
    if activated != len(staged.ids):
        raise RuntimeError("Staged media objects are no longer pending.")


def retire(db: Session, media_ids: Iterable[uuid.UUID | None]) -> None:
    """In TX-B: these objects are no longer used; the cleanup worker deletes their files."""
    ids = [media_id for media_id in media_ids if media_id is not None]
    if not ids:
        return
    db.execute(
        update(MediaObject)
        .where(MediaObject.id.in_(ids))
        .values(
            state="deleting",
            delete_after=func.now(),
            attempts=0,
            last_error=None,
            updated_at=func.now(),
        )
    )


def discard_staged(db: Session, storage: MediaStorage, staged: StagedImage) -> None:
    """After a failure: remove the staged files, then their rows. Best-effort, never raises;
    what is left stays 'pending' and is swept by the cleanup worker."""
    db.rollback()
    try:
        for visibility in ("private", "public"):
            storage.delete(staged.key, visibility=visibility)
    except Exception as exc:  # noqa: BLE001 - the sweeper finishes the job
        logger.warning("Discarding staged media failed (%s); left for cleanup", type(exc).__name__)
        return
    try:
        with atomic(db):
            db.execute(
                delete(MediaObject).where(
                    MediaObject.id.in_(staged.ids), MediaObject.state == "pending"
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Deleting staged media rows failed (%s); left for cleanup", type(exc).__name__
        )


def public_image(
    storage: MediaStorage, media: MediaObject, alt: str, position: int
) -> dict[str, Any]:
    """The public image object {url, width, height, alt, position} of a public media object."""
    return {
        "url": storage.public_url(media.storage_key),
        "width": media.width,
        "height": media.height,
        "alt": alt,
        "position": position,
    }
