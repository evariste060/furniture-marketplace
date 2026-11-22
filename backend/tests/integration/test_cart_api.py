"""Module 11 — cart (TC-05; plan §5, §7 Q10; RE-026 B7).

Runs on the disposable per-test PostgreSQL schema (tests/conftest.py).
"""

import hashlib
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.main import app
from app.models import Cart, CartItem, Category, Product, ProductVariant
from app.services import cart_service
from app.services.pricing import quote_merchandise
from tests.support.commerce import seed_sku

CART = "/api/v1/cart"
ITEMS = f"{CART}/items"
MERGE = f"{CART}/merge"


def code(res) -> str:
    return res.json()["error"]["code"]


def sku(db: Session, *, on_hand: int | None = 10, price: int = 1000, **overrides) -> str:
    variant = seed_sku(db, on_hand=on_hand, **overrides)
    variant.price = price
    db.commit()
    return str(variant.id)


def guest(token: str | None) -> dict:
    return {"X-Cart-Token": token} if token else {}


def add(client: TestClient, variant_id: str, quantity: int = 1, headers: dict | None = None):
    return client.post(
        ITEMS, json={"variant_id": variant_id, "quantity": quantity}, headers=headers or {}
    )


def new_guest_cart(client: TestClient, variant_id: str, quantity: int = 1) -> tuple[str, dict]:
    res = add(client, variant_id, quantity)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cart_token"]
    return body["cart_token"], body


def carts(db: Session) -> list[Cart]:
    db.expire_all()
    return list(db.scalars(select(Cart).order_by(Cart.created_at)))


def line_id(cart: dict, variant_id: str) -> str:
    return next(line["id"] for line in cart["lines"] if line["variant_id"] == variant_id)


# ---- guest token -----------------------------------------------------------------------------
def test_a_guest_without_a_token_gets_an_empty_cart_and_nothing_is_created(client, db):
    res = client.get(CART)
    assert res.status_code == 200
    assert res.json() == {
        "id": None,
        "owner": "guest",
        "expires_at": None,
        "lines": [],
        "item_count": 0,
        "merchandise_subtotal": 0,
        "currency_code": "RWF",
        "has_unavailable_lines": False,
        "has_price_changes": False,  # frontend phase 4
        "discount": None,  # module 13
        "discount_total": 0,
        "subtotal_after_discount": 0,
        "delivery": None,  # only with ?zone= (module 12)
        "grand_total": None,
        "cart_token": None,
    }
    assert carts(db) == []


def test_the_first_add_creates_a_guest_cart_and_shows_the_token_once(client, db):
    variant = sku(db, price=2500)
    token, body = new_guest_cart(client, variant, 2)
    assert len(token) >= 40 and body["owner"] == "guest"
    assert body["merchandise_subtotal"] == 5000 and body["item_count"] == 2
    (stored,) = carts(db)
    assert stored.guest_token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert stored.guest_token_hash != token and stored.user_id is None
    raw = db.execute(text("SELECT row_to_json(c)::text FROM carts c")).scalar_one()
    assert token not in raw  # only the hash is stored
    again = client.get(CART, headers=guest(token)).json()
    assert again["cart_token"] is None and again["id"] == body["id"]
    more = add(client, variant, 1, guest(token)).json()
    assert more["cart_token"] is None and more["lines"][0]["quantity"] == 3
    assert len(carts(db)) == 1


def test_each_line_names_the_store_that_sells_it(client, db):
    """ADR-014 phase 5: "Sold by" in the cart, from the product's store (never the browser)."""
    variant = sku(db)
    _, body = new_guest_cart(client, variant)
    product = db.get(ProductVariant, uuid.UUID(variant)).product
    assert body["lines"][0]["store"] == {
        "id": str(product.store.id),
        "name": product.store.name,
        "slug": product.store.slug,
    }


def test_two_guests_without_tokens_get_separate_carts(client, db):
    variant = sku(db)
    first, _ = new_guest_cart(client, variant)
    second, _ = new_guest_cart(client, variant)
    assert first != second and len(carts(db)) == 2


