"""Module 11 cart over real HTTP on the least-privilege runtime role, in two API processes.

Proves the module's grants (carts: SELECT, INSERT, UPDATE; cart_items: also DELETE), that
concurrent first adds by one customer create a single cart, and that concurrent merges of one
guest cart add its units exactly once.
"""

import psycopg
import pytest

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP, one, register
from tests.postgres.test_pg_inventory import seed_sku, together


def add(base: str, headers: dict, variant_id, quantity: int = 1):
    return HTTP.post(
        f"{base}/cart/items",
        json={"variant_id": str(variant_id), "quantity": quantity},
        headers=headers,
    )


def test_concurrent_first_adds_by_one_customer_share_one_cart(stack: Stack, unique: str):
    customer = register(stack, stack.servers[0], f"cart.{unique}@pg.test")
    variant_id, _, _ = seed_sku(stack, on_hand=50)
    results = together(6, lambda i: add(stack.servers[i % 2], customer["headers"], variant_id))
    assert [r.status_code for r in results] == [200] * 6, [r.text for r in results]
    with stack.owner() as conn:
        assert one(
            conn, "SELECT count(*) FROM carts WHERE user_id = %s", customer["user"]["id"]
        ) == (1,)
        assert one(
            conn,
            "SELECT i.quantity FROM cart_items i JOIN carts c ON c.id = i.cart_id "
            "WHERE c.user_id = %s",
            customer["user"]["id"],
        ) == (6,)


def test_concurrent_merges_of_one_guest_cart_add_its_units_once(stack: Stack, unique: str):
    customer = register(stack, stack.servers[0], f"merge.{unique}@pg.test")
    variant_id, _, _ = seed_sku(stack, on_hand=50)
    created = add(stack.servers[1], {}, variant_id, 5)
    assert created.status_code == 200, created.text
    token = created.json()["cart_token"]
    headers = {**customer["headers"], "X-Cart-Token": token}
    results = together(
        4, lambda i: HTTP.post(f"{stack.servers[i % 2]}/cart/merge", headers=headers)
    )
    assert sorted(r.status_code for r in results) == [200, 404, 404, 404], [r.text for r in results]
    cart = HTTP.get(f"{stack.servers[0]}/cart", headers=customer["headers"]).json()
    assert [line["quantity"] for line in cart["lines"]] == [5]
    assert HTTP.get(f"{stack.servers[0]}/cart", headers={"X-Cart-Token": token}).status_code == 404
    with stack.owner() as conn:  # S4: one audit record, written with the one successful merge
        assert one(
            conn,
            "SELECT count(*) FROM audit_records WHERE action = 'cart.merge' AND actor_user_id = %s",
            customer["user"]["id"],
        ) == (1,)


def test_guest_lines_are_removed_with_the_runtime_role(stack: Stack):
    variant_id, _, _ = seed_sku(stack, on_hand=5)
    created = add(stack.servers[0], {}, variant_id, 2).json()
    token, line = created["cart_token"], created["lines"][0]["id"]
    res = HTTP.delete(f"{stack.servers[1]}/cart/items/{line}", headers={"X-Cart-Token": token})
    assert res.status_code == 204


def test_runtime_role_cannot_delete_carts(stack: Stack):
    with stack.runtime() as conn:
        conn.execute("DELETE FROM cart_items WHERE false")  # granted (module 11)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM carts WHERE false")


def test_concurrent_adds_on_one_guest_cart_lose_no_update(stack: Stack):
    variant_id, _, _ = seed_sku(stack, on_hand=50)
    created = add(stack.servers[0], {}, variant_id, 1).json()
    token = created["cart_token"]
    guest_headers = {"X-Cart-Token": token}
    results = together(6, lambda i: add(stack.servers[i % 2], guest_headers, variant_id, 2))
    assert [r.status_code for r in results] == [200] * 6, [r.text for r in results]
    cart = HTTP.get(f"{stack.servers[1]}/cart", headers=guest_headers).json()
    assert [line["quantity"] for line in cart["lines"]] == [13]  # 1 + 6 x 2, serialised


def test_a_merge_racing_guest_adds_never_loses_or_doubles_units(stack: Stack, unique: str):
    customer = register(stack, stack.servers[0], f"race.{unique}@pg.test")
    variant_id, _, _ = seed_sku(stack, on_hand=90)
    token = add(stack.servers[0], {}, variant_id, 1).json()["cart_token"]
    guest_headers = {"X-Cart-Token": token}
    merge_headers = {**customer["headers"], "X-Cart-Token": token}

    def act(i: int):
        base = stack.servers[i % 2]
        if i == 0:
            return HTTP.post(f"{base}/cart/merge", headers=merge_headers)
        return add(base, guest_headers, variant_id, 1)

    results = together(6, act)
    merge, adds = results[0], results[1:]
    assert merge.status_code == 200, merge.text
    # Each add landed on the guest cart before the merge (200, then merged) or found it
    # converted after (404); none is lost or counted twice.
    assert {r.status_code for r in adds} <= {200, 404}
    added_before = sum(1 for r in adds if r.status_code == 200)
    merged = merge.json()["merged_lines"][0]["added_quantity"]
    assert merged == 1 + added_before
    cart = HTTP.get(f"{stack.servers[0]}/cart", headers=customer["headers"]).json()
    assert [line["quantity"] for line in cart["lines"]] == [merged]
