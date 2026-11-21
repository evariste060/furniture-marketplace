"""Job queue migration (revision d5f9b3c7e1a2; checkpoint 1b topic 4, 2026-10-26).

Runs on the disposable per-test schema of the *_test database (tests/conftest.py pg_engine).
"""

from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from tests.integration.test_image_media_migration import _alembic

BEFORE = "c4e8f2a6b9d1"


def _user(conn) -> str:
    user_id = str(uuid4())
    conn.execute(
        text(
            "INSERT INTO users (id, email, password_hash, full_name, is_staff, is_active) "
            "VALUES (:id, :email, 'x', 'Staff Member', true, true)"
        ),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    return user_id


def _job(conn, user_id: str, **values) -> str:
    job_id = str(uuid4())
    row = {"type": "bulk_image_upload", "state": "queued", "finished_at": None, **values}
    conn.execute(
        text(
            "INSERT INTO jobs (id, type, state, created_by_user_id, total_items, finished_at) "
            "VALUES (:id, :type, :state, :user, 1, :finished_at)"
        ),
        {"id": job_id, "user": user_id, **row},
    )
    return job_id


def _item(conn, job_id: str, index: int = 0, **values) -> None:
    row = {"state": "queued", "locked_at": None, **values}
    conn.execute(
        text(
            "INSERT INTO job_items (id, job_id, item_index, state, locked_at) "
            "VALUES (:id, :job, :index, :state, :locked_at)"
        ),
        {"id": str(uuid4()), "job": job_id, "index": index, **row},
    )


def test_downgrade_drops_the_queue_and_upgrade_restores_it(pg_engine: Engine):
    assert {"jobs", "job_items"} <= set(inspect(pg_engine).get_table_names())
    _alembic(pg_engine, "downgrade", BEFORE)
    assert {"jobs", "job_items"}.isdisjoint(inspect(pg_engine).get_table_names())
    _alembic(pg_engine, "upgrade", "head")
    assert {"jobs", "job_items"} <= set(inspect(pg_engine).get_table_names())


@pytest.mark.parametrize(
    "job_values",
    [{"type": "email_blast"}, {"state": "done"}, {"state": "finished"}],
    ids=["unknown-type", "unknown-state", "finished-without-time"],
)
def test_job_constraints(pg_engine: Engine, job_values: dict):
    with pg_engine.begin() as conn:
        user = _user(conn)
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        _job(conn, user, **job_values)


def test_item_constraints_and_one_item_per_index(pg_engine: Engine):
    with pg_engine.begin() as conn:
        job = _job(conn, _user(conn))
        _item(conn, job, 0)
    for values in ({"state": "processing"}, {"state": "lost"}, {"locked_at": "2026-01-01"}):
        with pytest.raises(IntegrityError), pg_engine.begin() as conn:
            _item(conn, job, 1, **values)
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        _item(conn, job, 0)  # (job_id, item_index) is unique: an item exists once
