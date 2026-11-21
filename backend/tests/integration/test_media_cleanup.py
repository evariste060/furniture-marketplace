"""The media cleanup worker (ADR-009; checkpoint 1b topic 1, 2026-10-26): sweeping abandoned and
expired files, deleting retired files then their rows, retries with backoff, SKIP LOCKED, the
in-use guard, and the report-only reconciliation."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app import worker as worker_module
from app.integrations.media import LocalMediaStorage, incoming_key, new_key
from app.models import Category, MediaObject, Product
from app.services import media_cleanup
from app.services.media_cleanup import PENDING_TTL, backoff
from tests.support.media import image_row, media_pair
from tests.support.sellers import new_store

NOW = datetime.now(UTC)


@pytest.fixture
def storage(tmp_path) -> LocalMediaStorage:
    return LocalMediaStorage(tmp_path / "media", "http://localhost:8000/media")


def category(db: Session) -> Category:
    row = Category(name="Phones", slug=f"phones-{uuid.uuid4().hex[:8]}")
    db.add(row)
    db.commit()
    return row


def stored(storage: LocalMediaStorage, db: Session, state: str, **fields) -> MediaObject:
    """A registered image file pair's public object, with its file written."""
    owner = uuid.uuid4()
    key = new_key("products", owner, "jpg", uuid.uuid4().bytes)
    public, original = media_pair(key, "products", owner)
    for media in (public, original):
        media.state = state
        for name, value in fields.items():
            setattr(media, name, value)
        storage.put(key, b"bytes", visibility=media.visibility, content_type="image/jpeg")  # type: ignore[arg-type]
    db.add_all([public, original])
    db.commit()
    return public


def states(db: Session) -> list[tuple[str, str]]:
    db.expire_all()
    return sorted(
        (key, state)
        for key, state in db.execute(select(MediaObject.storage_key, MediaObject.state))
    )


def files(storage: LocalMediaStorage) -> int:
    return sum(1 for p in storage.root.rglob("*") if p.is_file()) if storage.root.exists() else 0


def test_backoff_doubles_up_to_an_hour():
    assert [backoff(n) for n in (1, 2, 3, 7)] == [
        timedelta(minutes=1),
        timedelta(minutes=2),
        timedelta(minutes=4),
        timedelta(hours=1),
    ]
    assert backoff(20) == timedelta(hours=1)


def test_the_sweep_retires_abandoned_pending_files_and_expired_incoming_uploads(storage, db):
    old = stored(storage, db, "pending")
    db.execute(
        update(MediaObject)
        .where(MediaObject.storage_key == old.storage_key)
        .values(created_at=NOW - PENDING_TTL - timedelta(minutes=1))
    )
    db.commit()
    fresh = stored(storage, db, "pending")  # a request still in progress
    active = stored(storage, db, "active")
    owner = uuid.uuid4()
    incoming = [
        MediaObject(
            storage_key=incoming_key(owner, uuid.uuid4()),
            visibility="private",
            kind="incoming",
            state="active",
            sha256="0" * 64,
            bytes=1,
            content_type="image/jpeg",
            owner_type="jobs",
            owner_id=owner,
            delete_after=when,
        )
        for when in (NOW - timedelta(seconds=1), NOW + timedelta(days=7))
    ]
    db.add_all(incoming)
    db.commit()

    assert media_cleanup.sweep(db, NOW) == 3  # both files of the old pair, one incoming upload
    db.expire_all()
    rows = db.execute(select(MediaObject.storage_key, MediaObject.state)).all()
    by_key: dict[str, set[str]] = {}
    for key, state in rows:
        by_key.setdefault(key, set()).add(state)
    assert by_key[old.storage_key] == {"deleting"}
    assert by_key[fresh.storage_key] == {"pending"}
    assert by_key[active.storage_key] == {"active"}
    assert by_key[incoming[0].storage_key] == {"deleting"}
    assert by_key[incoming[1].storage_key] == {"active"}


def test_retired_files_are_deleted_then_their_rows_and_a_missing_file_is_fine(storage, db):
    retired = stored(storage, db, "deleting", delete_after=NOW - timedelta(seconds=1))
    later = stored(storage, db, "deleting", delete_after=NOW + timedelta(minutes=5))
    storage.delete(retired.storage_key, visibility="public")  # already gone: still a success
    assert files(storage) == 3
    result = media_cleanup.delete_due(db, storage, NOW)
    assert (result.deleted, result.failed) == (2, 0)
    assert files(storage) == 2  # only the not-yet-due pair is left
    assert {key for key, _ in states(db)} == {later.storage_key}


def test_a_retired_object_still_in_use_keeps_its_file_and_records_the_error(storage, db):
    category_row = category(db)
    image = image_row(None, 0)
    product = Product(
        store=new_store(), name="Phone", slug=f"phone-{uuid.uuid4().hex[:8]}", category=category_row
    )
    image.product = product
    db.add(image)
    db.commit()
    key = image.public_media.storage_key
    storage.put(key, b"x", visibility="public", content_type="image/jpeg")
    image.public_media.state = "deleting"  # a bug elsewhere: retired while still linked
    db.commit()

    result = media_cleanup.delete_due(db, storage, NOW)
    assert (result.deleted, result.failed) == (0, 1)
    assert storage.exists(key, visibility="public")  # the file is untouched
    db.expire_all()
    media = db.get(MediaObject, image.public_media_id)
    assert media is not None and media.state == "deleting" and media.attempts == 1
    assert media.last_error and "IntegrityError" in media.last_error
    assert media.delete_after is not None and media.delete_after > NOW


def test_two_workers_never_take_the_same_object(storage, db, pg_engine: Engine):
    stored(storage, db, "deleting", delete_after=NOW - timedelta(seconds=1))
    other = sessionmaker(bind=pg_engine)()
    try:
        # Worker A holds the lock on the first due object; worker B skips it.
        first = other.scalars(
            select(MediaObject)
            .where(MediaObject.state == "deleting")
            .order_by(MediaObject.id)
            .limit(1)
            .with_for_update()
        ).one()
        outcomes = []
        while (outcome := media_cleanup.delete_one(db, storage, NOW)) is not None:
            outcomes.append(outcome)
        assert outcomes == [True]  # the other object of the pair
        assert {key for key, _ in states(db)} == {first.storage_key}
    finally:
        other.rollback()
        other.close()


def test_reconciliation_reports_unregistered_files_and_deletes_nothing(storage, db):
    known = stored(storage, db, "active")
    stray = new_key("brands", uuid.uuid4(), "png", b"stray")
    storage.put(stray, b"x", visibility="public", content_type="image/png")
    unknown = media_cleanup.reconcile(db, storage)
    assert unknown == [("public", stray)]
    assert storage.exists(stray, visibility="public")
    assert storage.exists(known.storage_key, visibility="public")


def test_one_worker_pass_sweeps_and_deletes(storage, db, pg_engine: Engine, monkeypatch):
    stored(storage, db, "deleting", delete_after=NOW - timedelta(seconds=1))
    factory = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(worker_module, "SessionLocal", factory)
    monkeypatch.setattr(worker_module, "get_media_storage", lambda: storage)
    worker = worker_module.Worker()
    assert worker.run_once() is True
    assert states(db) == [] and files(storage) == 0
    assert worker.run_once() is False  # nothing left to do
