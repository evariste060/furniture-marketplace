"""Checkout request hash migration (module 14, revision f3a8c6e1b5d9). Disposable per-test
schema of the *_test database (tests/conftest.py pg_engine)."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.config import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
BEFORE = "d2f7a9c4e8b1"
CHECKOUT = "f3a8c6e1b5d9"


def _alembic(engine: Engine, action: str, *args: str) -> None:
    previous = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    try:
        getattr(command, action)(Config(str(ALEMBIC_INI)), *args)
    finally:
        os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def _order(engine: Engine, request_hash: str | None = None) -> str:
    order_id = str(uuid4())
    columns = "id, order_number, checkout_idempotency_key, subtotal, total, recipient_name, "
    columns += "recipient_phone, delivery_address_snapshot"
    values = ":id, :n, :k, 0, 0, 'R', '+250780000000', '{}'"
    params = {"id": order_id, "n": f"T-{order_id[:8]}", "k": f"k-{order_id}"}
    if request_hash is not None:
        columns += ", checkout_request_hash"
        values += ", :h"
        params["h"] = request_hash
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO orders ({columns}) VALUES ({values})"), params)
    return order_id


def _columns(engine: Engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("orders")}


def test_head_has_the_hash_column_and_its_check(pg_engine: Engine):
    assert "checkout_request_hash" in _columns(pg_engine)
    _order(pg_engine, "a" * 64)
    _order(pg_engine)  # legacy orders keep NULL
    for bad in ("A" * 64, "a" * 63, "not-hex" * 9):
        with pytest.raises(IntegrityError):
            _order(pg_engine, bad)


def test_downgrade_and_upgrade_keep_existing_orders(pg_engine: Engine):
    kept = _order(pg_engine, "b" * 64)
    _alembic(pg_engine, "downgrade", BEFORE)
    assert "checkout_request_hash" not in _columns(pg_engine)
    _alembic(pg_engine, "upgrade", CHECKOUT)
    with pg_engine.connect() as conn:
        row = conn.execute(
            text("SELECT checkout_request_hash FROM orders WHERE id = :id"), {"id": kept}
        ).one()
    assert row[0] is None  # the value is dropped with the column; the order itself is kept


def test_alembic_check_finds_no_drift(pg_engine: Engine):
    _alembic(pg_engine, "check")
