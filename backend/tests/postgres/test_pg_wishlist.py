"""Module 21 wishlist over real HTTP on the least-privilege runtime role, in two API processes.

Proves the grants (wishlist_items: SELECT, INSERT, DELETE; the limit check locks users) and that
concurrent saves of one product by one customer leave a single row.
"""

import psycopg
import pytest

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP, one, register
from tests.postgres.test_pg_inventory import seed_sku, together


def test_save_list_and_remove_on_the_runtime_role(stack: Stack, unique: str):
    customer = register(stack, stack.servers[0], f"wish.{unique}@pg.test")
    _, _, slug = seed_sku(stack, on_hand=5)
    with stack.owner() as conn:
        (product_id,) = one(conn, "SELECT id FROM products WHERE slug = %s", slug)
    path = f"/customers/me/wishlist/{product_id}"

    results = together(
        6, lambda i: HTTP.put(f"{stack.servers[i % 2]}{path}", headers=customer["headers"])
    )
    assert [r.status_code for r in results] == [200] * 6, [r.text for r in results]
    assert {r.json()["count"] for r in results} == {1}
    listed = HTTP.get(f"{stack.servers[1]}/customers/me/wishlist", headers=customer["headers"])
    assert listed.status_code == 200 and listed.json()["items"][0]["slug"] == slug
    with stack.owner() as conn:
        assert one(
            conn, "SELECT count(*) FROM wishlist_items WHERE user_id = %s", customer["user"]["id"]
        ) == (1,)

    removed = HTTP.delete(f"{stack.servers[0]}{path}", headers=customer["headers"])
    assert removed.status_code == 200 and removed.json()["count"] == 0


def test_the_runtime_role_cannot_rewrite_wishlist_rows(stack: Stack):
    with stack.runtime() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE wishlist_items SET product_id = product_id")
