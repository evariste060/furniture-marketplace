"""Module 6 products and variants over real HTTP on the least-privilege runtime role.

Proves the module's grants (INSERT and UPDATE on products and product_variants, no DELETE) and
that the product advisory lock serialises slug and SKU allocation across API processes.
"""

import secrets

import psycopg
import pytest

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP, one
from tests.postgres.test_pg_images import add_photo
from tests.postgres.test_pg_inventory import together


def staff(stack: Stack, i: int, admin: dict, method: str, path: str, body: dict | None = None):
    return HTTP.request(method, f"{stack.servers[i % 2]}/staff/{path}", json=body, headers=admin)


@pytest.fixture
def category_id(stack: Stack, admin: dict) -> str:
    res = staff(stack, 0, admin, "POST", "categories", {"name": f"PG Cat {secrets.token_hex(4)}"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_concurrent_product_creates_get_distinct_slugs(stack: Stack, admin: dict, category_id):
    name = f"Race Phone {secrets.token_hex(4)}"
    body = {"name": name, "category_id": category_id}
    results = together(6, lambda i: staff(stack, i, admin, "POST", "products", body))
    assert [r.status_code for r in results] == [201] * 6, [r.text for r in results]
    base = name.lower().replace(" ", "-")
    assert sorted(r.json()["slug"] for r in results) == sorted(
        [base] + [f"{base}-{n}" for n in range(2, 7)]
    )


def test_concurrent_variants_with_one_sku_create_exactly_one(
    stack: Stack, admin: dict, category_id
):
    product = staff(
        stack,
        0,
        admin,
        "POST",
        "products",
        {"name": f"SKU {secrets.token_hex(4)}", "category_id": category_id},
    ).json()
    sku = f"RACE-{secrets.token_hex(4)}"
    body = {"sku": sku, "name": "Std", "price": 100}
    results = together(
        6, lambda i: staff(stack, i, admin, "POST", f"products/{product['id']}/variants", body)
    )
    assert sorted(r.status_code for r in results) == [201] + [409] * 5
    assert {r.json()["error"]["code"] for r in results if r.status_code == 409} == {"sku_taken"}
    with stack.owner() as conn:
        assert one(conn, "SELECT count(*) FROM product_variants WHERE sku=%s", sku) == (1,)


def test_runtime_role_manages_products_and_public_shows_only_a_stock_band(
    stack: Stack, admin: dict, category_id
):
    tag = secrets.token_hex(4)
    product = staff(
        stack, 1, admin, "POST", "products", {"name": f"Runtime {tag}", "category_id": category_id}
    ).json()
    variant = staff(
        stack,
        1,
        admin,
        "POST",
        f"products/{product['id']}/variants",
        {"sku": f"RT-{tag}", "name": "Std", "price": 500, "low_stock_threshold": 2},
    ).json()
    with stack.owner() as conn:
        conn.execute(
            "INSERT INTO inventory_balances (id, variant_id, on_hand) "
            "VALUES (gen_random_uuid(), %s, 2)",
            (variant["id"],),
        )
    path = f"products/{product['id']}"
    refused = staff(stack, 0, admin, "PATCH", path, {"status": "active"})  # no image yet
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "product_has_no_images"
    add_photo(stack.servers[1], admin, product["id"])
    assert staff(stack, 0, admin, "PATCH", path, {"status": "active"}).status_code == 200
    priced = staff(
        stack,
        0,
        admin,
        "PATCH",
        f"products/{product['id']}/variants/{variant['id']}",
        {"price": 450},
    )
    assert priced.status_code == 200 and priced.json()["price"] == 450

    detail = HTTP.get(f"{stack.servers[1]}/catalog/products/{product['slug']}").json()
    (shown,) = detail["variants"]
    assert shown["stock_status"] == "low_stock" and "available_quantity" not in shown

    gone = staff(stack, 1, admin, "DELETE", f"products/{product['id']}/variants/{variant['id']}")
    assert gone.status_code == 204
    with stack.owner() as conn:
        assert one(conn, "SELECT is_active FROM product_variants WHERE id=%s", variant["id"]) == (
            False,
        )
        actions = conn.execute(
            "SELECT action FROM audit_records WHERE entity_id = ANY(%s)",
            ([product["id"], variant["id"]],),
        ).fetchall()
    assert sorted(a for (a,) in actions) == sorted(
        [
            "catalog.product_create",
            "catalog.product_update",
            "catalog.variant_create",
            "catalog.variant_update",
            "catalog.variant_deactivate",
        ]
    )


def test_runtime_role_cannot_delete_products_or_variants(stack: Stack):
    with stack.runtime() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM product_variants WHERE false")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM products WHERE false")
