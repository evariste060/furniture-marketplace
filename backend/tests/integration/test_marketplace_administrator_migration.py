"""SC-05 migration a9d3f5b7c1e2: the Marketplace Administrator is the only staff role.

Runs on the disposable per-test schema of the *_test database (tests/conftest.py pg_engine). The
upgrade refuses, changing nothing, while a staff assignment holds another role; it never
converts, disables or deletes an account.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from tests.integration.test_image_media_migration import _alembic

SC05 = "a9d3f5b7c1e2"
BEFORE = "f4c8a2e6b9d3"


def _staff(engine: Engine, role: str) -> str:
    user_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, is_staff, is_active) "
                "VALUES (:id, :email, 'x', 'Staff Member', true, true)"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        conn.execute(
            text(
                "INSERT INTO staff_role_assignments (id, user_id, role) VALUES (:id, :user, :role)"
            ),
            {"id": str(uuid4()), "user": user_id, "role": role},
        )
    return user_id


def _roles(engine: Engine) -> list[tuple[str, str, bool]]:
    with engine.begin() as conn:
        return [
            (str(user_id), str(role), bool(active))
            for user_id, role, active in conn.execute(
                text(
                    "SELECT u.id, s.role, u.is_active FROM staff_role_assignments s "
                    "JOIN users u ON u.id = s.user_id ORDER BY u.id"
                )
            )
        ]


def _revision(engine: Engine) -> str:
    with engine.begin() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_only_the_administrator_role_is_accepted_at_head(pg_engine: Engine):
    assert _revision(pg_engine) == SC05
    _staff(pg_engine, "administrator")
    for role in ("sales", "operations", "management", "finance", "customer"):
        with pytest.raises(IntegrityError, match="ck_staff_role_assignments_valid_role"):
            _staff(pg_engine, role)


def test_the_upgrade_refuses_and_changes_nothing_while_other_roles_exist(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", BEFORE)
    admin = _staff(pg_engine, "administrator")
    sales = _staff(pg_engine, "sales")
    finance_a = _staff(pg_engine, "finance")
    finance_b = _staff(pg_engine, "finance")
    before = _roles(pg_engine)

    with pytest.raises(RuntimeError) as refused:
        _alembic(pg_engine, "upgrade", SC05)
    message = str(refused.value)
    assert "finance: 2, sales: 1" in message and "No account was changed" in message
    for user_id in (admin, sales, finance_a, finance_b):
        assert user_id not in message  # counts only, never who holds a role
    assert _revision(pg_engine) == BEFORE
    assert _roles(pg_engine) == before  # nothing converted, disabled or deleted

    # Once the owner has dealt with those accounts deliberately, the upgrade goes through.
    with pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE staff_role_assignments SET role = 'administrator' WHERE user_id = :u"),
            {"u": sales},
        )
        retired = {"a": finance_a, "b": finance_b}
        conn.execute(text("DELETE FROM staff_role_assignments WHERE user_id IN (:a, :b)"), retired)
        conn.execute(text("UPDATE users SET is_staff = false WHERE id IN (:a, :b)"), retired)
    _alembic(pg_engine, "upgrade", SC05)
    assert _revision(pg_engine) == SC05
    assert {role for _, role, _ in _roles(pg_engine)} == {"administrator"}


def test_the_downgrade_restores_the_five_roles_without_changing_rows(pg_engine: Engine):
    admin = _staff(pg_engine, "administrator")
    _alembic(pg_engine, "downgrade", BEFORE)
    assert _roles(pg_engine) == [(admin, "administrator", True)]
    for role in ("sales", "operations", "management", "finance"):
        _staff(pg_engine, role)
    with pytest.raises(IntegrityError):
        _staff(pg_engine, "customer")
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM staff_role_assignments WHERE role <> 'administrator'"))
    _alembic(pg_engine, "upgrade", SC05)
    _alembic(pg_engine, "check")  # the models match the migrated schema
