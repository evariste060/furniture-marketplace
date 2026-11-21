"""Payment event metadata migration (module 15, revision a7c2e9d4f6b8). Disposable per-test
schema of the *_test database (tests/conftest.py pg_engine)."""

import os
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from alembic import command
from app.core.config import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
BEFORE = "f3a8c6e1b5d9"
PAYMENTS = "a7c2e9d4f6b8"


def _alembic(engine: Engine, action: str, *args: str) -> None:
    previous = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    try:
        getattr(command, action)(Config(str(ALEMBIC_INI)), *args)
    finally:
        os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def _head() -> str:
    """The newest revision: where `upgrade head` ends and where a refused downgrade stays."""
    head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    assert head is not None, "alembic has no single head revision"
    return head


def _columns(engine: Engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("payment_events")}


def _event(engine: Engine) -> str:
    event_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO payment_events (id, provider, event_key, received_at) "
                "VALUES (:id, 'mock', :key, now())"
            ),
            {"id": event_id, "key": f"evt-{event_id}"},
        )
    return event_id


def test_the_column_defaults_to_an_empty_object_and_survives_a_round_trip(pg_engine: Engine):
    assert "payload_metadata" in _columns(pg_engine)
    kept = _event(pg_engine)
    _alembic(pg_engine, "downgrade", BEFORE)
    assert "payload_metadata" not in _columns(pg_engine)
    _alembic(pg_engine, "upgrade", PAYMENTS)
    with pg_engine.connect() as conn:
        value: object = conn.execute(
            text("SELECT payload_metadata FROM payment_events WHERE id = :id"), {"id": kept}
        ).scalar_one()
    assert value == {}  # existing events keep their rows; the new column starts empty


def test_alembic_check_finds_no_drift(pg_engine: Engine):
    _alembic(pg_engine, "check")
