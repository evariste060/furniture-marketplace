"""The durable job queue (approved 2026-10-26, checkpoint 1b topic 4; app.models.jobs).

The API creates a job and its items in one transaction; the worker process
(python -m app.worker) claims and processes items:
- claim_next: one transaction locks the next queued item with FOR UPDATE SKIP LOCKED (so two
  workers never take the same item), marks it 'processing' (attempts + 1, locked_at) and
  commits. Items run in (job created_at, item index) order, and an item is not claimed while an
  earlier unfinished item has the same target, so changes to one target land in job order.
- process: runs the job type's handler. ItemFailed is a permanent failure ('failed', with its
  code); any other exception requeues the item until MAX_ATTEMPTS, then fails it.
- requeue_stale: an item 'processing' for longer than STALE_AFTER belongs to a crashed worker:
  it is requeued, or failed once it has had MAX_ATTEMPTS.
- retry_failed: staff requeue a job's failed items (attempts reset).
After every item the job's counts are recomputed; with nothing queued or processing it is
'finished' and its handler's on_finished hook runs (for example a job-level audit event).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, select, tuple_, update
from sqlalchemy.orm import Session, aliased

from app.core.errors import Conflict, NotFound
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.models.identity import User
from app.models.jobs import ITEM_ERROR_MAX_LENGTH, Job, JobItem
from app.services.audit_service import AuditService

logger = logging.getLogger("app.jobs")

STALE_AFTER = timedelta(minutes=10)
MAX_ATTEMPTS = 3
JOB_NOT_FOUND = "Job not found."


class ItemFailed(Exception):
    """A permanent failure of one item: it is not retried automatically."""

    def __init__(self, code: str, message: str, result: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.result = result


@dataclass(frozen=True)
class JobHandler:
    # (db, job, item) -> the item's result. Commits its own changes; raises ItemFailed for a
    # permanent failure.
    process: Callable[[Session, Job, JobItem], dict[str, Any]]
    # (db, job) inside the transaction that finishes the job.
    on_finished: Callable[[Session, Job], None] | None = None


HANDLERS: dict[str, JobHandler] = {}


@dataclass
class NewItem:
    payload: dict[str, Any]
    target: str | None = None
    state: str = "queued"  # an item can be created already 'failed' (e.g. a rejected file)
    error: str | None = None
    result: dict[str, Any] | None = field(default=None)


def job_context(job: Job | uuid.UUID) -> str:
    """The audit request_id of work done for a job."""
    job_id = job.id if isinstance(job, Job) else job
    return f"job:{job_id}"


def create_job(
    db: Session,
    job_type: str,
    actor: User,
    items: list[NewItem],
    *,
    job_id: uuid.UUID | None = None,
) -> Job:
    """Stage a job and its items in the caller's transaction. job_id may be chosen in advance
    (for example to name the job's incoming files before it exists)."""
    job = Job(
        id=job_id or uuid.uuid4(),
        type=job_type,
        created_by_user_id=actor.id,
        total_items=len(items),
    )
    db.add(job)
    db.flush()
    for index, new in enumerate(items):
        db.add(
            JobItem(
                job_id=job.id,
                item_index=index,
                state=new.state,
                target=new.target,
                payload=new.payload,
                error=new.error,
                result=new.result,
            )
        )
    db.flush()
    _refresh_job(db, job, datetime_now(db))
    return job


def datetime_now(db: Session) -> datetime:
    return db.scalar(select(func.now()))  # type: ignore[return-value]


def _refresh_job(db: Session, job: Job, now: datetime) -> None:
    """Recompute the job's counts and state from its items (caller's transaction)."""
    counts = dict(
        db.execute(
            select(JobItem.state, func.count(JobItem.id))
            .where(JobItem.job_id == job.id)
            .group_by(JobItem.state)
        ).all()
    )
    job.succeeded_items = counts.get("done", 0)
    job.failed_items = counts.get("failed", 0)
    open_items = counts.get("queued", 0) + counts.get("processing", 0)
    was_finished = job.state == "finished"
    if open_items == 0:
        job.state = "finished"
        if not was_finished:
            job.finished_at = now
            handler = HANDLERS.get(job.type)
            if handler is not None and handler.on_finished is not None:
                handler.on_finished(db, job)
    else:
        started = counts.get("processing") or job.succeeded_items or job.failed_items
        job.state = "processing" if started else "queued"
        job.finished_at = None
    db.flush()


def claim_next(db: Session, now: datetime) -> uuid.UUID | None:
    """Lock, mark and commit the next claimable item; its ID, or None when nothing is ready."""
    earlier_item = aliased(JobItem)
    earlier_job = aliased(Job)
    earlier_unfinished = exists().where(
        earlier_item.job_id == earlier_job.id,
        earlier_item.target == JobItem.target,
        earlier_item.state.in_(("queued", "processing")),
        tuple_(earlier_job.created_at, earlier_job.id, earlier_item.item_index)
        < tuple_(Job.created_at, Job.id, JobItem.item_index),
    )
    with atomic(db):
        item = db.scalar(
            select(JobItem)
            .join(Job, Job.id == JobItem.job_id)
            .where(JobItem.state == "queued", ~earlier_unfinished)
            .order_by(Job.created_at, Job.id, JobItem.item_index)
            .limit(1)
            .with_for_update(of=JobItem, skip_locked=True)
        )
        if item is None:
            return None
        item.state = "processing"
        item.locked_at = now
        item.attempts += 1
        job = db.get(Job, item.job_id, with_for_update=True)
        assert job is not None
        if job.state == "queued":
            job.state = "processing"
        db.flush()
        return item.id


def _finish_item(
    db: Session,
    item_id: uuid.UUID,
    now: datetime,
    *,
    state: str,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    with atomic(db):
        item = db.get(JobItem, item_id, with_for_update=True)
        if item is None or item.state != "processing":
            return  # requeued as stale meanwhile: its newer claim decides
        job = db.get(Job, item.job_id, with_for_update=True)
        assert job is not None
        item.state = state
        item.locked_at = None
        item.error = error[:ITEM_ERROR_MAX_LENGTH] if error else None
        if result is not None:
            item.result = result
        db.flush()
        _refresh_job(db, job, now)


def process(db: Session, item_id: uuid.UUID, now: datetime) -> str:
    """Run one claimed item; returns its new state ('done', 'failed' or 'queued')."""
    item = db.get(JobItem, item_id)
    assert item is not None
    job = db.get(Job, item.job_id)
    assert job is not None
    handler = HANDLERS.get(job.type)
    try:
        if handler is None:
            raise ItemFailed("unsupported_job_type", f"No handler for {job.type} jobs.")
        result = handler.process(db, job, item)
    except ItemFailed as failure:
        db.rollback()
        error = f"{failure.code}: {failure.message}"
        _finish_item(db, item_id, now, state="failed", error=error, result=failure.result)
        return "failed"
    except Exception as exc:  # noqa: BLE001 - retried; the worker must keep running
        db.rollback()
        logger.warning("Job item %s failed (%s)", item_id, type(exc).__name__)
        attempts = item.attempts
        if attempts >= MAX_ATTEMPTS:
            error = f"failed_after_retries: {type(exc).__name__} after {attempts} attempts"
            _finish_item(db, item_id, now, state="failed", error=error)
            return "failed"
        _finish_item(db, item_id, now, state="queued", error=f"retrying: {type(exc).__name__}")
        return "queued"
    _finish_item(db, item_id, now, state="done", result=result)
    return "done"


def requeue_stale(db: Session, now: datetime) -> int:
    """Requeue (or, after MAX_ATTEMPTS, fail) items whose worker stopped mid-item."""
    with atomic(db):
        stale = list(
            db.scalars(
                select(JobItem)
                .where(JobItem.state == "processing", JobItem.locked_at < now - STALE_AFTER)
                .with_for_update(skip_locked=True)
            )
        )
        for item in stale:
            item.locked_at = None
            if item.attempts >= MAX_ATTEMPTS:
                item.state = "failed"
                item.error = f"timed_out: no result after {item.attempts} attempts"
            else:
                item.state = "queued"
                item.error = "retrying: the worker stopped while processing it"
        db.flush()
        for job_id in {item.job_id for item in stale}:
            job = db.get(Job, job_id, with_for_update=True)
            if job is not None:
                _refresh_job(db, job, now)
    if stale:
        logger.warning("Requeued or failed %d stale job item(s)", len(stale))
    return len(stale)


def get_job(db: Session, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFound(JOB_NOT_FOUND, code="job_not_found")
    return job


def retry_failed(db: Session, actor: User, job_id: uuid.UUID, ctx: RequestContext) -> Job:
    """Requeue a job's failed items; done items are never redone. Items rejected before they
    were queued (their result has "final": true, e.g. an unknown file name) cannot be retried:
    the file must be uploaded again."""
    with atomic(db):
        job = db.get(Job, job_id, with_for_update=True)
        if job is None:
            raise NotFound(JOB_NOT_FOUND, code="job_not_found")
        retryable = and_(
            JobItem.job_id == job.id,
            JobItem.state == "failed",
            JobItem.result.is_(None) | ~JobItem.result.has_key("final"),  # type: ignore[attr-defined]
        )
        requeued = db.execute(
            update(JobItem)
            .where(retryable)
            .values(state="queued", attempts=0, error=None, locked_at=None, updated_at=func.now())
        ).rowcount  # type: ignore[attr-defined]
        if not requeued:
            raise Conflict("The job has no failed items to retry.", code="nothing_to_retry")
        db.flush()
        _refresh_job(db, job, datetime_now(db))
        AuditService.log_event(
            db=db,
            action="job.retry_failed",
            status="success",
            actor=actor,
            entity_type="job",
            entity_id=job.id,
            context=ctx,
            details={"type": job.type, "requeued_items": requeued},
        )
    db.refresh(job)
    return job
