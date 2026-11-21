"""Staff product list and detail ('catalog:read', approved 2026-10-26): every status, drafts
included, with the has_images filter used to find products without photos."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ProductImage
from tests.support.media import image_row
from tests.support.sellers import post_product

STAFF = "/api/v1/staff"


@pytest.fixture
def category(client: TestClient, admin_auth: dict) -> dict:
    res = client.post(f"{STAFF}/categories", json={"name": "Phones"}, headers=admin_auth["headers"])
    assert res.status_code == 201, res.text
    return res.json()


def product(client, headers, category_id: str, name: str, sku: str | None = None, **extra):
    res = post_product(
        client,
        json={"name": name, "category_id": category_id, **extra},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    if sku is not None:
        variant = client.post(
            f"{STAFF}/products/{body['id']}/variants",
            json={"sku": sku, "name": "Std", "price": 1000},
            headers=headers,
        )
        assert variant.status_code == 201, variant.text
        body["variant_id"] = variant.json()["id"]
    return body


def add_image(db: Session, product_id: str, sort_order: int = 0, variant_id=None) -> ProductImage:
    image = image_row(
        uuid.UUID(product_id),
        sort_order,
        variant_id=uuid.UUID(variant_id) if variant_id else None,
    )
    db.add(image)
    db.commit()
    return image


def names(client, headers, **params) -> list[str]:
    res = client.get(f"{STAFF}/products", params=params, headers=headers)
    assert res.status_code == 200, res.text
    return [item["name"] for item in res.json()["items"]]


@pytest.mark.parametrize(
    ("who", "expected"),
    [
        ("admin_auth", 200),
        ("customer_auth", 403),
        (None, 401),
    ],
)
def test_list_and_detail_need_catalog_read(client, request, admin_auth, category, who, expected):
    made = product(client, admin_auth["headers"], category["id"], "Galaxy A55")
    headers = request.getfixturevalue(who)["headers"] if who else {}
    assert client.get(f"{STAFF}/products", headers=headers).status_code == expected
    assert client.get(f"{STAFF}/products/{made['id']}", headers=headers).status_code == expected


def test_the_list_shows_every_status_with_counts_newest_change_first(
    client, db, admin_auth, category
):
    h = admin_auth["headers"]
    draft = product(client, h, category["id"], "Draft Phone", sku="DP-1")
    hidden = product(client, h, category["id"], "Hidden Phone", status="hidden")
    product(client, h, category["id"], "Archived Phone", status="archived")
    add_image(db, draft["id"], 1)
    add_image(db, draft["id"], 0)
    add_image(db, draft["id"], 2, variant_id=draft["variant_id"])  # variant image: not counted
    client.patch(f"{STAFF}/products/{hidden['id']}", json={"model": "H1"}, headers=h)

    res = client.get(f"{STAFF}/products", headers=h)
    body = res.json()
    assert body["total"] == 3 and body["page"] == 1 and body["size"] == 20
    assert [i["name"] for i in body["items"]] == ["Hidden Phone", "Archived Phone", "Draft Phone"]
    row = body["items"][2]
    assert row["status"] == "draft" and row["category"]["slug"] == "phones"
    assert row["brand"] is None
    assert (row["variant_count"], row["image_count"]) == (1, 2)
    assert row["image"]["position"] == 0 and row["image"]["alt"] == "Draft Phone"
    assert row["image"]["url"].startswith("http") and row["image"]["width"] == 800
    assert body["items"][0]["image"] is None


def test_status_and_has_images_filters_find_products_without_photos(
    client, db, admin_auth, category
):
    h = admin_auth["headers"]
    ready = product(client, h, category["id"], "Ready Draft")
    product(client, h, category["id"], "Bare Draft")
    variant_only = product(client, h, category["id"], "Variant Photo Only", sku="VPO-1")
    add_image(db, ready["id"])
    add_image(db, variant_only["id"], variant_id=variant_only["variant_id"])

    assert names(client, h, status="draft", has_images="true") == ["Ready Draft"]
    assert names(client, h, status="draft", has_images="false") == [
        "Variant Photo Only",
        "Bare Draft",
    ]
    assert names(client, h, status="active") == []
    res = client.get(f"{STAFF}/products", params={"status": "live"}, headers=h)
    assert res.status_code == 422


def test_q_matches_name_slug_model_and_any_variant_sku_case_insensitively(
    client, admin_auth, category
):
    h = admin_auth["headers"]
    product(client, h, category["id"], "Galaxy A55", sku="SAM-A55-128")
    product(client, h, category["id"], "Spark 20", model="KJ5")
    assert names(client, h, q="sam-a55") == ["Galaxy A55"]
    assert names(client, h, q="GALAXY") == ["Galaxy A55"]
    assert names(client, h, q="spark-2") == ["Spark 20"]  # slug
    assert names(client, h, q="kj5") == ["Spark 20"]
    blank = client.get(f"{STAFF}/products", params={"q": "   "}, headers=h)
    assert blank.status_code == 422


def test_the_detail_shows_drafts_variants_and_every_image_in_order(
    client, db, admin_auth, category
):
    h = admin_auth["headers"]
    draft = product(client, h, category["id"], "Draft Phone", sku="DP-2")
    second = add_image(db, draft["id"], 1)
    first = add_image(db, draft["id"], 0)
    variant = add_image(db, draft["id"], 2, variant_id=draft["variant_id"])
    res = client.get(f"{STAFF}/products/{draft['id']}", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "draft" and [v["sku"] for v in body["variants"]] == ["DP-2"]
    assert [i["id"] for i in body["images"]] == [str(first.id), str(second.id), str(variant.id)]
    assert body["images"][2]["variant_id"] == draft["variant_id"]
    missing = client.get(f"{STAFF}/products/{uuid.uuid4()}", headers=h)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "product_not_found"
