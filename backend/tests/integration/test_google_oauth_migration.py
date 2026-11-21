"""d5a9c3e7f2b8 (Continue with Google, ADR-006 amendment 2026-11-11) on a disposable per-test
schema: it adds two tables, round-trips, refuses to drop linked identities, and the models match
the migrated schema."""

import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from tests.integration.test_payment_migration import _alembic, _head

BEFORE = "a9d3f7c2e5b8"  # category spotlight product, the parent on dev
GOOGLE = "d5a9c3e7f2b8"
# The newest revision (email verification, 2026-11-12): a refused downgrade leaves the schema here.


def _user(engine: Engine, email: str = "a@example.com") -> uuid.UUID:
    """A verified account where the column exists (2026-11-12), so later revisions' downgrade
    guards do not stop these downgrades."""
    user_id = uuid.uuid4()
    verified = "email_verified_at" in {c["name"] for c in inspect(engine).get_columns("users")}
    with engine.begin() as conn:
        if verified:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, email_verified_at) VALUES (:id, :email, now())"
                ),
                {"id": user_id, "email": email},
            )
        else:
            conn.execute(
                text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                {"id": user_id, "email": email},
            )
    return user_id


def _identity(engine: Engine, user_id: uuid.UUID, subject: str = "s1") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO oauth_identities (id, user_id, provider, subject) "
                "VALUES (:id, :user, 'google', :subject)"
            ),
            {"id": uuid.uuid4(), "user": user_id, "subject": subject},
        )


def test_the_tables_round_trip(pg_engine: Engine) -> None:
    tables = set(inspect(pg_engine).get_table_names())
    assert {"oauth_identities", "oauth_login_flows"} <= tables
    _alembic(pg_engine, "downgrade", BEFORE)
    tables = set(inspect(pg_engine).get_table_names())
    assert not {"oauth_identities", "oauth_login_flows"} & tables
    _alembic(pg_engine, "upgrade", GOOGLE)
    assert "oauth_identities" in inspect(pg_engine).get_table_names()


def test_the_downgrade_refuses_while_google_identities_exist(pg_engine: Engine) -> None:
    _identity(pg_engine, _user(pg_engine))
    with pytest.raises(RuntimeError, match="Google sign-in identities exist"):
        _alembic(pg_engine, "downgrade", BEFORE)
    assert "oauth_identities" in inspect(pg_engine).get_table_names()


def test_one_google_account_per_user_and_one_user_per_google_account(pg_engine: Engine) -> None:
    first, second = _user(pg_engine), _user(pg_engine, "b@example.com")
    _identity(pg_engine, first, "s1")
    with pytest.raises(IntegrityError):
        _identity(pg_engine, second, "s1")  # the same Google account twice
    with pytest.raises(IntegrityError):
        _identity(pg_engine, first, "s2")  # a second Google account for one user


@pytest.mark.parametrize(
    "values",
    [
        "'github', 'login', NULL",  # unknown provider
        "'google', 'admin', NULL",  # unknown purpose
        "'google', 'link', NULL",  # a link flow without its user
    ],
)
def test_flow_constraints(pg_engine: Engine, values: str) -> None:
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO oauth_login_flows (id, provider, purpose, user_id, state_hash, "
                f"flow_token_hash, nonce_hash, expires_at) VALUES (:id, {values}, 'a', 'b', 'c', "
                "now())"
            ),
            {"id": uuid.uuid4()},
        )


def test_states_are_unique(pg_engine: Engine) -> None:
    insert = text(
        "INSERT INTO oauth_login_flows (id, provider, purpose, state_hash, flow_token_hash, "
        "nonce_hash, expires_at) VALUES (:id, 'google', 'login', 'same', 'b', 'c', now())"
    )
    with pg_engine.begin() as conn:
        conn.execute(insert, {"id": uuid.uuid4()})
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(insert, {"id": uuid.uuid4()})


def test_models_match_the_migrated_schema(pg_engine: Engine) -> None:
    _alembic(pg_engine, "check")  # raises if autogenerate would find any difference


def _columns(engine: Engine, table: str) -> dict[str, tuple[str, bool]]:
    return {c["name"]: (str(c["type"]), c["nullable"]) for c in inspect(engine).get_columns(table)}


