"""Module 20 reviews part 2 over real HTTP on the least-privilege runtime role, in two API
processes.

Proves the grants (review_tokens and product_reviews: SELECT, INSERT, UPDATE; the totals update
products), that a link spent concurrently on both processes yields exactly one review, and that
approving recalculates the product's rating.
"""

import secrets
import uuid

import psycopg
import pytest

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP, one
from tests.postgres.test_pg_inventory import seed_sku, together

PHONE = "+250788123456"


def delivered_order(stack: Stack, variant_id: uuid.UUID) -> tuple[str, uuid.UUID]:
    """A delivered guest order of one item; returns (order number, order item id)."""
    order_id, item_id = uuid.uuid4(), uuid.uuid4()
    number = f"ORD-PG-{secrets.token_hex(4).upper()}"
    with stack.owner() as conn:
        (product_id, name) = one(
            conn,
            "SELECT p.id, p.name FROM product_variants v JOIN products p ON p.id = v.product_id "
            "WHERE v.id = %s",
            variant_id,
        )
        conn.execute(
            "INSERT INTO orders (id, order_number, checkout_idempotency_key, status, subtotal, "
            "total, recipient_name, recipient_phone, delivery_address_snapshot) "
            "VALUES (%s, %s, %s, 'delivered', 1000, 1000, 'Aline Uwase', %s, '{}')",
            (order_id, number, f"pg-{order_id}", PHONE),
        )
        conn.execute(
            "INSERT INTO order_items (id, order_id, product_id, variant_id, sku_snapshot, "
            "product_name_snapshot, quantity, unit_price, line_subtotal, line_total) "
            "VALUES (%s, %s, %s, %s, 'PG', %s, 1, 1000, 1000, 1000)",
            (item_id, order_id, product_id, variant_id, name),
        )
        conn.execute(
            "INSERT INTO order_status_history (id, order_id, status) VALUES (%s, %s, 'delivered')",
            (uuid.uuid4(), order_id),
        )
    return number, item_id


def test_link_submit_and_approve_on_the_runtime_role(stack: Stack, admin: dict):
    variant_id, _, slug = seed_sku(stack, on_hand=5)
    number, item_id = delivered_order(stack, variant_id)
    link = HTTP.post(
        f"{stack.servers[0]}/orders/review-link",
        json={"order_number": number, "phone": PHONE, "order_item_id": str(item_id)},
    )
    assert link.status_code == 201, link.text
    token = link.json()["token"]

    # Five at once: the most a link allows an hour, so none is refused with 429 whatever order
    # the attempts are counted in.
    results = together(
        5,
        lambda i: HTTP.post(f"{stack.servers[i % 2]}/reviews/{token}", json={"rating": 4}),
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201] + [409] * 4, [r.text for r in results]
    with stack.owner() as conn:
        assert one(
            conn, "SELECT count(*) FROM product_reviews WHERE order_item_id = %s", item_id
        ) == (1,)
        (review_id,) = one(conn, "SELECT id FROM product_reviews WHERE order_item_id = %s", item_id)

    approved = HTTP.post(f"{stack.servers[1]}/staff/reviews/{review_id}/approve", headers=admin)
    assert approved.status_code == 200, approved.text
    detail = HTTP.get(f"{stack.servers[0]}/catalog/products/{slug}").json()
    assert detail["rating"]["average"] == 4.0 and detail["rating"]["count"] == 1
    listed = HTTP.get(f"{stack.servers[0]}/catalog/products/{slug}/reviews").json()
    assert [r["author_name"] for r in listed["items"]] == ["Aline U."]


def test_the_runtime_role_cannot_delete_reviews_or_links(stack: Stack):
    for table in ("product_reviews", "review_tokens"):
        with stack.runtime() as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names
