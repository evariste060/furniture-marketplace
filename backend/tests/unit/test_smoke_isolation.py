"""The smoke script must only ever target a confirmed, disposable, local test database."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_postgres_live.py"
_spec = importlib.util.spec_from_file_location("verify_postgres_live", SCRIPT)
assert _spec is not None
assert _spec.loader is not None
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)

SMOKE = "postgresql+psycopg://app_test:x@127.0.0.1:55432/rwanda_smoke_test"
OWNER = "postgresql+psycopg://owner_test:y@127.0.0.1:55432/rwanda_smoke_test"
DEV_DOTENV = {
    "APP_ENV": "development",
    "DATABASE_URL": "postgresql+psycopg://rwanda_app:z@127.0.0.1:55432/rwanda_ecommerce",
    "MIGRATION_DATABASE_URL": "postgresql+psycopg://rwanda_dev:z@127.0.0.1:55432/rwanda_ecommerce",
}


def env(**overrides) -> dict:
    values = {
        "SMOKE_DATABASE_URL": SMOKE,
        "SMOKE_OWNER_DATABASE_URL": OWNER,
        "SMOKE_CONFIRM_DISPOSABLE": "rwanda_smoke_test",
    }
    values.update(overrides)
    return {k: v for k, v in values.items() if v is not None}


def test_accepts_a_confirmed_local_test_database():
    runtime, owner = smoke.resolve_target(env(), DEV_DOTENV)
    assert (runtime.username, owner.username) == ("app_test", "owner_test")
    assert runtime.database == "rwanda_smoke_test"


def test_owner_url_defaults_to_the_runtime_url():
    runtime, owner = smoke.resolve_target(env(SMOKE_OWNER_DATABASE_URL=None), {})
    assert runtime == owner


@pytest.mark.parametrize(
    ("overrides", "dotenv", "reason"),
    [
        ({"SMOKE_DATABASE_URL": None}, DEV_DOTENV, "Set SMOKE_DATABASE_URL"),
        ({"SMOKE_DATABASE_URL": "not a url"}, DEV_DOTENV, "not valid"),
        (  # the normal development database
            {
                "SMOKE_DATABASE_URL": DEV_DOTENV["DATABASE_URL"],
                "SMOKE_OWNER_DATABASE_URL": DEV_DOTENV["MIGRATION_DATABASE_URL"],
                "SMOKE_CONFIRM_DISPOSABLE": "rwanda_ecommerce",
            },
            DEV_DOTENV,
            "must end in _test",
        ),
        (
            {
                "SMOKE_DATABASE_URL": SMOKE.replace("127.0.0.1", "db.staging.internal"),
                "SMOKE_OWNER_DATABASE_URL": OWNER.replace("127.0.0.1", "db.staging.internal"),
            },
            DEV_DOTENV,
            "not loopback",
        ),
        ({"APP_ENV": "staging"}, DEV_DOTENV, "only in development"),
        ({}, {**DEV_DOTENV, "APP_ENV": "production"}, "only in development"),
        ({"SMOKE_CONFIRM_DISPOSABLE": None}, DEV_DOTENV, "SMOKE_CONFIRM_DISPOSABLE"),
        ({"SMOKE_CONFIRM_DISPOSABLE": "yes"}, DEV_DOTENV, "SMOKE_CONFIRM_DISPOSABLE"),
        (
            {"SMOKE_OWNER_DATABASE_URL": OWNER.replace("rwanda_smoke_test", "other_test")},
            DEV_DOTENV,
            "same database",
        ),
        (  # a _test database that backend/.env uses as the app database
            {},
            {**DEV_DOTENV, "DATABASE_URL": SMOKE.replace("app_test", "someone")},
            "configured in DATABASE_URL",
        ),
        (
            {},
            {**DEV_DOTENV, "MIGRATION_DATABASE_URL": OWNER.replace("owner_test", "someone")},
            "configured in MIGRATION_DATABASE_URL",
        ),
        ({"DATABASE_URL": SMOKE}, DEV_DOTENV, "configured in DATABASE_URL"),
        ({}, {**DEV_DOTENV, "DATABASE_URL": "::garbage::"}, "isolation cannot be verified"),
    ],
)
def test_refuses_unless_isolation_is_verified(overrides, dotenv, reason):
    with pytest.raises(smoke.SmokeRefused, match=reason):
        smoke.resolve_target(env(**overrides), dotenv)


def test_generated_credentials_are_random_and_meet_policy():
    from app.core.security import validate_password_strength

    passwords = {smoke.random_password() for _ in range(50)}
    assert len(passwords) == 50
    assert all(validate_password_strength(p)[0] for p in passwords)
    assert all(smoke.random_phone().startswith("+2507") for _ in range(5))


def test_script_contains_no_fixed_passwords():
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"password": "' not in source
    assert 'hash_password("' not in source
