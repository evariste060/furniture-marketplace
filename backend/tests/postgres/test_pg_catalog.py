"""Module 5 categories and brands over real HTTP (RE-018; TC-16).

Two API processes run on the least-privilege runtime role, so these tests also prove the
module's grants (INSERT, UPDATE, DELETE on categories and brands) and that the advisory locks
serialise concurrent slug allocation and parent changes across processes.
"""

import secrets

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP, one
from tests.postgres.test_pg_inventory import seed_sku, together


def post(stack: Stack, i: int, admin: dict, path: str, body: dict):
    return HTTP.post(f"{stack.servers[i % 2]}/staff/{path}", json=body, headers=admin)


def test_concurrent_creates_with_one_name_get_distinct_suffixed_slugs(stack: Stack, admin: dict):
    name = f"Race Phones {secrets.token_hex(4)}"
    results = together(8, lambda i: post(stack, i, admin, "categories", {"name": name}))
    assert [r.status_code for r in results] == [201] * 8, [r.text for r in results]
    base = name.lower().replace(" ", "-")
    assert sorted(r.json()["slug"] for r in results) == sorted(
        [base] + [f"{base}-{n}" for n in range(2, 9)]
    )
    home = [results[0].json()["id"]]  # a brand belongs to a main category (ADR-012 decision 9)
    brands = together(
        6, lambda i: post(stack, i, admin, "brands", {"name": name, "category_ids": home})
    )
    assert [r.status_code for r in brands] == [201] * 6, [r.text for r in brands]
    assert len({r.json()["slug"] for r in brands}) == 6


def test_opposite_concurrent_parent_changes_never_create_a_cycle(stack: Stack, admin: dict):
    tag = secrets.token_hex(4)
    for round_number in range(5):
        a = post(stack, 0, admin, "categories", {"name": f"A {tag} {round_number}"}).json()
        b = post(stack, 1, admin, "categories", {"name": f"B {tag} {round_number}"}).json()
        pairs = [(a["id"], b["id"]), (b["id"], a["id"])]

        def move(i: int, pairs=pairs):
            child, parent = pairs[i]
            return HTTP.patch(
                f"{stack.servers[i]}/staff/categories/{child}",
                json={"parent_id": parent},
                headers=admin,
            )

        codes = sorted(r.status_code for r in together(2, move))
        assert codes == [200, 409], codes
        with stack.owner() as conn:
            parents = one(
                conn,
                "SELECT count(*) FROM categories WHERE id = ANY(%s) AND parent_id IS NOT NULL",
                [a["id"], b["id"]],
            )
        assert parents == (1,)


def test_runtime_role_creates_updates_and_deletes_with_audit(stack: Stack, admin: dict):
    tag = secrets.token_hex(4)
    base = stack.servers[1]
    category = HTTP.post(
        f"{base}/staff/categories", json={"name": f"Runtime {tag}"}, headers=admin
    ).json()
    brand = HTTP.post(
        f"{base}/staff/brands",
        json={"name": f"Runtime {tag}", "category_ids": [category["id"]]},
        headers=admin,
    ).json()
    renamed = HTTP.patch(
        f"{base}/staff/categories/{category['id']}", json={"sort_order": 7}, headers=admin
    )
    assert renamed.status_code == 200 and renamed.json()["sort_order"] == 7
    assert category["slug"] in [c["slug"] for c in HTTP.get(f"{base}/catalog/categories").json()]
    listed = {b["slug"]: b["product_count"] for b in HTTP.get(f"{base}/catalog/brands").json()}
    assert listed[brand["slug"]] == 0

    assert (
        HTTP.delete(f"{base}/staff/categories/{category['id']}", headers=admin).status_code == 204
    )
    assert HTTP.delete(f"{base}/staff/brands/{brand['id']}", headers=admin).status_code == 204
    with stack.owner() as conn:
        actions = conn.execute(
            "SELECT action FROM audit_records WHERE entity_id = ANY(%s) ORDER BY created_at",
            ([category["id"], brand["id"]],),
        ).fetchall()
        remaining = one(
            conn,
            "SELECT (SELECT count(*) FROM categories WHERE id=%s)"
            " + (SELECT count(*) FROM brands WHERE id=%s)",
            category["id"],
            brand["id"],
        )
    assert sorted(a for (a,) in actions) == sorted(
        [
            "catalog.category_create",
            "catalog.category_update",
            "catalog.category_delete",
            "catalog.brand_create",
            "catalog.brand_delete",
        ]
    )
    assert remaining == (0,)


def test_category_in_use_cannot_be_deleted_on_the_runtime_role(stack: Stack, admin: dict):
    variant_id, sku, product_slug = seed_sku(stack, on_hand=1)
    with stack.owner() as conn:
        (category_id,) = one(conn, "SELECT category_id FROM products WHERE slug=%s", product_slug)
    res = HTTP.delete(f"{stack.servers[0]}/staff/categories/{category_id}", headers=admin)
    assert res.status_code == 409 and res.json()["error"]["code"] == "category_in_use"
    with stack.owner() as conn:
        assert one(conn, "SELECT count(*) FROM categories WHERE id=%s", category_id) == (1,)
