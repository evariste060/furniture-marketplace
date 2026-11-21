"""Module 9 full-text search over real HTTP on the least-privilege runtime role.

Proves that the search triggers run with the runtime role's existing grants: creating a product
and renaming its brand through the staff API keep the public search current.
"""

import secrets

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP
from tests.postgres.test_pg_images import add_photo
from tests.postgres.test_pg_sellers import approved_seller_headers


def test_search_follows_product_creation_and_brand_rename_on_the_runtime_role(
    stack: Stack, admin: dict, unique: str, phone_factory
):
    seller = approved_seller_headers(stack, admin, unique, phone_factory())
    base, tag = stack.servers[0], secrets.token_hex(4)
    category = HTTP.post(
        f"{base}/staff/categories", json={"name": f"PG search {tag}"}, headers=admin
    ).json()
    brand = HTTP.post(
        f"{base}/staff/brands",
        json={"name": f"Brand{tag}", "category_ids": [category["id"]]},
        headers=admin,
    ).json()
    product = HTTP.post(  # sellers create products; staff moderate them (SC-05)
        f"{base}/seller/products",
        json={
            "name": f"Searchphone {tag}",
            "model": f"QX-{tag}",
            "category_id": category["id"],
            "brand_id": brand["id"],
        },
        headers=seller,
    )
    assert product.status_code == 201, product.text
    slug = product.json()["slug"]
    add_photo(base, admin, product.json()["id"])  # activation needs an image (2026-10-26)
    activated = HTTP.patch(
        f"{base}/staff/products/{product.json()['id']}", json={"status": "active"}, headers=admin
    )
    assert activated.status_code == 200, activated.text

    def found(q: str) -> list[str]:
        res = HTTP.get(f"{stack.servers[1]}/catalog/products", params={"q": q})
        assert res.status_code == 200, res.text
        return [item["slug"] for item in res.json()["items"]]

    assert found(f"qx{tag}") == [slug]
    assert found(f"brand{tag}") == [slug]
    renamed = HTTP.patch(
        f"{base}/staff/brands/{brand['id']}", json={"name": f"Renamed{tag}"}, headers=admin
    )
    assert renamed.status_code == 200, renamed.text
    assert found(f"renamed{tag}") == [slug]
    assert found(f"brand{tag}") == []
