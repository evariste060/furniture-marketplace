"""The durable job queue (approved 2026-10-26, checkpoint 1b topic 4).

A job is one request's long work, done by the worker process (python -m app.worker), never by
the API process: FastAPI background tasks are lost on restart. A job has one item per unit of
work. Items are claimed with SELECT ... FOR UPDATE SKIP LOCKED, so two workers never take the
same one; an item stuck in 'processing' (its worker crashed) is requeued after STALE_AFTER, at
most MAX_ATTEMPTS times. The job is 'finished' when no item is queued or processing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import Entity

JobType = Literal["bulk_image_upload"]
JobState = Literal["queued", "processing", "finished"]
JobItemState = Literal["queued", "processing", "done", "failed"]
ITEM_ERROR_MAX_LENGTH = 500


class Job(Entity):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("type IN ('bulk_image_upload')", name="valid_type"),
        CheckConstraint("state IN ('queued', 'processing', 'finished')", name="valid_state"),
        CheckConstraint(
            "total_items >= 0 AND succeeded_items >= 0 AND failed_items >= 0 "
            "AND succeeded_items + failed_items <= total_items",
            name="counts_valid",
        ),
        CheckConstraint(
            "(state = 'finished') = (finished_at IS NOT NULL)", name="finished_when_final"
        ),
        Index("ix_jobs_created_by_created", "created_by_user_id", "created_at"),
    )

    type: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(
        String(12), nullable=False, default="queued", server_default="queued"
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    succeeded_items: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failed_items: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[JobItem]] = relationship(
        back_populates="job", order_by="JobItem.item_index", cascade="save-update, merge"
    )


class JobItem(Entity):
    __tablename__ = "job_items"
    __table_args__ = (
        CheckConstraint("state IN ('queued', 'processing', 'done', 'failed')", name="valid_state"),
        CheckConstraint("item_index >= 0", name="index_nonnegative"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint(
            "(state = 'processing') = (locked_at IS NOT NULL)", name="locked_when_processing"
        ),
        UniqueConstraint("job_id", "item_index", name="uq_job_items_job_index"),
        Index("ix_job_items_state_created", "state", "created_at"),
        Index("ix_job_items_target_state", "target", "state"),
    )

    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(12), nullable=False, default="queued", server_default="queued"
    )
    # What the item changes (e.g. "product:<id>:position:2"); items with the same target are
    # processed in job order.
    target: Mapped[str | None] = mapped_column(String(120))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(ITEM_ERROR_MAX_LENGTH))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    job: Mapped[Job] = relationship(back_populates="items")
