"""The durable job queue and the worker (approved 2026-10-26, checkpoint 1b topic 4).

A fake handler stands in for a real job type here; the bulk image upload has its own tests.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app import worker as worker_module
from app.models import AuditRecord, ImportJob, Job, JobItem
from app.services import jobs
from app.services.catalog_import import STALE_IMPORT_AFTER, fail_stale_imports
from app.services.jobs import MAX_ATTEMPTS, STALE_AFTER, ItemFailed, JobHandler, NewItem

STAFF = "/api/v1/staff/jobs"
TYPE = "bulk_image_upload"


class FakeWork:
    """Records processed items; behaviour per payload: ok, fail (permanent) or crash."""

    def __init__(self) -> None:
        self.processed: list[tuple[int, int]] = []
        self.finished: list[uuid.UUID] = []

    def process(self, db: Session, job: Job, item: JobItem) -> dict:
        self.processed.append((item.item_index, item.attempts))
        kind = item.payload.get("kind", "ok")
        if kind == "fail":
            raise ItemFailed("bad_input", "This item cannot be done.")
        if kind == "crash":
            raise RuntimeError("simulated crash")
        return {"did": item.payload.get("name")}

    def on_finished(self, db: Session, job: Job) -> None:
        self.finished.append(job.id)


@pytest.fixture
def work(monkeypatch) -> FakeWork:
    fake = FakeWork()
    monkeypatch.setitem(jobs.HANDLERS, TYPE, JobHandler(fake.process, fake.on_finished))
    return fake


def now() -> datetime:
    return datetime.now(UTC)


def new_job(db: Session, actor, *items: NewItem) -> Job:
    job = jobs.create_job(db, TYPE, actor, list(items))
    db.commit()
    return job


def run_all(db: Session) -> list[str]:
    outcomes = []
    while (item_id := jobs.claim_next(db, now())) is not None:
        outcomes.append(jobs.process(db, item_id, now()))
    return outcomes


def reload(db: Session, job: Job) -> Job:
    db.expire_all()
    fresh = db.get(Job, job.id)
    assert fresh is not None
    return fresh


def test_items_run_in_job_then_index_order_and_the_job_finishes_once(db, admin_auth, work):
    actor = admin_auth["user"]
    first = new_job(db, actor, NewItem({"name": "a"}), NewItem({"name": "b"}))
    second = new_job(db, actor, NewItem({"name": "c"}))
    assert (first.state, first.total_items) == ("queued", 2)
    assert run_all(db) == ["done", "done", "done"]
    assert work.processed == [(0, 1), (1, 1), (0, 1)]
    for job in (reload(db, first), reload(db, second)):
        assert (job.state, job.succeeded_items, job.failed_items) == (
            "finished",
            job.total_items,
            0,
        )
        assert job.finished_at is not None
    assert work.finished == [first.id, second.id]
    items = reload(db, first).items
    assert [i.result for i in items] == [{"did": "a"}, {"did": "b"}]


def test_a_permanent_failure_is_not_retried(db, admin_auth, work):
    job = new_job(db, admin_auth["user"], NewItem({"kind": "fail"}), NewItem({}))
    assert run_all(db) == ["failed", "done"]
    fresh = reload(db, job)
    assert (fresh.state, fresh.succeeded_items, fresh.failed_items) == ("finished", 1, 1)
    assert fresh.items[0].error == "bad_input: This item cannot be done."


def test_a_crash_is_retried_up_to_the_limit_then_failed(db, admin_auth, work):
    job = new_job(db, admin_auth["user"], NewItem({"kind": "crash"}))
    assert run_all(db) == ["queued"] * (MAX_ATTEMPTS - 1) + ["failed"]
    assert [attempts for _, attempts in work.processed] == list(range(1, MAX_ATTEMPTS + 1))
    item = reload(db, job).items[0]
    assert item.state == "failed" and item.error is not None
    assert item.error.startswith("failed_after_retries: RuntimeError")


def test_two_workers_never_claim_the_same_item(db, admin_auth, work, pg_engine: Engine):
    new_job(db, admin_auth["user"], NewItem({"name": "a"}), NewItem({"name": "b"}))
    other = sessionmaker(bind=pg_engine)()
    try:
        held = other.scalars(
            select(JobItem).order_by(JobItem.item_index).limit(1).with_for_update()
        ).one()
        claimed = jobs.claim_next(db, now())
        assert claimed is not None and claimed != held.id  # the locked item is skipped
        assert jobs.claim_next(db, now()) is None
    finally:
        other.rollback()
        other.close()


def test_items_for_the_same_target_run_in_job_order(db, admin_auth, work):
    actor = admin_auth["user"]
    first = new_job(db, actor, NewItem({"name": "old"}, target="product:1:position:1"))
    second = new_job(db, actor, NewItem({"name": "new"}, target="product:1:position:1"))
    other = new_job(db, actor, NewItem({"name": "other"}, target="product:2:position:1"))
    claimed = jobs.claim_next(db, now())
    assert claimed == reload(db, first).items[0].id
    # While the first is processing, the second (same target) waits; other targets go ahead.
    assert jobs.claim_next(db, now()) == reload(db, other).items[0].id
    assert jobs.claim_next(db, now()) is None
    jobs.process(db, claimed, now())
    assert jobs.claim_next(db, now()) == reload(db, second).items[0].id


def test_an_item_whose_worker_stopped_is_requeued_then_failed(db, admin_auth, work):
    job = new_job(db, admin_auth["user"], NewItem({}))
    for attempt in range(1, MAX_ATTEMPTS + 1):
        item_id = jobs.claim_next(db, now())
        assert item_id is not None  # claimed, then the worker "crashes"
        db.execute(
            update(JobItem)
            .where(JobItem.id == item_id)
            .values(locked_at=now() - STALE_AFTER - timedelta(seconds=1))
        )
        db.commit()
        assert jobs.requeue_stale(db, now()) == 1
        item = reload(db, job).items[0]
        expected = "failed" if attempt == MAX_ATTEMPTS else "queued"
        assert (item.state, item.attempts) == (expected, attempt)
    assert reload(db, job).state == "finished"
    assert "timed_out" in (reload(db, job).items[0].error or "")


def test_a_fresh_processing_item_is_not_requeued(db, admin_auth, work):
    new_job(db, admin_auth["user"], NewItem({}))
    assert jobs.claim_next(db, now()) is not None
    assert jobs.requeue_stale(db, now()) == 0


def test_the_worker_pass_processes_items(db, admin_auth, work, pg_engine: Engine, monkeypatch):
    job = new_job(db, admin_auth["user"], NewItem({"name": "a"}))
    factory = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(worker_module, "SessionLocal", factory)
    worker = worker_module.Worker()
    assert worker.run_once() is True
    assert reload(db, job).state == "finished"


# ---- API ---------------------------------------------------------------------------------
def test_staff_read_a_job_and_retry_only_its_retryable_failed_items(client, db, admin_auth, work):
    h = admin_auth["headers"]
    job = new_job(
        db,
        admin_auth["user"],
        NewItem({"kind": "fail"}),
        NewItem({"name": "ok"}),
        NewItem({}, state="failed", error="unknown_slug: x.jpg", result={"final": True}),
    )
    run_all(db)
    body = client.get(f"{STAFF}/{job.id}", headers=h).json()
    assert (body["state"], body["succeeded_items"], body["failed_items"]) == ("finished", 1, 2)
    assert [i["state"] for i in body["items"]] == ["failed", "done", "failed"]

    work.processed.clear()
    db.execute(update(JobItem).where(JobItem.item_index == 0).values(payload={"name": "fixed"}))
    db.commit()
    retried = client.post(f"{STAFF}/{job.id}/retry-failed", headers=h)
    assert retried.status_code == 200, retried.text
    assert [i["state"] for i in retried.json()["items"]] == ["queued", "done", "failed"]
    assert retried.json()["state"] == "processing"
    run_all(db)
    assert work.processed == [(0, 1)]  # only the retryable failed item ran again
    assert reload(db, job).succeeded_items == 2
    audit = db.scalars(select(AuditRecord).where(AuditRecord.action == "job.retry_failed")).one()
    assert audit.change_summary["requeued_items"] == 1

    again = client.post(f"{STAFF}/{job.id}/retry-failed", headers=h)
    assert again.status_code == 409 and again.json()["error"]["code"] == "nothing_to_retry"
    missing = client.get(f"{STAFF}/{uuid.uuid4()}", headers=h)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "job_not_found"


@pytest.mark.parametrize(
    ("who", "expected"),
    [
        ("admin_auth", 200),
        ("customer_auth", 403),
        (None, 401),
    ],
)
def test_jobs_need_catalog_manage(client, db, admin_auth, work, request, who, expected):
    job = new_job(db, admin_auth["user"], NewItem({}))
    headers = request.getfixturevalue(who)["headers"] if who else {}
    assert client.get(f"{STAFF}/{job.id}", headers=headers).status_code == expected


# ---- stale catalogue imports ---------------------------------------------------------------
def test_imports_left_processing_by_a_stopped_process_are_marked_failed(db, admin_auth):
    actor = admin_auth["user"]
    stale = ImportJob(created_by_user_id=actor.id, filename="a.csv", file_format="csv")
    fresh = ImportJob(created_by_user_id=actor.id, filename="b.csv", file_format="csv")
    db.add_all([stale, fresh])
    db.commit()
    db.execute(
        update(ImportJob)
        .where(ImportJob.id == stale.id)
        .values(created_at=now() - STALE_IMPORT_AFTER - timedelta(seconds=1))
    )
    db.commit()
    assert fail_stale_imports(db, now()) == 1
    db.expire_all()
    failed = db.get(ImportJob, stale.id)
    assert failed is not None and failed.status == "failed" and failed.finished_at is not None
    assert "stopped unexpectedly" in failed.errors[0]["message"]
    assert db.get(ImportJob, fresh.id).status == "processing"  # type: ignore[union-attr]
    audit = db.scalars(select(AuditRecord).where(AuditRecord.entity_id == str(stale.id))).one()
    assert (audit.action, audit.change_summary["status"]) == ("catalog.import", "failure")
    assert audit.actor_user_id == actor.id and audit.request_id == "worker:stale_import"
    assert fail_stale_imports(db, now()) == 0