@pytest.mark.parametrize("method", ["get", "add", "patch", "delete"])
def test_an_unknown_token_is_404_everywhere_and_never_creates_a_cart(client, db, method):
    variant = sku(db)
    unknown = guest("x" * 43)
    item = "6f1c2e9a-3b4d-4e5f-8a9b-0c1d2e3f4a5b"
    res = {
        "get": lambda: client.get(CART, headers=unknown),
        "add": lambda: add(client, variant, 1, unknown),
        "patch": lambda: client.patch(f"{ITEMS}/{item}", json={"quantity": 1}, headers=unknown),
        "delete": lambda: client.delete(f"{ITEMS}/{item}", headers=unknown),
    }[method]()
    assert res.status_code == 404 and code(res) == "cart_not_found"
    assert carts(db) == []


@pytest.mark.parametrize("token", ["short", "has spaces in it padding padding", "a" * 101])
def test_a_malformed_token_is_422(client, token):
    assert client.get(CART, headers={"X-Cart-Token": token}).status_code == 422


# ---- expiry ----------------------------------------------------------------------------------
def test_guest_carts_expire_30_days_after_their_last_change(client, db):
    variant = sku(db)
    token, body = new_guest_cart(client, variant)
    (stored,) = carts(db)
    now = db.scalar(select(func.now()))
    assert abs(stored.expires_at - (now + timedelta(days=30))) < timedelta(minutes=1)
    assert body["expires_at"] is not None
    db.execute(update(Cart).values(expires_at=func.now() + timedelta(days=1)))
    db.commit()
    soon = carts(db)[0].expires_at
    client.get(CART, headers=guest(token))  # a read does not renew it
    assert carts(db)[0].expires_at == soon
    add(client, variant, 1, guest(token))  # a change does
    assert carts(db)[0].expires_at > now + timedelta(days=29)


def test_an_expired_guest_cart_cannot_be_read_changed_or_revived(client, db):
    variant = sku(db)
    token, body = new_guest_cart(client, variant)
    item = body["lines"][0]["id"]
    db.execute(update(Cart).values(expires_at=func.now() - timedelta(seconds=1)))
    db.commit()
    attempts = [
        client.get(CART, headers=guest(token)),
        add(client, variant, 1, guest(token)),
        client.patch(f"{ITEMS}/{item}", json={"quantity": 2}, headers=guest(token)),
        client.delete(f"{ITEMS}/{item}", headers=guest(token)),
    ]
    assert [r.status_code for r in attempts] == [404] * 4
    assert {code(r) for r in attempts} == {"cart_not_found"}
    (stored,) = carts(db)
    assert stored.status == "abandoned"  # marked when presented; no job needed
    db.expire_all()
    assert db.scalar(select(CartItem.quantity)) == 1  # nothing changed
    fresh_token, _ = new_guest_cart(client, variant)  # without the token, a new cart
    assert fresh_token != token and len(carts(db)) == 2


# ---- customers and ownership -----------------------------------------------------------------
def test_a_customer_cart_has_no_token_and_no_expiry(client, db, customer_auth):
    variant = sku(db)
    h = customer_auth["headers"]
    assert client.get(CART, headers=h).json()["owner"] == "customer"
    body = add(client, variant, 2, h).json()
    assert body["owner"] == "customer" and body["cart_token"] is None
    assert body["expires_at"] is None
    (stored,) = carts(db)
    assert str(stored.user_id) == customer_auth["user"]["id"] and stored.guest_token_hash is None
    add(client, variant, 1, h)
    assert len(carts(db)) == 1 and client.get(CART, headers=h).json()["lines"][0]["quantity"] == 3


