"""Customer wishlist (module 21, scope change SC-01 approved by the project owner 2026-10-27)."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import Conflict
from app.models import Category, Product, WishlistItem
from app.models.engagement import WISHLIST_LIMIT
from app.services.wishlist_service import WishlistService
from tests.support.catalog import force_status
from tests.support.sellers import new_store, post_product

STAFF = "/api/v1/staff"
WISH = "/api/v1/customers/me/wishlist"


@pytest.fixture
def category(client: TestClient, admin_auth: dict) -> dict:
    res = client.post(
        f"{STAFF}/categories",
        json={"name": "Phones", "slug": "phones"},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


def product(client: TestClient, admin_auth: dict, category: dict, name: str) -> str:
    h = admin_auth["headers"]
    res = post_product(client, json={"name": name, "category_id": category["id"]}, headers=h)
    assert res.status_code == 201, res.text
    product_id = res.json()["id"]
    variant = client.post(
        f"{STAFF}/products/{product_id}/variants",
        json={"sku": f"SKU-{uuid.uuid4().hex[:8]}", "name": "Std", "price": 1000},
        headers=h,
    )
    assert variant.status_code == 201, variant.text
    force_status(product_id)
    return product_id


def put(client, auth, product_id):
    return client.put(f"{WISH}/{product_id}", headers=auth["headers"])


def ids(client, auth) -> list[str]:
    res = client.get(f"{WISH}/ids", headers=auth["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == len(body["product_ids"]) and body["limit"] == WISHLIST_LIMIT
    return body["product_ids"]


def test_saving_and_removing_are_idempotent_and_listed_newest_first(
    client, admin_auth, category, customer_auth
):
    first = product(client, admin_auth, category, "Galaxy A55")
    second = product(client, admin_auth, category, "Pixel 8")

    for _ in range(2):  # saving twice changes nothing
        res = put(client, customer_auth, first)
        assert res.status_code == 200, res.text
        assert res.json() == {"product_id": first, "in_wishlist": True, "count": 1}
    assert put(client, customer_auth, second).json()["count"] == 2
    assert ids(client, customer_auth) == [second, first]

    page = client.get(WISH, headers=customer_auth["headers"]).json()
    assert (page["total"], page["page"]) == (2, 1)
    newest = page["items"][0]
    assert (newest["product_id"], newest["name"], newest["slug"]) == (second, "Pixel 8", "pixel-8")
    assert newest["available"] is True and newest["image"] is None
    assert newest["product"]["id"] == second and newest["product"]["variants"][0]["price"] == 1000
    assert newest["product"]["rating"] == {"average": None, "count": 0}  # catalogue summary
    paged = client.get(WISH, params={"page": 2, "size": 1}, headers=customer_auth["headers"])
    assert [i["product_id"] for i in paged.json()["items"]] == [first]

    for _ in range(2):  # removing twice changes nothing
        res = client.delete(f"{WISH}/{first}", headers=customer_auth["headers"])
        assert res.status_code == 200
        assert res.json() == {"product_id": first, "in_wishlist": False, "count": 1}
    assert ids(client, customer_auth) == [second]


def test_each_customer_has_their_own_wishlist(
    client, admin_auth, category, customer_auth, second_customer_auth
):
    a = product(client, admin_auth, category, "Galaxy A55")
    put(client, customer_auth, a)
    assert ids(client, second_customer_auth) == []
    assert (
        client.delete(f"{WISH}/{a}", headers=second_customer_auth["headers"]).json()["count"] == 0
    )
    assert ids(client, customer_auth) == [a]


def test_only_products_on_sale_can_be_saved(client, admin_auth, category, customer_auth):
    draft = post_product(
        client,
        json={"name": "Draft phone", "category_id": category["id"]},
        headers=admin_auth["headers"],
    ).json()["id"]
    for unknown in (draft, str(uuid.uuid4())):
        res = put(client, customer_auth, unknown)
        assert res.status_code == 404 and res.json()["error"]["code"] == "product_not_found"
    assert client.put(f"{WISH}/not-a-uuid", headers=customer_auth["headers"]).status_code == 422
    assert ids(client, customer_auth) == []


def test_products_no_longer_sold_stay_listed_until_removed(
    client, db: Session, admin_auth, category, customer_auth
):
    archived = product(client, admin_auth, category, "Old phone")
    hidden = product(client, admin_auth, category, "Phone in a hidden category")
    put(client, customer_auth, archived)
    put(client, customer_auth, hidden)
    force_status(archived, "archived")
    other = Category(name="Hidden", slug="hidden", is_active=False)
    db.add(other)
    db.flush()
    db.execute(update(Product).where(Product.id == uuid.UUID(hidden)).values(category_id=other.id))
    db.commit()

    items = client.get(WISH, headers=customer_auth["headers"]).json()["items"]
    assert [(i["name"], i["available"], i["product"]) for i in items] == [
        ("Phone in a hidden category", False, None),
        ("Old phone", False, None),
    ]
    assert items[1]["slug"] == "old-phone"
    # Still saved, saving again changes nothing, and it can be removed.
    assert put(client, customer_auth, archived).json() == {
        "product_id": archived,
        "in_wishlist": True,
        "count": 2,
    }
    assert (
        client.delete(f"{WISH}/{archived}", headers=customer_auth["headers"]).json()["count"] == 1
    )
    # Once removed, it cannot be saved again while it is not sold.
    assert put(client, customer_auth, archived).status_code == 404


def _fill(db: Session, user_id: uuid.UUID, category_id: uuid.UUID, n: int) -> list[uuid.UUID]:
    """n active products saved by the customer, inserted directly (fast)."""
    product_ids = [uuid.uuid4() for _ in range(n)]
    store = new_store()  # every product belongs to an approved store (ADR-014 phase 2)
    db.add(store)
    db.flush()
    db.execute(
        insert(Product),
        [
            {
                "id": pid,
                "name": f"Bulk {i}",
                "slug": f"bulk-{i}",
                "category_id": category_id,
                "status": "active",
                "specifications": {},
                "store_id": store.id,
            }
            for i, pid in enumerate(product_ids)
        ],
    )
    db.execute(
        insert(WishlistItem),
        [{"id": uuid.uuid4(), "user_id": user_id, "product_id": pid} for pid in product_ids],
    )
    db.commit()
    return product_ids


def test_the_wishlist_holds_at_most_200_products(
    client, db: Session, admin_auth, category, customer_auth
):
    user_id = uuid.UUID(customer_auth["user"]["id"])
    saved = _fill(db, user_id, uuid.UUID(category["id"]), WISHLIST_LIMIT - 1)
    last = product(client, admin_auth, category, "Number 200")
    extra = product(client, admin_auth, category, "Number 201")
    assert put(client, customer_auth, last).json()["count"] == WISHLIST_LIMIT
    res = put(client, customer_auth, extra)
    assert res.status_code == 409 and res.json()["error"]["code"] == "wishlist_full"
    assert put(client, customer_auth, saved[0]).status_code == 200  # already saved: fine
    client.delete(f"{WISH}/{saved[0]}", headers=customer_auth["headers"])
    assert put(client, customer_auth, extra).json()["count"] == WISHLIST_LIMIT


def test_parallel_saves_cannot_pass_the_limit(
    client, db: Session, pg_engine, admin_auth, category, customer_auth
):
    """Ten customers' worth of races on one customer: the users row lock serialises the count
    check, so with one place left exactly one of ten different products is saved."""
    user_id = uuid.UUID(customer_auth["user"]["id"])
    _fill(db, user_id, uuid.UUID(category["id"]), WISHLIST_LIMIT - 1)
    candidates = [uuid.UUID(product(client, admin_auth, category, f"Race {i}")) for i in range(10)]
    sf = sessionmaker(bind=pg_engine, expire_on_commit=False)
    barrier = Barrier(len(candidates))
    customer = SimpleNamespace(id=user_id)

    def save(product_id: uuid.UUID) -> str:
        with sf() as s:
            barrier.wait()
            try:
                WishlistService.add(s, customer, product_id)  # type: ignore[arg-type]
                return "saved"
            except Conflict:
                return "full"

    with ThreadPoolExecutor(len(candidates)) as pool:
        results = list(pool.map(save, candidates))
    assert sorted(results) == ["full"] * 9 + ["saved"]
    db.expire_all()
    count = db.scalar(select(func.count()).where(WishlistItem.user_id == user_id))
    assert count == WISHLIST_LIMIT


def test_only_signed_in_customers_have_a_wishlist(client, admin_auth, category):
    some = product(client, admin_auth, category, "Galaxy A55")
    for method, path in (
        ("get", WISH),
        ("get", f"{WISH}/ids"),
        ("put", f"{WISH}/{some}"),
        ("delete", f"{WISH}/{some}"),
    ):
        assert client.request(method, path).status_code == 401
        bad = client.request(method, path, headers={"Authorization": "Bearer nope"})
        assert bad.status_code == 401
        for staff in (admin_auth,):  # the only staff role since SC-05
            res = client.request(method, path, headers=staff["headers"])
            assert res.status_code == 403 and res.json()["error"]["code"] == "customer_only"


def test_a_customer_who_signs_in_can_save_the_product_they_picked_as_a_guest(
    client, admin_auth, category, customer_auth
):
    """The storefront keeps the product a guest tapped and saves it once they sign in."""
    picked = product(client, admin_auth, category, "Galaxy A55")
    assert client.put(f"{WISH}/{picked}").status_code == 401  # as a guest
    login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "customer.a@example.com", "password": "SecurePassword123!"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['session_token']}"}
    assert client.put(f"{WISH}/{picked}", headers=headers).json()["in_wishlist"] is True
    assert ids(client, customer_auth) == [picked]
