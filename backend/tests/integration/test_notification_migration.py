"""Notification logs migration (module 17, revision e4b9c1f7a3d6), from the current `dev` head
(a1d9c3e5f7b2, the merge of payments/invoices and frontend phase 1). Disposable per-test
schema of the *_test database (tests/conftest.py pg_engine)."""

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from tests.integration.test_payment_migration import _alembic

BEFORE = "a1d9c3e5f7b2"
NOTIFICATIONS = "e4b9c1f7a3d6"


def test_the_table_is_created_and_removed_by_a_round_trip(pg_engine: Engine):
    assert "notification_logs" in inspect(pg_engine).get_table_names()
    _alembic(pg_engine, "downgrade", BEFORE)
    assert "notification_logs" not in inspect(pg_engine).get_table_names()
    _alembic(pg_engine, "upgrade", NOTIFICATIONS)
    inspector = inspect(pg_engine)
    unique = {
        tuple(u["column_names"]) for u in inspector.get_unique_constraints("notification_logs")
    }
    assert ("order_id", "event", "channel") in unique
    [fk] = inspector.get_foreign_keys("notification_logs")
    assert fk["referred_table"] == "orders" and fk["options"].get("ondelete") == "RESTRICT"
    indexes = {i["name"]: i for i in inspector.get_indexes("notification_logs")}
    assert indexes["ix_notification_logs_due"]["column_names"] == ["next_attempt_at"]
    assert {"ix_notification_logs_created", "ix_notification_logs_status_created"} <= set(indexes)
    columns = {c["name"]: c for c in inspector.get_columns("notification_logs")}
    for name in ("next_attempt_at", "claimed_until", "sent_at", "created_at", "updated_at"):
        assert getattr(columns[name]["type"], "timezone", False), name  # timezone-aware timestamps
    checks = {c["name"] for c in inspector.get_check_constraints("notification_logs")}
    assert {
        "ck_notification_logs_valid_event",
        "ck_notification_logs_valid_channel",
        "ck_notification_logs_valid_status",
        "ck_notification_logs_attempts_bounded",
        "ck_notification_logs_recipient_matches_channel",
    } <= checks


def test_alembic_check_finds_no_drift(pg_engine: Engine):
    _alembic(pg_engine, "check")