def test_owners_never_see_or_change_each_others_lines(
    client, db, customer_auth, second_customer_auth
):
    variant = sku(db)
    a, b = customer_auth["headers"], second_customer_auth["headers"]
    a_line = line_id(add(client, variant, 1, a).json(), variant)
    g_token, g_cart = new_guest_cart(client, variant)
    g_line = line_id(g_cart, variant)
    missing = "6f1c2e9a-3b4d-4e5f-8a9b-0c1d2e3f4a5b"
    assert client.get(CART, headers=b).json()["lines"] == []
    for headers, foreign in ((b, a_line), (guest(g_token), a_line), (a, g_line), (b, g_line)):
        patched = client.patch(f"{ITEMS}/{foreign}", json={"quantity": 2}, headers=headers)
        deleted = client.delete(f"{ITEMS}/{foreign}", headers=headers)
        nothing = client.patch(f"{ITEMS}/{missing}", json={"quantity": 2}, headers=headers)
        assert patched.status_code == deleted.status_code == 404
        assert patched.json() == nothing.json()  # same answer as a line that does not exist
    db.expire_all()
    assert sorted(db.scalars(select(CartItem.quantity))) == [1, 1]


def test_a_customer_token_ignores_x_cart_token_except_for_merge(client, db, customer_auth):
    variant = sku(db)
    token, _ = new_guest_cart(client, variant, 2)
    body = client.get(CART, headers={**customer_auth["headers"], **guest(token)}).json()
    assert body["owner"] == "customer" and body["lines"] == []


def test_staff_accounts_have_no_cart(client, db, admin_auth):
    variant = sku(db)
    for staff in (admin_auth,):  # the only staff role since SC-05
        attempts = [
            client.get(CART, headers=staff["headers"]),
            add(client, variant, 1, staff["headers"]),
            client.post(MERGE, headers={**staff["headers"], **guest("y" * 43)}),
        ]
        assert [r.status_code for r in attempts] == [403] * 3
        assert {code(r) for r in attempts} == {"customer_only"}
    assert carts(db) == []


def test_an_invalid_bearer_token_is_401_not_a_guest(client, db):
    variant = sku(db)
    bad = {"Authorization": "Bearer not-a-real-session-token"}
    assert client.get(CART, headers=bad).status_code == 401
    assert add(client, variant, 1, bad).status_code == 401
    assert carts(db) == []


# ---- lines and quantities --------------------------------------------------------------------
def test_add_update_and_remove_a_line(client, db, customer_auth):
    h = customer_auth["headers"]
    variant = sku(db, on_hand=20, price=700)
    cart = add(client, variant, 2, h).json()
    item = line_id(cart, variant)
    assert add(client, variant, 3, h).json()["lines"][0]["quantity"] == 5  # added to the line
    updated = client.patch(f"{ITEMS}/{item}", json={"quantity": 9}, headers=h)
    assert updated.status_code == 200
    assert updated.json()["lines"][0]["quantity"] == 9
    assert updated.json()["merchandise_subtotal"] == 6300
    removed = client.delete(f"{ITEMS}/{item}", headers=h)
    assert removed.status_code == 204 and removed.content == b""
    assert client.get(CART, headers=h).json()["lines"] == []
    again = client.delete(f"{ITEMS}/{item}", headers=h)
    assert again.status_code == 404 and code(again) == "cart_item_not_found"


@pytest.mark.parametrize(
    ("quantity", "status"), [(1, 200), (99, 200), (0, 422), (-1, 422), (100, 422), (1.5, 422)]
)
def test_quantity_bounds(client, db, customer_auth, quantity, status):
    variant = sku(db, on_hand=200)
    res = add(client, variant, quantity, customer_auth["headers"])
    assert res.status_code == status, res.text
    item_res = add(client, sku(db, on_hand=200), 1, customer_auth["headers"]).json()
    item = item_res["lines"][-1]["id"]
    patched = client.patch(
        f"{ITEMS}/{item}", json={"quantity": quantity}, headers=customer_auth["headers"]
    )
    assert patched.status_code == status


