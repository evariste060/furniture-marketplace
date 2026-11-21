"""Cart price-change notices and line images (frontend phase 4, decision 1 of 2026-10-27;
migration f1a7c3e9d2b4). A line keeps the price it was added at; when the catalogue price
changes, the cart reports the old price until the customer accepts the new ones. Display only:
totals always use the current price. Disposable per-test PostgreSQL schema."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import CartItem, ProductVariant
from tests.integration.test_cart_api import (
    CART,
    MERGE,
    add,
    guest,
    line_id,
    new_guest_cart,
    sku,
)
from tests.integration.test_checkout_api import INLINE, checkout
from tests.integration.test_delivery_api import create_zone, set_threshold
from tests.support.media import image_row

ACCEPT = f"{CART}/accept-prices"


def reprice(db: Session, variant_id: str, price: int) -> None:
    db.execute(
        update(ProductVariant).where(ProductVariant.id == uuid.UUID(variant_id)).values(price=price)
    )
    db.commit()


def line(cart: dict, variant_id: str) -> dict:
    return next(item for item in cart["lines"] if item["variant_id"] == variant_id)


def stored_price(db: Session, variant_id: str) -> int | None:
    db.expire_all()
    return db.scalar(
        select(CartItem.price_at_add).where(CartItem.variant_id == uuid.UUID(variant_id))
    )


def test_a_line_notes_its_price_and_reports_a_change(client, db):
    variant = sku(db, price=230_000)
    token, created = new_guest_cart(client, variant)
    assert line(created, variant)["previous_unit_price"] is None
    assert created["has_price_changes"] is False
    assert stored_price(db, variant) == 230_000

    reprice(db, variant, 245_000)
    cart = client.get(CART, headers=guest(token)).json()
    assert line(cart, variant)["unit_price"] == 245_000  # totals use today's price
    assert line(cart, variant)["previous_unit_price"] == 230_000
    assert cart["has_price_changes"] is True and cart["merchandise_subtotal"] == 245_000


def test_accepting_clears_every_notice_and_is_idempotent(client, db):
    a, b = sku(db, price=1_000), sku(db, price=2_000)
    token, _ = new_guest_cart(client, a)
    add(client, b, 1, guest(token))
    reprice(db, a, 1_100)
    reprice(db, b, 1_900)
    accepted = client.post(ACCEPT, headers=guest(token))
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["has_price_changes"] is False
    assert [item["previous_unit_price"] for item in body["lines"]] == [None, None]
    assert stored_price(db, a) == 1_100 and stored_price(db, b) == 1_900
    assert client.post(ACCEPT, headers=guest(token)).json()["has_price_changes"] is False


def test_adding_more_units_notes_the_current_price(client, db):
    variant = sku(db, price=5_000)
    token, _ = new_guest_cart(client, variant)
    reprice(db, variant, 6_000)
    topped = add(client, variant, 1, guest(token)).json()
    assert line(topped, variant)["quantity"] == 2
    assert line(topped, variant)["previous_unit_price"] is None


def test_changing_the_quantity_keeps_the_notice(client, db):
    variant = sku(db, price=5_000)
    token, created = new_guest_cart(client, variant, 2)
    reprice(db, variant, 4_500)
    lowered = client.patch(
        f"{CART}/items/{line_id(created, variant)}", json={"quantity": 1}, headers=guest(token)
    ).json()
    assert line(lowered, variant)["previous_unit_price"] == 5_000


def test_flagged_lines_and_older_lines_report_no_previous_price(client, db):
    gone = sku(db, price=3_000, on_hand=1)
    old = sku(db, price=4_000)
    token, _ = new_guest_cart(client, gone)
    add(client, old, 1, guest(token))
    db.execute(
        update(CartItem).where(CartItem.variant_id == uuid.UUID(old)).values(price_at_add=None)
    )
    db.commit()
    reprice(db, old, 4_400)
    reprice(db, gone, 3_300)
    db.execute(
        update(ProductVariant).where(ProductVariant.id == uuid.UUID(gone)).values(is_active=False)
    )
    db.commit()
    cart = client.get(CART, headers=guest(token)).json()
    assert line(cart, gone)["status"] == "unavailable"
    assert line(cart, gone)["previous_unit_price"] is None
    assert line(cart, old)["previous_unit_price"] is None  # added before the column existed
    assert cart["has_price_changes"] is False


def test_merge_carries_the_guest_price_and_keeps_the_customer_line(client, db, customer_auth):
    shared, only_guest = sku(db, price=1_000), sku(db, price=2_000)
    h = customer_auth["headers"]
    add(client, shared, 1, h)
    token, _ = new_guest_cart(client, shared)
    add(client, only_guest, 1, guest(token))
    reprice(db, only_guest, 2_500)
    merged = client.post(MERGE, headers={**h, **guest(token)})
    assert merged.status_code == 200, merged.text
    cart = merged.json()["cart"]
    assert line(cart, only_guest)["previous_unit_price"] == 2_000
    assert line(cart, shared)["previous_unit_price"] is None


def test_customers_accept_their_own_cart_and_a_visitor_without_one_gets_an_empty_cart(
    client, db, customer_auth
):
    variant = sku(db, price=1_000)
    h = customer_auth["headers"]
    assert client.post(ACCEPT, headers=h).json()["lines"] == []
    assert client.post(ACCEPT).json()["id"] is None
    add(client, variant, 1, h)
    reprice(db, variant, 900)
    assert client.get(CART, headers=h).json()["has_price_changes"] is True
    assert client.post(ACCEPT, headers=h).json()["has_price_changes"] is False


def test_lines_show_the_variant_image_else_the_product_image(client, db):
    with_own, product_only, none = sku(db), sku(db), sku(db)
    own = db.get(ProductVariant, uuid.UUID(with_own))
    other = db.get(ProductVariant, uuid.UUID(product_only))
    assert own is not None and other is not None
    db.add_all(
        [
            image_row(own.product_id, 0, alt_text="Product front"),
            image_row(own.product_id, 1, variant_id=own.id, alt_text="Navy back"),
            image_row(other.product_id, 3, alt_text="Box"),
            image_row(other.product_id, 2, alt_text="Front"),
        ]
    )
    db.commit()
    token, _ = new_guest_cart(client, with_own)
    add(client, product_only, 1, guest(token))
    add(client, none, 1, guest(token))
    cart = client.get(CART, headers=guest(token)).json()
    assert line(cart, with_own)["image"]["alt"] == "Navy back"
    assert line(cart, product_only)["image"]["alt"] == "Front"
    assert line(cart, product_only)["image"]["url"].startswith("http")
    assert line(cart, none)["image"] is None


def test_order_lines_show_the_image_too(client, db, admin_auth):
    create_zone(client, admin_auth["headers"], "Gasabo", 2000)
    set_threshold(client, admin_auth["headers"], 10**9)
    variant = sku(db, price=10_000)
    stored = db.get(ProductVariant, uuid.UUID(variant))
    assert stored is not None
    db.add(image_row(stored.product_id, 0, alt_text="Front"))
    db.commit()
    token, _ = new_guest_cart(client, variant)
    res = checkout(client, guest(token), {"address": INLINE, "payment_method": "mtn_momo"})
    assert res.status_code == 201, res.text
    assert res.json()["order"]["lines"][0]["image"]["alt"] == "Front"
