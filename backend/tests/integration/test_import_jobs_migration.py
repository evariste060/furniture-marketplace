"""Catalogue import jobs migration (module 8, revision 9d820b74f718).

Runs on the disposable per-test schema of the *_test database (tests/conftest.py pg_engine).
"""

import json
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from tests.integration.test_image_media_migration import _alembic

BEFORE = "76768b844c03"
IMPORTS = "9d820b74f718"


def _user(engine: Engine) -> str:
    user_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, full_name, password_hash, is_staff) "
                "VALUES (:id, :email, 'Importer', 'x', true)"
            ),
            {"id": user_id, "email": f"{user_id}@pg.test"},
        )
    return user_id


def _insert(engine: Engine, user_id: str, **overrides) -> None:
    values = {
        "id": str(uuid4()),
        "user": user_id,
        "filename": "a.csv",
        "file_format": "csv",
        "status": "processing",
        "total_rows": 0,
        "imported_rows": 0,
        "error_rows": 0,
        "errors": "[]",
        "finished_at": None,
    }
    values.update(overrides)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO import_jobs (id, created_by_user_id, filename, file_format, status, "
                "total_rows, imported_rows, error_rows, errors, finished_at) VALUES (:id, :user, "
                ":filename, :file_format, :status, :total_rows, :imported_rows, :error_rows, "
                "CAST(:errors AS jsonb), :finished_at)"
            ),
            values,
        )


def test_upgrade_downgrade_upgrade(pg_engine: Engine):
    assert "import_jobs" in inspect(pg_engine).get_table_names()  # the fixture migrates to head
    _alembic(pg_engine, "downgrade", BEFORE)
    assert "import_jobs" not in inspect(pg_engine).get_table_names()
    _alembic(pg_engine, "upgrade", IMPORTS)
    assert "import_jobs" in inspect(pg_engine).get_table_names()
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == IMPORTS


def test_defaults_and_a_valid_finished_job(pg_engine: Engine):
    user_id = _user(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO import_jobs (id, created_by_user_id, filename, file_format) "
                "VALUES (:id, :user, 'a.xlsx', 'xlsx')"
            ),
            {"id": str(uuid4()), "user": user_id},
        )
        row = conn.execute(
            text(
                "SELECT status, total_rows, imported_rows, error_rows, errors, errors_truncated, "
                "finished_at FROM import_jobs"
            )
        ).one()
    assert tuple(row) == ("processing", 0, 0, 0, [], False, None)
    _insert(
        pg_engine,
        user_id,
        status="completed",
        total_rows=3,
        imported_rows=2,
        error_rows=1,
        errors=json.dumps([{"row": 2, "field": "price", "message": "x"}]),
        finished_at="2026-10-24T09:00:00Z",
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"file_format": "xls"},
        {"status": "done"},
        {"total_rows": -1},
        {"total_rows": 1, "imported_rows": 1, "error_rows": 1},
        {"errors": '{"row": 1}'},
        {"errors": json.dumps([{"row": i} for i in range(1001)])},
        {"status": "completed"},  # final status without finished_at
        {"finished_at": "2026-10-24T09:00:00Z"},  # processing with finished_at
    ],
    ids=[
        "format",
        "status",
        "negative",
        "counts-over-total",
        "errors-not-array",
        "errors-over-cap",
        "final-unfinished",
        "processing-finished",
    ],
)
def test_constraints_reject_invalid_jobs(pg_engine: Engine, overrides: dict):
    user_id = _user(pg_engine)
    with pytest.raises(IntegrityError):
        _insert(pg_engine, user_id, **overrides)


def test_a_user_with_import_jobs_cannot_be_deleted(pg_engine: Engine):
    user_id = _user(pg_engine)
    _insert(pg_engine, user_id)
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


def test_models_match_the_migrated_schema(pg_engine: Engine):
    _alembic(pg_engine, "check")