def test_a_line_never_exceeds_99_units_in_total(client, db, customer_auth):
    h = customer_auth["headers"]
    variant = sku(db, on_hand=500)
    add(client, variant, 60, h)
    res = add(client, variant, 40, h)
    assert res.status_code == 422
    assert res.json()["error"]["details"][0]["loc"] == ["body", "quantity"]
    assert client.get(CART, headers=h).json()["lines"][0]["quantity"] == 60


def test_more_than_is_available_is_refused_not_capped(client, db, customer_auth):
    h = customer_auth["headers"]
    variant = sku(db, on_hand=3)
    assert add(client, variant, 4, h).status_code == 409
    cart = add(client, variant, 3, h).json()
    over = add(client, variant, 1, h)
    assert over.status_code == 409 and code(over) == "insufficient_stock"
    patched = client.patch(f"{ITEMS}/{line_id(cart, variant)}", json={"quantity": 4}, headers=h)
    assert patched.status_code == 409
    assert client.get(CART, headers=h).json()["lines"][0]["quantity"] == 3


def test_a_refused_first_add_creates_no_guest_cart_and_no_token(client, db):
    res = add(client, sku(db, on_hand=1), 2)
    assert res.status_code == 409 and "cart_token" not in res.text
    assert carts(db) == []


@pytest.mark.parametrize("kind", ["unknown", "inactive_variant", "hidden_product", "no_stock_row"])
def test_unsellable_or_unknown_variants_cannot_be_added(client, db, customer_auth, kind):
    variant = {
        "unknown": lambda: "6f1c2e9a-3b4d-4e5f-8a9b-0c1d2e3f4a5b",
        "inactive_variant": lambda: sku(db, is_active=False),
        "hidden_product": lambda: _hidden(db),
        "no_stock_row": lambda: sku(db, on_hand=None),
    }[kind]()
    res = add(client, variant, 1, customer_auth["headers"])
    if kind == "no_stock_row":
        assert res.status_code == 409 and code(res) == "insufficient_stock"
    else:
        assert res.status_code == 422
        assert res.json()["error"]["details"][0]["loc"] == ["body", "variant_id"]
    assert client.get(CART, headers=customer_auth["headers"]).json()["lines"] == []


def _hidden(db: Session) -> str:
    variant_id = sku(db)
    db.execute(
        update(Product)
        .where(
            Product.id
            == select(ProductVariant.product_id)
            .where(ProductVariant.id == variant_id)
            .scalar_subquery()
        )
        .values(status="hidden")
    )
    db.commit()
    return variant_id


# ---- totals ----------------------------------------------------------------------------------
def test_invalid_lines_are_flagged_and_left_out_of_the_totals(client, db, customer_auth):
    h = customer_auth["headers"]
    good, gone, short, category_off = (
        sku(db, on_hand=10, price=1000),
        sku(db, on_hand=10, price=2000),
        sku(db, on_hand=10, price=3000),
        sku(db, on_hand=10, price=4000),
    )
    for variant, quantity in ((good, 2), (gone, 1), (short, 5), (category_off, 1)):
        assert add(client, variant, quantity, h).status_code == 200
    db.execute(update(ProductVariant).where(ProductVariant.id == gone).values(is_active=False))
    db.execute(
        text("UPDATE inventory_balances SET on_hand = 2 WHERE variant_id = :v"), {"v": short}
    )
    category_id = db.scalar(
        select(Product.category_id).join(ProductVariant).where(ProductVariant.id == category_off)
    )
    db.execute(update(Category).where(Category.id == category_id).values(is_active=False))
    db.commit()
    body = client.get(CART, headers=h).json()
    status = {line["variant_id"]: line["status"] for line in body["lines"]}
    assert status == {
        good: "available",
        gone: "unavailable",
        short: "insufficient_stock",
        category_off: "unavailable",
    }
    assert body["merchandise_subtotal"] == 2000 and body["item_count"] == 2
    assert body["has_unavailable_lines"] is True
    flagged = [line for line in body["lines"] if line["status"] != "available"]
    assert all(line["unit_price"] is None and line["line_subtotal"] is None for line in flagged)
    assert len(body["lines"]) == 4  # flagged lines stay in the cart
    gone_line = line_id(body, gone)
    refused = client.patch(f"{ITEMS}/{gone_line}", json={"quantity": 1}, headers=h)
    assert refused.status_code == 409 and code(refused) == "variant_unavailable"
    assert client.delete(f"{ITEMS}/{gone_line}", headers=h).status_code == 204


