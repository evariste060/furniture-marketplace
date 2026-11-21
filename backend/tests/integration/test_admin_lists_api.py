"""Frontend phase 6 backend (owner decision 2026-10-28): the staff order list's customer, search
and payment-method filter, the staff category and brand lists, the staff product list's price
and stock, and the order assignee list. Disposable per-test PostgreSQL schema."""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.models import Brand, Category, InventoryBalance, Product, ProductVariant
from tests.integration.test_checkout_api import (  # noqa: F401 (delivery is a fixture)
    INLINE,
    checkout,
    delivery,
    guest_cart,
)

ORDERS = "/api/v1/staff/orders"
STAFF = "/api/v1/staff"


def place(client, db, phone: str, name: str, method: str = "cash_on_delivery") -> dict:
    body = {"address": {**INLINE, "phone": phone, "recipient_name": name}, "payment_method": method}
    res = checkout(client, guest_cart(client, db), body)
    assert res.status_code == 201, res.text
    return res.json()["order"]


# ---- orders ------------------------------------------------------------------------------------
@pytest.mark.usefixtures("delivery")
def test_order_rows_name_the_customer_and_search_by_phone_or_number(client, db, admin_auth):
    h = admin_auth["headers"]
    first = place(client, db, "0788 111 222", "Aline Uwase")
    second = place(client, db, "0722333444", "Eric Ndayisaba", method="mtn_momo")

    rows = client.get(ORDERS, headers=h).json()["items"]
    assert {(r["customer_name"], r["customer_phone"]) for r in rows} == {
        ("Aline Uwase", "+250788111222"),
        ("Eric Ndayisaba", "+250722333444"),
    }

    def numbers(**params) -> list[str]:
        res = client.get(ORDERS, params=params, headers=h)
        assert res.status_code == 200, res.text
        return [r["order_number"] for r in res.json()["items"]]

    assert numbers(q="+250 788 111 222") == [first["order_number"]]
    assert numbers(q="0722333444") == [second["order_number"]]
    assert numbers(q=second["order_number"][-6:].lower()) == [second["order_number"]]
    assert numbers(q="no-such%order") == []
    assert numbers(payment_method="mtn_momo") == [second["order_number"]]
    assert numbers(payment_method="cash_on_delivery") == [first["order_number"]]


@pytest.mark.usefixtures("delivery")
def test_assignees_list_active_staff_for_fulfilment_roles_only(
    client, db, admin_auth, operations_auth, sales_auth
):
    res = client.get(f"{ORDERS}/assignees", headers=operations_auth["headers"])
    assert res.status_code == 200, res.text
    roles = {item["role"] for item in res.json()["items"]}
    assert {"administrator", "operations", "sales"} <= roles
    assert client.get(f"{ORDERS}/assignees", headers=sales_auth["headers"]).status_code == 403

    order = place(client, db, "0788111222", "Aline Uwase")
    target = str(operations_auth["user"].id)
    assigned = client.patch(
        f"{ORDERS}/{order['id']}/assignment",
        json={"staff_user_id": target},
        headers=admin_auth["headers"],
    )
    assert assigned.status_code == 200, assigned.text
    detail = client.get(f"{ORDERS}/{order['id']}", headers=sales_auth["headers"]).json()
    assert detail["fulfilment_assignee_user_id"] == target
    assert detail["fulfilment_assignee_name"] == "Test operations"


# ---- categories and brands ---------------------------------------------------------------------
def test_staff_lists_include_hidden_categories_and_brands_with_counts(
    client, db: Session, operations_auth, customer_auth
):
    shown = Category(name="Phones", slug="phones", sort_order=1)
    hidden = Category(name="Gaming", slug="gaming", sort_order=2, is_active=False)
    child = Category(name="Android", slug="android", parent=shown)
    brand = Brand(name="Samsung", slug="samsung")
    hidden_brand = Brand(name="Hisense", slug="hisense", is_active=False)
    db.add_all([shown, hidden, child, brand, hidden_brand])
    db.flush()
    for i, status in enumerate(["active", "draft"]):
        db.add(
            Product(
                name=f"Phone {i}",
                slug=f"phone-{i}",
                category=child,
                brand=brand,
                specifications={},
                status=status,
            )
        )
    db.commit()
    h = operations_auth["headers"]

    categories = client.get(f"{STAFF}/categories", headers=h).json()["items"]
    by_slug = {c["slug"]: c for c in categories}
    assert set(by_slug) == {"phones", "gaming", "android"}
    assert by_slug["gaming"]["is_active"] is False
    assert by_slug["android"]["parent_id"] == str(shown.id)
    assert (by_slug["android"]["product_count"], by_slug["phones"]["product_count"]) == (2, 0)

    brands = client.get(f"{STAFF}/brands", headers=h).json()["items"]
    assert [(b["name"], b["is_active"], b["product_count"]) for b in brands] == [
        ("Hisense", False, 0),
        ("Samsung", True, 2),
    ]
    for path in ("categories", "brands"):
        assert client.get(f"{STAFF}/{path}", headers=customer_auth["headers"]).status_code == 403


# ---- products ----------------------------------------------------------------------------------
def test_product_rows_have_price_sku_and_stock_and_filter_low_stock(
    client, db: Session, operations_auth
):
    category = Category(name="Phones", slug="phones")
    db.add(category)
    low = Product(name="Low", slug="low", category=category, specifications={}, status="active")
    plenty = Product(
        name="Plenty", slug="plenty", category=category, specifications={}, status="active"
    )
    bare = Product(name="Bare", slug="bare", category=category, specifications={})
    db.add_all([low, plenty, bare])
    db.flush()

    def variant(product, sku, price, on_hand, threshold=3, active=True):
        db.add(
            ProductVariant(
                product=product,
                sku=sku,
                name=sku,
                price=price,
                low_stock_threshold=threshold,
                is_active=active,
                inventory=InventoryBalance(on_hand=on_hand, unavailable_quantity=0),
            )
        )

    variant(low, "LOW-B", 900, 2)  # low: 2 <= 3
    variant(low, "LOW-A", 1200, 10)
    variant(low, "LOW-OFF", 100, 0, active=False)  # inactive: ignored
    variant(plenty, "PLENTY-1", 5000, 40)
    db.commit()

    res = client.get(f"{STAFF}/products", headers=operations_auth["headers"])
    assert res.status_code == 200, res.text
    rows = {r["slug"]: r for r in res.json()["items"]}
    assert (rows["low"]["sku"], rows["low"]["price"]) == ("LOW-A", 900)
    assert (rows["low"]["available_quantity"], rows["low"]["has_low_stock"]) == (12, True)
    assert (rows["plenty"]["available_quantity"], rows["plenty"]["has_low_stock"]) == (40, False)
    assert (rows["bare"]["sku"], rows["bare"]["price"], rows["bare"]["available_quantity"]) == (
        None,
        None,
        0,
    )

    def slugs(**params) -> set[str]:
        page = client.get(f"{STAFF}/products", params=params, headers=operations_auth["headers"])
        return {r["slug"] for r in page.json()["items"]}

    assert slugs(low_stock="true") == {"low"}
    assert slugs(low_stock="false") == {"plenty", "bare"}
    assert uuid.UUID(rows["low"]["id"])
