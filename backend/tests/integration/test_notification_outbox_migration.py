"""Notification outbox migration (revision c7e2a9f4d1b6, approved 2026-11-02): existing order
messages are kept with their subject and dedupe key, and the downgrade refuses rather than
dropping messages of the newer kinds. Disposable per-test schema (tests/conftest.py pg_engine)."""

import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.integration.test_payment_migration import _alembic
from tests.support.commerce import new_order, seed_sku

BEFORE = "b2f6d8e4a1c9"
OUTBOX = "c7e2a9f4d1b6"


def _order(engine: Engine) -> uuid.UUID:
    with Session(engine) as db:
        variant = seed_sku(db, on_hand=5)
        order = new_order({variant.id: 1})
        db.add(order)
        db.commit()
        return order.id


def _old_row(engine: Engine, order_id: uuid.UUID, event: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO notification_logs (id, order_id, event, channel, recipient, status, "
                "attempts, next_attempt_at) VALUES (:id, :order_id, :event, 'sms', "
                "'+250788123456', 'pending', 0, now())"
            ),
            {"id": uuid.uuid4(), "order_id": order_id, "event": event},
        )


def test_existing_order_messages_keep_their_identity(pg_engine: Engine):
    order_id = _order(pg_engine)
    _alembic(pg_engine, "downgrade", BEFORE)
    _old_row(pg_engine, order_id, "confirmed")
    _alembic(pg_engine, "upgrade", OUTBOX)
    with pg_engine.connect() as conn:
        row = conn.execute(
            text("SELECT subject_type, subject_id, dedupe_key, order_id FROM notification_logs")
        ).one()
    assert row.subject_type == "order" and row.subject_id == row.order_id == order_id
    assert row.dedupe_key == f"order:{order_id}:confirmed:sms"  # the key the API uses
    columns = {c["name"]: c for c in inspect(pg_engine).get_columns("notification_logs")}
    assert columns["order_id"]["nullable"] and not columns["dedupe_key"]["nullable"]
    unique = {
        tuple(u["column_names"])
        for u in inspect(pg_engine).get_unique_constraints("notification_logs")
    }
    assert ("dedupe_key",) in unique and ("order_id", "event", "channel") not in unique


def test_constraints_keep_order_messages_and_subjects_consistent(pg_engine: Engine):
    order_id = _order(pg_engine)
    insert = text(
        "INSERT INTO notification_logs (id, order_id, subject_type, subject_id, dedupe_key, "
        "event, channel, recipient, status, attempts, next_attempt_at) VALUES (:id, :order_id, "
        ":type, :subject, :key, :event, 'email', 'a@example.rw', 'pending', 0, now())"
    )
    other = uuid.uuid4()
    bad: list[dict[str, object]] = [
        {"order_id": None, "type": "order", "subject": order_id, "event": "received"},
        {"order_id": order_id, "type": "user", "subject": order_id, "event": "welcome"},
        {"order_id": order_id, "type": "order", "subject": other, "event": "received"},
        {"order_id": None, "type": "user", "subject": other, "event": "invented"},
        {"order_id": None, "type": "invoice", "subject": other, "event": "welcome"},
    ]
    for values in bad:
        with pytest.raises(IntegrityError), pg_engine.begin() as conn:
            conn.execute(insert, {"id": uuid.uuid4(), "key": uuid.uuid4().hex, **values})
    good = {"order_id": None, "type": "user", "subject": other, "event": "welcome", "key": "k"}
    with pg_engine.begin() as conn:
        conn.execute(insert, {"id": uuid.uuid4(), **good})
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:  # dedupe_key is unique
        conn.execute(insert, {"id": uuid.uuid4(), **good})


def test_the_downgrade_refuses_while_newer_messages_exist(pg_engine: Engine):
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO notification_logs (id, subject_type, subject_id, dedupe_key, event, "
                "channel, recipient, status, attempts, next_attempt_at) VALUES (:id, 'user', "
                ":subject, 'user:x:welcome', 'welcome', 'email', 'a@example.rw', 'pending', 0, "
                "now())"
            ),
            {"id": uuid.uuid4(), "subject": uuid.uuid4()},
        )
    with pytest.raises(RuntimeError, match="Downgrade refused"):
        _alembic(pg_engine, "downgrade", BEFORE)
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM notification_logs"))
    _alembic(pg_engine, "downgrade", BEFORE)
    unique = {
        tuple(u["column_names"])
        for u in inspect(pg_engine).get_unique_constraints("notification_logs")
    }
    assert ("order_id", "event", "channel") in unique
    _alembic(pg_engine, "upgrade", "head")
    _alembic(pg_engine, "check")  # the models match the migrated schema