def test_totals_match_the_pricing_service_and_follow_database_prices(client, db, customer_auth):
    h = customer_auth["headers"]
    a, b = sku(db, price=1250), sku(db, price=999)
    add(client, a, 3, h)
    body = add(client, b, 2, h).json()
    quote = quote_merchandise(
        db, [(uuid.UUID(line["variant_id"]), line["quantity"]) for line in body["lines"]]
    )
    assert body["merchandise_subtotal"] == quote.merchandise_subtotal == 5748
    db.execute(update(ProductVariant).where(ProductVariant.id == a).values(price=1300))
    db.commit()
    assert client.get(CART, headers=h).json()["merchandise_subtotal"] == 3 * 1300 + 2 * 999


@pytest.mark.parametrize(
    "extra",
    [
        {"price": 1},
        {"unit_price": 1},
        {"line_subtotal": 1},
        {"total": 1},
        {"merchandise_subtotal": 1},
    ],
)
def test_client_prices_and_totals_are_refused(client, db, customer_auth, extra):
    variant = sku(db, price=5000)
    res = client.post(
        ITEMS,
        json={"variant_id": variant, "quantity": 1, **extra},
        headers=customer_auth["headers"],
    )
    assert res.status_code == 422
    item = add(client, variant, 1, customer_auth["headers"]).json()["lines"][0]["id"]
    patched = client.patch(
        f"{ITEMS}/{item}", json={"quantity": 2, **extra}, headers=customer_auth["headers"]
    )
    assert patched.status_code == 422
    assert client.get(CART, headers=customer_auth["headers"]).json()["merchandise_subtotal"] == 5000


# ---- delivery zone (module 12; full coverage in test_delivery_api.py) -----------------------
def test_an_unknown_zone_is_refused_without_a_partial_cart(client, db, customer_auth):
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    res = client.get(CART, params={"zone": "kigali-city"}, headers=h)
    assert res.status_code == 422 and code(res) == "delivery_zone_unavailable"
    assert "merchandise_subtotal" not in res.text  # an error, not a partial cart with a fee
    plain = client.get(CART, headers=h)
    assert plain.status_code == 200
    assert plain.json()["delivery"] is None and plain.json()["grand_total"] is None
    assert client.get(CART, params={"zone": ""}, headers=h).status_code == 422
    unknown_guest = client.get(CART, params={"zone": "kigali"}, headers=guest("z" * 43))
    assert unknown_guest.status_code == 404  # ownership is checked first


