"""e6b1d4a8c2f7 (email verification, ADR-006 amendment 2026-11-12) on a disposable per-test
schema: existing accounts stay verified, the table round-trips, the downgrade refuses while
customers wait for verification, and the models match the migrated schema."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from tests.integration.test_payment_migration import _alembic, _head

BEFORE = "d5a9c3e7f2b8"  # Continue with Google
VERIFY = "e6b1d4a8c2f7"
CREATED = datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)


def _user(engine: Engine, email: str | None, phone: str | None = None, staff: bool = False):
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, phone, is_staff, created_at, updated_at) "
                "VALUES (:id, :email, :phone, :staff, :created, :created)"
            ),
            {"id": user_id, "email": email, "phone": phone, "staff": staff, "created": CREATED},
        )
    return user_id


def _verified_at(engine: Engine, user_id: uuid.UUID):
    with engine.connect() as conn:
        return conn.scalar(
            text("SELECT email_verified_at FROM users WHERE id = :id"), {"id": user_id}
        )


def test_existing_accounts_stay_verified_through_the_upgrade(pg_engine: Engine) -> None:
    _alembic(pg_engine, "downgrade", BEFORE)
    customer = _user(pg_engine, "old.customer@example.com")
    staff = _user(pg_engine, "old.staff@example.com", staff=True)
    phone_only = _user(pg_engine, None, "+250788000001")
    _alembic(pg_engine, "upgrade", VERIFY)
    # Verified as of their creation: nobody who could sign in before is locked out now.
    assert _verified_at(pg_engine, customer) == CREATED
    assert _verified_at(pg_engine, staff) == CREATED
    assert _verified_at(pg_engine, phone_only) is None  # no email, nothing to verify
    with pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM users")) == 3  # no row lost
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == VERIFY


def test_the_schema_round_trips(pg_engine: Engine) -> None:
    insp = inspect(pg_engine)
    assert "email_verification_tokens" in insp.get_table_names()
    assert "email_verified_at" in {c["name"] for c in insp.get_columns("users")}
    _alembic(pg_engine, "downgrade", BEFORE)
    insp = inspect(pg_engine)
    assert "email_verification_tokens" not in insp.get_table_names()
    assert "email_verified_at" not in {c["name"] for c in insp.get_columns("users")}
    _alembic(pg_engine, "upgrade", "head")
    _alembic(pg_engine, "check")  # the models match the migrated schema


def test_the_built_schema(pg_engine: Engine) -> None:
    insp = inspect(pg_engine)
    columns = {
        c["name"]: (str(c["type"]), c["nullable"])
        for c in insp.get_columns("email_verification_tokens")
    }
    assert columns == {
        "id": ("UUID", False),
        "created_at": ("TIMESTAMP", False),
        "updated_at": ("TIMESTAMP", False),
        "user_id": ("UUID", False),
        "email": ("VARCHAR(320)", False),
        "token_hash": ("VARCHAR(64)", False),
        "expires_at": ("TIMESTAMP", False),
        "consumed_at": ("TIMESTAMP", True),
        "revoked_at": ("TIMESTAMP", True),
    }
    [fk] = insp.get_foreign_keys("email_verification_tokens")
    assert fk["referred_table"] == "users" and fk["options"].get("ondelete") == "CASCADE"
    assert {u["name"] for u in insp.get_unique_constraints("email_verification_tokens")} == {
        "uq_email_verification_tokens_token_hash"
    }
    assert {c["name"] for c in insp.get_check_constraints("email_verification_tokens")} == {
        "ck_email_verification_tokens_consumed_or_revoked_not_both"
    }
    indexes = {i["name"] for i in insp.get_indexes("email_verification_tokens")}
    assert "ix_email_verification_tokens_user_created" in indexes


def _token(engine: Engine, user_id: uuid.UUID, token_hash: str, **extra) -> None:
    columns = {"id": uuid.uuid4(), "user": user_id, "hash": token_hash, **extra}
    names = ", ".join(["consumed_at", "revoked_at"][: len(extra)])
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO email_verification_tokens (id, user_id, email, token_hash, expires_at"
                + (f", {names}" if names else "")
                + ") VALUES (:id, :user, 'a@example.com', :hash, now() + interval '1 day'"
                + "".join(f", :{k}" for k in extra)
                + ")"
            ),
            columns,
        )


def test_token_digests_are_unique(pg_engine: Engine) -> None:
    user = _user(pg_engine, "a@example.com")
    _token(pg_engine, user, "same")
    with pytest.raises(IntegrityError):
        _token(pg_engine, user, "same")


def test_a_token_is_never_both_used_and_revoked(pg_engine: Engine) -> None:
    user = _user(pg_engine, "a@example.com")
    now = datetime.now(UTC)
    with pytest.raises(IntegrityError):
        _token(pg_engine, user, "h1", consumed_at=now, revoked_at=now)


def test_deleting_a_user_removes_their_tokens(pg_engine: Engine) -> None:
    user = _user(pg_engine, "a@example.com")
    _token(pg_engine, user, "h2")
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user})
        assert conn.scalar(text("SELECT count(*) FROM email_verification_tokens")) == 0


def test_the_downgrade_refuses_while_customers_wait_for_verification(pg_engine: Engine) -> None:
    waiting = _user(pg_engine, "waiting@example.com")
    with pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET email_verified_at = NULL WHERE id = :id"), {"id": waiting}
        )
    with pytest.raises(RuntimeError, match="have not verified their email"):
        _alembic(pg_engine, "downgrade", BEFORE)
    with pg_engine.connect() as conn:  # refused: nothing changed, later revisions included
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == _head()
    # Unverified staff do not block it (staff are never asked to verify), nor phone-only accounts.
    with pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET email_verified_at = :at WHERE id = :id"),
            {"at": CREATED + timedelta(days=1), "id": waiting},
        )
    _user(pg_engine, "staff.unverified@example.com", staff=True)
    _user(pg_engine, None, "+250788000002")
    _alembic(pg_engine, "downgrade", BEFORE)
    _alembic(pg_engine, "upgrade", "head")