def test_upgrade_from_the_parent_keeps_existing_users_and_builds_the_expected_schema(
    pg_engine: Engine,
) -> None:
    _alembic(pg_engine, "downgrade", BEFORE)
    user_id = _user(pg_engine)  # an existing account before the upgrade
    _alembic(pg_engine, "upgrade", GOOGLE)
    with pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id}) == 1
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == GOOGLE

    assert _columns(pg_engine, "oauth_identities") == {
        "id": ("UUID", False),
        "created_at": ("TIMESTAMP", False),
        "updated_at": ("TIMESTAMP", False),
        "user_id": ("UUID", False),
        "provider": ("VARCHAR(16)", False),
        "subject": ("VARCHAR(255)", False),
        "email": ("VARCHAR(320)", True),
        "last_login_at": ("TIMESTAMP", True),
    }
    assert _columns(pg_engine, "oauth_login_flows") == {
        "id": ("UUID", False),
        "created_at": ("TIMESTAMP", False),
        "updated_at": ("TIMESTAMP", False),
        "provider": ("VARCHAR(16)", False),
        "purpose": ("VARCHAR(8)", False),
        "state_hash": ("VARCHAR(64)", False),
        "flow_token_hash": ("VARCHAR(64)", False),
        "nonce_hash": ("VARCHAR(64)", False),
        "code_verifier": ("VARCHAR(128)", True),
        "user_id": ("UUID", True),
        "expires_at": ("TIMESTAMP", False),
        "consumed_at": ("TIMESTAMP", True),
    }
    insp = inspect(pg_engine)
    for table in ("oauth_identities", "oauth_login_flows"):
        [fk] = insp.get_foreign_keys(table)
        assert fk["referred_table"] == "users" and fk["constrained_columns"] == ["user_id"]
        assert fk["referred_columns"] == ["id"]
        assert fk["options"].get("ondelete") == "CASCADE"
        assert insp.get_pk_constraint(table)["constrained_columns"] == ["id"]
    assert {
        (u["name"], tuple(u["column_names"]))
        for u in insp.get_unique_constraints("oauth_identities")
    } == {
        ("uq_oauth_identities_provider_subject", ("provider", "subject")),
        ("uq_oauth_identities_user_id_provider", ("user_id", "provider")),
    }
    assert {
        (u["name"], tuple(u["column_names"]))
        for u in insp.get_unique_constraints("oauth_login_flows")
    } == {("uq_oauth_login_flows_state_hash", ("state_hash",))}
    # The expiry index for purging, plus the index backing the unique state constraint.
    flow_indexes = {
        (ix["name"], tuple(ix["column_names"]), ix["unique"])
        for ix in insp.get_indexes("oauth_login_flows")
    }
    assert flow_indexes == {
        ("ix_oauth_login_flows_expires_at", ("expires_at",), False),
        ("uq_oauth_login_flows_state_hash", ("state_hash",), True),
    }
    assert {c["name"] for c in insp.get_check_constraints("oauth_identities")} == {
        "ck_oauth_identities_valid_provider"
    }
    assert {c["name"] for c in insp.get_check_constraints("oauth_login_flows")} == {
        "ck_oauth_login_flows_valid_provider",
        "ck_oauth_login_flows_valid_purpose",
        "ck_oauth_login_flows_link_flow_has_user",
    }


def test_downgrade_succeeds_without_identities_even_with_flows_then_upgrades_again(
    pg_engine: Engine,
) -> None:
    user_id = _user(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO oauth_login_flows (id, provider, purpose, user_id, state_hash, "
                "flow_token_hash, nonce_hash, expires_at) VALUES (:id, 'google', 'link', :user, "
                "'a', 'b', 'c', now())"
            ),
            {"id": uuid.uuid4(), "user": user_id},
        )
    _alembic(pg_engine, "downgrade", BEFORE)  # short-lived flows may go; nobody loses a sign-in
    tables = set(inspect(pg_engine).get_table_names())
    assert not {"oauth_identities", "oauth_login_flows"} & tables
    with pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id}) == 1
    _alembic(pg_engine, "upgrade", "head")
    _alembic(pg_engine, "check")


def test_a_refused_downgrade_changes_nothing(pg_engine: Engine) -> None:
    user_id = _user(pg_engine)
    _identity(pg_engine, user_id)
    with pytest.raises(RuntimeError):
        _alembic(pg_engine, "downgrade", BEFORE)
    with pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == _head()
        assert conn.scalar(text("SELECT count(*) FROM oauth_identities")) == 1
    # Once the identity is gone the same downgrade succeeds.
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM oauth_identities"))
    _alembic(pg_engine, "downgrade", BEFORE)
    _alembic(pg_engine, "upgrade", "head")