# ---- merge -----------------------------------------------------------------------------------
def test_merge_adds_guest_quantities_with_caps_and_closes_the_guest_cart(client, db, customer_auth):
    h = customer_auth["headers"]
    plain, near_limit, low_stock, gone, empty = (
        sku(db, on_hand=50),
        sku(db, on_hand=500),
        sku(db, on_hand=6),
        sku(db, on_hand=10),
        sku(db, on_hand=4),
    )
    add(client, near_limit, 95, h)
    add(client, low_stock, 4, h)
    token, _ = new_guest_cart(client, plain, 3)
    for variant, quantity in ((near_limit, 10), (low_stock, 5), (gone, 2), (empty, 4)):
        assert add(client, variant, quantity, guest(token)).status_code == 200
    db.execute(update(ProductVariant).where(ProductVariant.id == gone).values(is_active=False))
    db.execute(
        text("UPDATE inventory_balances SET on_hand = 0 WHERE variant_id = :v"), {"v": empty}
    )
    db.commit()

    res = client.post(MERGE, headers={**h, **guest(token)})
    assert res.status_code == 200, res.text
    body = res.json()
    outcome = {
        line["variant_id"]: (
            line["guest_quantity"],
            line["added_quantity"],
            line["outcome"],
            line["reason"],
        )
        for line in body["merged_lines"]
    }
    assert outcome == {
        plain: (3, 3, "merged", None),
        near_limit: (10, 4, "capped", "line_limit"),
        low_stock: (5, 2, "capped", "insufficient_stock"),
        gone: (2, 0, "excluded", "unavailable"),
        empty: (4, 0, "excluded", "insufficient_stock"),
    }
    quantities = {line["variant_id"]: line["quantity"] for line in body["cart"]["lines"]}
    assert quantities == {near_limit: 99, low_stock: 6, plain: 3}
    assert body["cart"]["owner"] == "customer" and body["cart"]["cart_token"] is None
    statuses = {c.guest_token_hash is None: c.status for c in carts(db)}
    assert statuses == {True: "active", False: "converted"}
    db.expire_all()
    guest_cart = db.scalar(select(Cart).where(Cart.guest_token_hash.is_not(None)))
    assert db.scalar(select(func.count()).where(CartItem.cart_id == guest_cart.id)) == 5  # kept

    retry = client.post(MERGE, headers={**h, **guest(token)})
    assert retry.status_code == 404 and code(retry) == "cart_not_found"
    assert client.get(CART, headers=guest(token)).status_code == 404
    after = {
        line["variant_id"]: line["quantity"] for line in client.get(CART, headers=h).json()["lines"]
    }
    assert after == quantities  # a retry never adds twice


def test_merge_creates_the_customer_cart_when_there_is_none(client, db, customer_auth):
    variant = sku(db)
    token, _ = new_guest_cart(client, variant, 2)
    res = client.post(MERGE, headers={**customer_auth["headers"], **guest(token)})
    assert res.status_code == 200
    assert res.json()["cart"]["lines"][0]["quantity"] == 2


def test_merge_is_for_customers_with_a_valid_guest_token(client, db, customer_auth):
    variant = sku(db)
    token, _ = new_guest_cart(client, variant)
    assert client.post(MERGE, headers=guest(token)).status_code == 401
    missing = client.post(MERGE, headers=customer_auth["headers"])
    assert missing.status_code == 422
    unknown = client.post(MERGE, headers={**customer_auth["headers"], **guest("q" * 43)})
    assert unknown.status_code == 404
    db.execute(update(Cart).values(expires_at=func.now() - timedelta(seconds=1)))
    db.commit()
    expired = client.post(MERGE, headers={**customer_auth["headers"], **guest(token)})
    assert expired.status_code == 404 and carts(db)[0].status == "abandoned"


def test_a_failed_merge_changes_nothing(client, db, customer_auth, monkeypatch):
    h = customer_auth["headers"]
    variant = sku(db, on_hand=20)
    add(client, variant, 2, h)
    token, _ = new_guest_cart(client, variant, 3)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure while merging")

    monkeypatch.setattr(cart_service, "_merge_line", boom)
    with pytest.raises(RuntimeError):
        client.post(MERGE, headers={**h, **guest(token)})
    monkeypatch.undo()
    assert client.get(CART, headers=h).json()["lines"][0]["quantity"] == 2
    assert client.get(CART, headers=guest(token)).json()["lines"][0]["quantity"] == 3
    assert {c.status for c in carts(db)} == {"active"}


# ---- OpenAPI ---------------------------------------------------------------------------------
def test_openapi_documents_the_cart_routes():
    app.openapi_schema = None
    paths = app.openapi()["paths"]
    assert set(paths["/api/v1/cart"]) == {"get"}
    assert set(paths["/api/v1/cart/items"]) == {"post"}
    assert set(paths["/api/v1/cart/items/{item_id}"]) == {"patch", "delete"}
    assert set(paths["/api/v1/cart/merge"]) == {"post"}
    get = paths["/api/v1/cart"]["get"]
    assert {"200", "401", "403", "404", "422", "503"} <= set(get["responses"])
    assert {p["name"] for p in get["parameters"]} >= {"zone", "X-Cart-Token"}
    add_body = app.openapi()["components"]["schemas"]["CartItemAddRequest"]
    assert set(add_body["properties"]) == {"variant_id", "quantity"}
    assert add_body["additionalProperties"] is False


