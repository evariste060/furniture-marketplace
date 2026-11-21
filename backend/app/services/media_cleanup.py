"""The media cleanup worker's work (ADR-009; checkpoint 1b topic 1, 2026-10-26).

- sweep: 'pending' objects older than PENDING_TTL (a request that failed or crashed between
  registering and using its files) and expired incoming uploads become 'deleting'.
- delete_due: for each 'deleting' object whose delete_after has passed, in one transaction: lock
  it (SKIP LOCKED, so several workers never take the same object), delete its row (the foreign
  keys refuse while anything still uses it), delete its file, commit. A missing file counts as
  deleted, so a retry after a crash is harmless. On failure the row stays 'deleting' with
  attempts + 1, last_error, and delete_after pushed back (exponential backoff, at most an hour).
- reconcile: storage keys without a registry row (report only; nothing is deleted).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.transaction import atomic
from app.integrations.media import MediaStorage, StorageError, Visibility
from app.models.media import LAST_ERROR_MAX_LENGTH, MediaObject

logger = logging.getLogger("app.media")

PENDING_TTL = timedelta(hours=1)
SWEEP_INTERVAL = timedelta(minutes=15)
MAX_BACKOFF = timedelta(hours=1)


def backoff(attempts: int) -> timedelta:
    """Wait before retry number `attempts` (1, 2, 4, ... minutes, at most an hour)."""
    return min(timedelta(minutes=2 ** max(attempts - 1, 0)), MAX_BACKOFF)


@dataclass
class CleanupResult:
    deleted: int = 0
    failed: int = 0


def sweep(db: Session, now: datetime) -> int:
    """Mark abandoned pending objects and expired incoming uploads for deletion."""
    with atomic(db):
        abandoned = db.execute(
            update(MediaObject)
            .where(MediaObject.state == "pending", MediaObject.created_at < now - PENDING_TTL)
            .values(state="deleting", delete_after=now, updated_at=now)
        ).rowcount  # type: ignore[attr-defined]
        expired = db.execute(
            update(MediaObject)
            .where(
                MediaObject.state == "active",
                MediaObject.kind == "incoming",
                MediaObject.delete_after <= now,
            )
            .values(state="deleting", delete_after=now, updated_at=now)
        ).rowcount  # type: ignore[attr-defined]
    if abandoned or expired:
        logger.info("Media sweep: %d abandoned, %d expired incoming", abandoned, expired)
    return int(abandoned) + int(expired)


def _error_text(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text[:LAST_ERROR_MAX_LENGTH]


def _record_failure(db: Session, media_id, exc: BaseException, now: datetime) -> None:
    db.rollback()
    with atomic(db):
        media = db.get(MediaObject, media_id, with_for_update=True)
        if media is None:
            return
        media.attempts += 1
        media.last_error = _error_text(exc)
        media.delete_after = now + backoff(media.attempts)
    logger.warning(
        "Media file deletion failed (attempt %d, %s); retrying later",
        media.attempts,
        type(exc).__name__,
    )


def delete_one(db: Session, storage: MediaStorage, now: datetime) -> bool | None:
    """Delete the next due object. None when nothing is due; True/False for success."""
    media_id = None
    try:
        with atomic(db):
            media = db.scalar(
                select(MediaObject)
                .where(
                    MediaObject.state == "deleting",
                    or_(MediaObject.delete_after.is_(None), MediaObject.delete_after <= now),
                )
                .order_by(MediaObject.delete_after.asc().nulls_first(), MediaObject.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if media is None:
                return None
            media_id = media.id
            key, visibility = media.storage_key, media.visibility
            db.delete(media)
            db.flush()  # a row still in use fails here, before its file is touched
            storage.delete(key, visibility=_visibility(visibility))
    except (SQLAlchemyError, StorageError) as exc:
        if media_id is None:
            raise
        _record_failure(db, media_id, exc, now)
        return False
    return True


def _visibility(value: str) -> Visibility:
    return "public" if value == "public" else "private"


def delete_due(
    db: Session, storage: MediaStorage, now: datetime, limit: int = 100
) -> CleanupResult:
    result = CleanupResult()
    for _ in range(limit):
        outcome = delete_one(db, storage, now)
        if outcome is None:
            break
        if outcome:
            result.deleted += 1
        else:
            result.failed += 1
    return result


def reconcile(db: Session, storage: MediaStorage) -> list[tuple[Visibility, str]]:
    """Stored keys with no registry row, for a report. Nothing is deleted."""
    unknown: list[tuple[Visibility, str]] = []
    visibilities: tuple[Visibility, ...] = ("private", "public")
    for visibility in visibilities:
        known = set(
            db.scalars(select(MediaObject.storage_key).where(MediaObject.visibility == visibility))
        )
        unknown.extend(
            (visibility, key) for key in storage.list("", visibility=visibility) if key not in known
        )
    return unknown
