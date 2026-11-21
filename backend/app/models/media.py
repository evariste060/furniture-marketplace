"""The media registry (ADR-009; approved 2026-10-26, checkpoint 1b): one row per stored file.

A file is written under a new key, never overwritten. Its row goes through
pending -> active -> deleting:
- pending: inserted and committed before the file is written; nothing uses it yet. A pending row
  older than an hour belongs to a request that failed or crashed, and the cleanup worker deletes
  its file (if any) and the row.
- active: committed in the same transaction that makes an image, category, brand or banner use
  it (or, for an incoming bulk-upload file, that queues its job item).
- deleting: committed in the same transaction that stops using it. The cleanup worker deletes the
  file, then the row; a failed deletion is retried with backoff and keeps its last_error.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.common import Entity

MediaKind = Literal["original", "public_source", "incoming"]
MediaState = Literal["pending", "active", "deleting"]
MediaOwnerType = Literal["products", "categories", "brands", "banners", "jobs"]
LAST_ERROR_MAX_LENGTH = 500


class MediaObject(Entity):
    __tablename__ = "media_objects"
    __table_args__ = (
        CheckConstraint("visibility IN ('private', 'public')", name="valid_visibility"),
        CheckConstraint("kind IN ('original', 'public_source', 'incoming')", name="valid_kind"),
        CheckConstraint("state IN ('pending', 'active', 'deleting')", name="valid_state"),
        CheckConstraint(
            "owner_type IN ('products', 'categories', 'brands', 'banners', 'jobs', 'services', "
            "'stores')",
            name="valid_owner_type",
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint("bytes >= 0", name="bytes_nonnegative"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint(
            "(width IS NULL) = (height IS NULL) AND (width IS NULL OR (width > 0 AND height > 0))",
            name="dimensions_valid",
        ),
        # Originals and incoming uploads are private; public sources are public.
        CheckConstraint(
            "(kind = 'public_source') = (visibility = 'public')", name="kind_matches_visibility"
        ),
        CheckConstraint(
            "kind <> 'incoming' OR (visibility = 'private' AND delete_after IS NOT NULL)",
            name="incoming_private_and_expiring",
        ),
        # One store per visibility (two buckets later), so a key is unique within its visibility.
        UniqueConstraint(
            "visibility", "storage_key", name="uq_media_objects_visibility_storage_key"
        ),
        Index("ix_media_objects_state_created", "state", "created_at"),
        Index("ix_media_objects_state_delete_after", "state", "delete_after"),
        Index("ix_media_objects_owner", "owner_type", "owner_id"),
    )

    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    visibility: Mapped[str] = mapped_column(String(8), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(
        String(10), nullable=False, default="pending", server_default="pending"
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(nullable=False)
    # deleting: not before this time (retry backoff); incoming: expiry (7 days after upload).
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(LAST_ERROR_MAX_LENGTH))