# ---- amounts beyond the storable range (pricing.MAX_AMOUNT) ----------------------------------
HUGE = 20_000_000_000  # 2e10 RWF: 50 units exceed the 999,999,999,999 cap


def test_unrepresentable_amounts_are_refused_on_add_and_update(
    client, db, customer_auth, second_customer_auth
):
    h = customer_auth["headers"]
    variant = sku(db, on_hand=99, price=HUGE)
    cart = add(client, variant, 1, h).json()
    assert cart["merchandise_subtotal"] == HUGE
    too_many = add(client, variant, 49, h)  # 50 x 2e10 = 1e12 > 999,999,999,999
    assert too_many.status_code == 422
    assert too_many.json()["error"]["details"][0]["loc"] == ["body", "quantity"]
    patched = client.patch(f"{ITEMS}/{line_id(cart, variant)}", json={"quantity": 60}, headers=h)
    assert patched.status_code == 422
    assert add(client, variant, 48, h).status_code == 200  # 49 x 2e10 fits
    assert client.get(CART, headers=h).json()["lines"][0]["quantity"] == 49
    # The cart total counts too: a line at exactly the cap, then one more RWF elsewhere.
    other = second_customer_auth["headers"]
    assert add(client, sku(db, price=999_999_999_999), 1, other).status_code == 200
    one_more = add(client, sku(db, price=1), 1, other)
    assert one_more.status_code == 422
    body = client.get(CART, headers=other).json()
    assert body["merchandise_subtotal"] == 999_999_999_999 and len(body["lines"]) == 1


def test_a_read_flags_lines_beyond_the_amount_range_instead_of_failing(client, db, customer_auth):
    h = customer_auth["headers"]
    first, second, cheap = sku(db, on_hand=99), sku(db, on_hand=99), sku(db, on_hand=99, price=500)
    add(client, first, 30, h)
    add(client, second, 30, h)
    add(client, cheap, 2, h)
    # Prices raised by staff afterwards: each line alone is 6e11; both together exceed the cap.
    db.execute(
        update(ProductVariant).where(ProductVariant.id.in_([first, second])).values(price=HUGE)
    )
    db.commit()
    res = client.get(CART, headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    status = {line["variant_id"]: line["status"] for line in body["lines"]}
    assert status == {first: "available", second: "amount_out_of_range", cheap: "available"}
    assert body["merchandise_subtotal"] == 30 * HUGE + 2 * 500
    assert body["has_unavailable_lines"] is True
    flagged = next(line for line in body["lines"] if line["variant_id"] == second)
    assert flagged["unit_price"] is None and flagged["line_subtotal"] is None
    db.execute(update(ProductVariant).where(ProductVariant.id == first).values(price=10**12 - 1))
    db.commit()
    alone = client.get(CART, headers=h)  # 30 x (1e12 - 1) alone is beyond the cap
    assert alone.status_code == 200
    assert {line["variant_id"]: line["status"] for line in alone.json()["lines"]}[first] == (
        "amount_out_of_range"
    )


# ---- cross-origin browser use ----------------------------------------------------------------
def test_a_cross_origin_guest_request_with_x_cart_token_is_allowed(client, db):
    token, _ = new_guest_cart(client, sku(db))
    origin = {"Origin": "http://localhost:3000"}
    preflight = client.options(
        CART,
        headers={
            **origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-cart-token",
        },
    )
    assert preflight.status_code == 200
    res = client.get(CART, headers={**origin, **guest(token)})
    assert res.status_code == 200 and len(res.json()["lines"]) == 1
    assert res.headers["access-control-allow-origin"] == "http://localhost:3000"
