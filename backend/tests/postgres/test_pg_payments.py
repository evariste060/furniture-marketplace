"""Module 15 payments over real HTTP on the least-privilege runtime role, in two API processes.

Proves the grants (payment_events INSERT/UPDATE, payment_attempts), and that concurrent copies
of one verified success event are applied once: one event row, one stock commit, one audit, and
every copy answered 200.
"""

import json
import time
import uuid

import psycopg
import pytest

from app.integrations.payments.mock import sign
from tests.postgres.conftest import MOCK_PAYMENT_SECRET, Stack
from tests.postgres.test_pg_checkout import checkout, delivery  # noqa: F401
from tests.postgres.test_pg_http import HTTP, one, register
from tests.postgres.test_pg_inventory import seed_sku, together


def send(base: str, payload: bytes):
    stamp = int(time.time())
    return HTTP.post(
        f"{base}/webhooks/mock",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Mock-Timestamp": str(stamp),
            "X-Mock-Signature": sign(payload, stamp, MOCK_PAYMENT_SECRET),
        },
    )


def paid_order(stack: Stack, unique: str, tag: str) -> tuple[dict, dict, dict]:
    buyer = register(stack, stack.servers[0], f"pay.{tag}.{unique}@pg.test")
    variant_id, _, _ = seed_sku(stack, on_hand=3)
    HTTP.post(
        f"{stack.servers[0]}/cart/items",
        json={"variant_id": str(variant_id), "quantity": 1},
        headers=buyer["headers"],
    )
    order = checkout(stack.servers[0], buyer["headers"], f"pay-{tag}-{unique}").json()["order"]
    started = HTTP.post(
        f"{stack.servers[1]}/payments/{order['order_number']}/initiate", headers=buyer["headers"]
    )
    assert started.status_code == 200, started.text
    return buyer, order, started.json()


def test_concurrent_duplicate_webhooks_apply_once(stack: Stack, delivery, unique: str):  # noqa: F811
    _, order, started = paid_order(stack, unique, "dup")
    payload = json.dumps(
        {
            "event_id": f"evt-{uuid.uuid4().hex}",
            "reference": started["reference"],
            "status": "succeeded",
            "amount": order["total"],
            "currency": "RWF",
        }
    ).encode()
    results = together(8, lambda i: send(stack.servers[i % 2], payload))
    assert [r.status_code for r in results] == [200] * 8, [r.text for r in results]
    outcomes = sorted(r.json()["status"] for r in results)
    assert outcomes == ["duplicate"] * 7 + ["processed"]
    with stack.owner() as conn:
        assert one(
            conn,
            "SELECT count(*) FROM payment_events e JOIN payment_attempts a ON a.id = e.attempt_id "
            "WHERE a.order_id = %s",
            order["id"],
        ) == (1,)
        assert one(
            conn,
            "SELECT count(*) FROM stock_reservations WHERE order_id = %s AND status = 'committed'",
            order["id"],
        ) == (1,)
        assert one(
            conn,
            "SELECT count(*) FROM audit_records WHERE action = 'inventory.reservation_commit' "
            "AND entity_id = %s",
            order["id"],
        ) == (1,)
        assert one(
            conn, "SELECT status FROM payment_attempts WHERE order_id = %s", order["id"]
        ) == ("succeeded",)


def test_racing_success_and_failure_events_never_regress(stack: Stack, delivery, unique: str):  # noqa: F811
    _, order, started = paid_order(stack, unique, "race")

    def body(status: str) -> bytes:
        return json.dumps(
            {
                "event_id": f"evt-{uuid.uuid4().hex}",
                "reference": started["reference"],
                "status": status,
                "amount": order["total"],
                "currency": "RWF",
            }
        ).encode()

    payloads = [body("succeeded")] + [body("failed") for _ in range(3)]
    results = together(4, lambda i: send(stack.servers[i % 2], payloads[i]))
    assert [r.status_code for r in results] == [200] * 4
    with stack.owner() as conn:
        (status,) = one(
            conn, "SELECT status FROM payment_attempts WHERE order_id = %s", order["id"]
        )
    # Whatever the arrival order, it ends succeeded: failures after the success are ignored
    # (never a regression), and a success after a failure still commits while the hold lasts.
    assert status == "succeeded"


def test_runtime_role_cannot_delete_payment_events(stack: Stack):
    with stack.runtime() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM payment_events WHERE false")
