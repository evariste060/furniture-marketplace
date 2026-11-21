"""The in-process smoke script, run for real against the disposable suite database.

It must refuse unconfirmed or real-looking databases without writing anything, never change
accounts it did not create, and leave none of its own run-scoped accounts behind.
"""

import os
import subprocess
import sys
import uuid
from urllib.parse import urlsplit

import pytest

from tests.postgres.conftest import BACKEND, REPO, Stack
from tests.postgres.test_pg_http import one

SCRIPT = REPO / "scripts" / "verify_postgres_live.py"
SNAPSHOT = (
    "SELECT u.id, u.email, u.phone, u.full_name, u.password_hash, u.is_active, u.is_staff, "
    "u.updated_at, s.role FROM users u LEFT JOIN staff_role_assignments s ON s.user_id = u.id "
    "ORDER BY u.id"
)


def run_smoke(stack: Stack, **overrides: str | None) -> subprocess.CompletedProcess:
    dbname = urlsplit(stack.owner_url).path.lstrip("/")
    # The suite's own DATABASE_URL settings are dropped: the script must not need them.
    env = {
        k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "MIGRATION_DATABASE_URL"}
    }
    env.update(
        SMOKE_DATABASE_URL=stack.runtime_url,
        SMOKE_OWNER_DATABASE_URL=stack.owner_url,
        SMOKE_CONFIRM_DISPOSABLE=dbname,
        SMOKE_REDIS_URL=stack.redis_url,
        APP_ENV="development",
    )
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def insert_user(conn, email: str, role: str | None) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO users (id, email, full_name, password_hash, is_staff) "
        "VALUES (%s, %s, 'Existing Account', 'not-a-usable-hash', %s)",
        (user_id, email, role is not None),
    )
    if role:
        conn.execute(
            "INSERT INTO staff_role_assignments (id, user_id, role) VALUES (%s, %s, %s)",
            (uuid.uuid4(), user_id, role),
        )
    return user_id


def delete_user(conn, user_id: uuid.UUID) -> None:
    conn.execute("DELETE FROM staff_role_assignments WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM users WHERE id = %s", (user_id,))


def test_smoke_run_keeps_existing_accounts_and_removes_its_own(stack: Stack, unique: str):
    with stack.owner() as conn:
        customer = insert_user(conn, f"existing.{unique}@kigali.rw", None)
        admin = insert_user(conn, f"existing.admin.{unique}@pg.test", "administrator")
        before = conn.execute(SNAPSHOT).fetchall()
        audit_before = one(conn, "SELECT count(*) FROM audit_records")[0]
    try:
        result = run_smoke(stack)
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
        assert "ALL 12 IN-PROCESS CHECKS PASSED" in result.stdout
        assert "password" not in (result.stdout + result.stderr).lower()
        with stack.owner() as conn:
            assert conn.execute(SNAPSHOT).fetchall() == before
            leftovers = "SELECT count(*) FROM users WHERE email LIKE 'smoke.%%@smoke.invalid'"
            assert one(conn, leftovers) == (0,)
            # Audit history is append-only and is kept.
            assert one(conn, "SELECT count(*) FROM audit_records")[0] > audit_before
    finally:
        with stack.owner() as conn:
            delete_user(conn, customer)
            delete_user(conn, admin)


def test_smoke_run_refuses_a_database_with_real_staff_accounts(stack: Stack, unique: str):
    with stack.owner() as conn:
        real_admin = insert_user(conn, f"real.admin.{unique}@kigali.rw", "administrator")
        before = conn.execute(SNAPSHOT).fetchall()
    try:
        result = run_smoke(stack)
        assert result.returncode == 2
        assert "may hold real accounts" in result.stderr
        with stack.owner() as conn:
            assert conn.execute(SNAPSHOT).fetchall() == before
    finally:
        with stack.owner() as conn:
            delete_user(conn, real_admin)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"SMOKE_CONFIRM_DISPOSABLE": None}, "SMOKE_CONFIRM_DISPOSABLE"),
        ({"SMOKE_DATABASE_URL": None, "SMOKE_OWNER_DATABASE_URL": None}, "SMOKE_DATABASE_URL"),
        ({"APP_ENV": "production"}, "only in development"),
    ],
)
def test_smoke_run_refuses_without_verified_isolation(stack: Stack, overrides, reason):
    with stack.owner() as conn:
        before = conn.execute(SNAPSHOT).fetchall()
    result = run_smoke(stack, **overrides)
    assert result.returncode == 2 and reason in result.stderr
    with stack.owner() as conn:
        assert conn.execute(SNAPSHOT).fetchall() == before
