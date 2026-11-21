"""Module 14 checkout over real HTTP on the least-privilege runtime role, in two API processes.

Proves the grants (orders and order_items INSERT, stock_reservations INSERT, payment_attempts),
that concurrent checkouts of the last unit sell it once (TC-13), and that concurrent retries
with one Idempotency-Key place one order with one set of holds.
"""

import secrets
from typing import cast

import psycopg
import pytest
import redis

from app.core.security import pseudonymize_identifier
from tests.postgres.conftest import HMAC_KEY, Stack
from tests.postgres.test_pg_http import HTTP, one, register
from tests.postgres.test_pg_inventory import seed_sku, together

ADDRESS = {
    "recipient_name": "PG Buyer",
    "phone": "0788765432",
    "district": "Nyarugenge",
    "street_address": "KN 3 Rd",
}


@pytest.fixture
def delivery(stack: Stack, admin: dict) -> None:
    """A Nyarugenge zone with a fee and a threshold (created once; reused if present)."""
    base = stack.servers[0]
    res = HTTP.post(
        f"{base}/staff/delivery/zones",
        json={"code": "nyarugenge-pg", "name": "Nyarugenge", "district": "Nyarugenge", "fee": 1500},
        headers=admin,
    )
    assert res.status_code in (201, 409), res.text
    with stack.owner() as conn:
        conn.execute("UPDATE delivery_zones SET is_active = true WHERE district = 'Nyarugenge'")
        (zone_id,) = one(conn, "SELECT id FROM delivery_zones WHERE district = 'Nyarugenge'")
        (rules,) = one(
            conn,
            "SELECT count(*) FROM delivery_fee_rules WHERE zone_id = %s AND is_active",
            zone_id,
        )
        if rules == 0:
            conn.execute(
                "INSERT INTO delivery_fee_rules (id, zone_id, fee, starts_at) "
                "VALUES (gen_random_uuid(), %s, 1500, now())",
                (zone_id,),
            )
    res = HTTP.patch(
        f"{base}/staff/settings", json={"delivery.free_delivery_threshold": 10**9}, headers=admin
    )
    assert res.status_code == 200, res.text


def checkout(base: str, headers: dict, key: str):
    return HTTP.post(
        f"{base}/checkout",
        json={"address": ADDRESS, "payment_method": "mtn_momo"},
        headers={**headers, "Idempotency-Key": key},
    )


def test_tc13_concurrent_checkouts_sell_the_last_unit_once(stack: Stack, delivery, unique: str):
    variant_id, _, _ = seed_sku(stack, on_hand=1)
    buyers = [register(stack, stack.servers[i % 2], f"last.{unique}.{i}@pg.test") for i in range(6)]
    for buyer in buyers:
        res = HTTP.post(
            f"{stack.servers[0]}/cart/items",
            json={"variant_id": str(variant_id), "quantity": 1},
            headers=buyer["headers"],
        )
        assert res.status_code == 200, res.text
    results = together(
        6, lambda i: checkout(stack.servers[i % 2], buyers[i]["headers"], f"last-{unique}-{i}")
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201] + [409] * 5, [r.text for r in results]
    refused = {r.json()["error"]["code"] for r in results if r.status_code == 409}
    assert refused <= {"insufficient_stock", "cart_needs_attention"}
    with stack.owner() as conn:
        assert one(
            conn,
            "SELECT count(*) FROM stock_reservations WHERE variant_id = %s AND status = 'active'",
            variant_id,
        ) == (1,)
        assert one(
            conn,
            "SELECT count(*) FROM order_items WHERE variant_id = %s",
            variant_id,
        ) == (1,)


def test_concurrent_retries_with_one_key_place_one_order(stack: Stack, delivery, unique: str):
    buyer = register(stack, stack.servers[0], f"retry.{unique}@pg.test")
    variant_id, _, _ = seed_sku(stack, on_hand=5)
    HTTP.post(
        f"{stack.servers[0]}/cart/items",
        json={"variant_id": str(variant_id), "quantity": 2},
        headers=buyer["headers"],
    )
    key = f"retry-{secrets.token_hex(6)}"
    results = together(6, lambda i: checkout(stack.servers[i % 2], buyer["headers"], key))
    assert sorted(r.status_code for r in results) == [200] * 5 + [201], [r.text for r in results]
    assert len({r.json()["order"]["id"] for r in results}) == 1
    assert sum(1 for r in results if r.json()["replayed"]) == 5
    with stack.owner() as conn:
        assert one(conn, "SELECT count(*) FROM orders WHERE user_id = %s", buyer["user"]["id"]) == (
            1,
        )
        assert one(
            conn,
            "SELECT count(*) FROM stock_reservations WHERE variant_id = %s",
            variant_id,
        ) == (1,)
        assert one(
            conn,
            "SELECT count(*) FROM payment_attempts a JOIN orders o ON o.id = a.order_id "
            "WHERE o.user_id = %s",
            buyer["user"]["id"],
        ) == (1,)


def test_runtime_role_cannot_delete_orders_or_payments(stack: Stack):
    with stack.runtime() as conn:
        for table in ("orders", "order_items", "payment_attempts", "stock_reservations"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"DELETE FROM {table} WHERE false")


def test_concurrent_failed_lookups_are_counted_exactly_on_the_shared_store(
    stack: Stack, delivery, unique: str
):
    """ADR-008 S6 on real Redis across two API processes: every failed lookup is one atomic
    increment of the order number's counter, and once 5 failures are counted the number is
    refused (429) even with the right phone."""
    buyer = register(stack, stack.servers[0], f"lookup.{unique}@pg.test")
    variant_id, _, _ = seed_sku(stack, on_hand=2)
    HTTP.post(
        f"{stack.servers[0]}/cart/items",
        json={"variant_id": str(variant_id), "quantity": 1},
        headers=buyer["headers"],
    )
    placed = checkout(stack.servers[0], buyer["headers"], f"lookup-{unique}")
    assert placed.status_code == 201, placed.text
    number = placed.json()["order"]["order_number"]

    def wrong(i: int):
        return HTTP.post(
            f"{stack.servers[i % 2]}/orders/lookup",
            json={"order_number": number, "phone": "0788000999"},
        )

    results = together(10, wrong)
    statuses = [r.status_code for r in results]
    assert set(statuses) <= {404, 429}, [r.text for r in results]
    failures = statuses.count(404)
    assert 5 <= failures <= 10  # concurrent requests may all pass the check before counting
    key = f"rl:order_lookup:id:{pseudonymize_identifier(number, HMAC_KEY)}"
    store = redis.Redis.from_url(stack.redis_url)
    try:
        counted = cast(bytes | None, store.get(key))
        assert int(counted or 0) == failures  # each 404 counted once, none for 429s
        assert 0 < cast(int, store.ttl(key)) <= 900
    finally:
        store.close()
    right = HTTP.post(
        f"{stack.servers[1]}/orders/lookup", json={"order_number": number, "phone": "0788765432"}
    )
    assert right.status_code == 429 and int(right.headers["Retry-After"]) > 0
