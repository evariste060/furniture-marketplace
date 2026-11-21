"""Module 17 notifications over real HTTP on the least-privilege runtime role, in two API
processes (NOTIFICATION_PROVIDER=console, development only).

Proves the grants (notification_logs SELECT, INSERT, UPDATE; no DELETE): an order cancelled
through one process is notified after the response, the other process lists and refuses to
retry it, and concurrent copies of scripts/retry_notifications.py on the runtime role send each
due notification exactly once.
"""

import os
import subprocess
import sys
import time
import uuid

import psycopg
import pytest

from tests.postgres.conftest import BACKEND, HMAC_KEY, REPO, Stack
from tests.postgres.test_pg_checkout import checkout, delivery  # noqa: F401
from tests.postgres.test_pg_http import HTTP, one, register
from tests.postgres.test_pg_inventory import seed_sku

PHONE = "+250788765432"  # tests.postgres.test_pg_checkout.ADDRESS, canonical


def placed_order(stack: Stack, unique: str, tag: str) -> dict:
    buyer = register(stack, stack.servers[0], f"notify.{tag}.{unique}@pg.test")
    variant_id, _, _ = seed_sku(stack, on_hand=2)
    added = HTTP.post(
        f"{stack.servers[0]}/cart/items",
        json={"variant_id": str(variant_id), "quantity": 1},
        headers=buyer["headers"],
    )
    assert added.status_code == 200, added.text
    res = checkout(stack.servers[0], buyer["headers"], f"notify-{tag}-{unique}")
    assert res.status_code == 201, res.text
    return res.json()["order"]


def wait_for_status(stack: Stack, order_id: str, event: str, expected: str) -> tuple:
    deadline = time.monotonic() + 15
    while True:
        with stack.owner() as conn:
            row = one(
                conn,
                "SELECT status, attempts, provider_message_id, sent_at FROM notification_logs "
                "WHERE order_id = %s AND event = %s",
                order_id,
                event,
            )
        if (row and row[0] == expected) or time.monotonic() > deadline:
            return row
        time.sleep(0.2)


def test_a_cancellation_is_notified_listed_and_not_resent_on_the_runtime_role(
    stack: Stack,
    delivery,  # noqa: F811
    admin: dict,
    unique: str,
):
    order = placed_order(stack, unique, "cancel")
    res = HTTP.patch(
        f"{stack.servers[0]}/staff/orders/{order['id']}/status",
        json={"status": "cancelled"},
        headers=admin,
    )
    assert res.status_code == 200, res.text
    status, attempts, message_id, sent_at = wait_for_status(stack, order["id"], "cancelled", "sent")
    assert (status, attempts) == ("sent", 1)
    assert message_id.startswith("console-") and sent_at is not None
    listing = HTTP.get(
        f"{stack.servers[1]}/staff/notifications", params={"order_id": order["id"]}, headers=admin
    )
    assert listing.status_code == 200, listing.text
    # checkout also recorded the order-received message; this test is about the cancellation
    [item] = [i for i in listing.json()["items"] if i["event"] == "cancelled"]
    assert (item["event"], item["channel"], item["status"]) == ("cancelled", "sms", "sent")
    assert item["recipient"] == "+250******432" and PHONE not in listing.text
    retry = HTTP.post(f"{stack.servers[1]}/staff/notifications/{item['id']}/retry", headers=admin)
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "notification_already_sent"


def test_concurrent_retry_jobs_send_each_due_notification_once(
    stack: Stack,
    delivery,  # noqa: F811
    unique: str,
):
    orders = [placed_order(stack, unique, f"job{i}") for i in range(2)]
    ids = []
    with stack.owner() as conn:
        for order in orders:
            for event in ("confirmed", "dispatched", "delivered"):
                ids.append(uuid.uuid4())
                conn.execute(
                    "INSERT INTO notification_logs (id, order_id, subject_type, subject_id, "
                    "dedupe_key, event, channel, recipient, status, attempts, next_attempt_at) "
                    "VALUES (%s, %s, 'order', %s, %s, %s, 'sms', %s, 'pending', 0, "
                    "now() - interval '1 second')",
                    (
                        ids[-1],
                        order["id"],
                        order["id"],
                        f"order:{order['id']}:{event}:sms",
                        event,
                        PHONE,
                    ),
                )
    env = {
        **os.environ,
        "DATABASE_URL": stack.runtime_url,  # the job runs on the least-privilege role
        "MIGRATION_DATABASE_URL": "",
        "AUDIT_HMAC_KEY": HMAC_KEY,
        "REDIS_URL": stack.redis_url,
        "APP_ENV": "development",
        "NOTIFICATION_PROVIDER": "console",
    }
    cmd = [sys.executable, str(REPO / "scripts" / "retry_notifications.py"), "--batch-size", "2"]
    procs = [
        subprocess.Popen(cmd, cwd=BACKEND, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(3)
    ]
    outputs = [p.communicate(timeout=120) for p in procs]
    assert all(p.returncode == 0 for p in procs), [err.decode() for _, err in outputs]
    printed = b"".join(err for _, err in outputs).decode()
    for order in orders:  # the console provider printed each message exactly once
        for verb in ("is confirmed", "is on its way", "has been delivered"):
            assert printed.count(f"Your order {order['order_number']} {verb}") == 1
    summaries = b"".join(out for out, _ in outputs).decode()
    assert PHONE not in summaries  # the job's own output carries counts only
    with stack.owner() as conn:
        assert one(
            conn,
            "SELECT count(*) FROM notification_logs WHERE id = ANY(%s) "
            "AND status = 'sent' AND attempts = 1 AND claimed_until IS NULL",
            ids,
        ) == (6,)


def test_runtime_role_cannot_delete_notification_logs(stack: Stack):
    with stack.runtime() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM notification_logs WHERE false")
