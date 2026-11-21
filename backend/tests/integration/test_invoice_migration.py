"""Invoices migration (module 16, revision c5e8a2d7f4b1). Disposable per-test schema of the *_test
database (tests/conftest.py pg_engine)."""

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from tests.integration.test_payment_migration import _alembic

BEFORE = "a7c2e9d4f6b8"
INVOICES = "c5e8a2d7f4b1"


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_the_tables_are_created_and_removed_by_a_round_trip(pg_engine: Engine):
    assert {"invoices", "invoice_counters"} <= _tables(pg_engine)
    _alembic(pg_engine, "downgrade", BEFORE)
    assert not {"invoices", "invoice_counters"} & _tables(pg_engine)
    _alembic(pg_engine, "upgrade", INVOICES)
    assert {"invoices", "invoice_counters"} <= _tables(pg_engine)
    inspector = inspect(pg_engine)
    unique = {tuple(u["column_names"]) for u in inspector.get_unique_constraints("invoices")}
    assert {("order_id",), ("invoice_number",)} <= unique
    [fk] = inspector.get_foreign_keys("invoices")
    assert fk["referred_table"] == "orders" and fk["options"].get("ondelete") == "RESTRICT"
    assert inspector.get_pk_constraint("invoice_counters")["constrained_columns"] == ["year"]


def test_alembic_check_finds_no_drift(pg_engine: Engine):
    _alembic(pg_engine, "check")
