"""Module 13 — promotions and discounts (RE-026 B3, B6; ADR-007; TC-06). Runs on the disposable
per-test PostgreSQL schema (tests/conftest.py); locks are real PostgreSQL row locks."""

import logging
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.rate_limit import CartRateLimiter, get_cart_rate_limiter
from app.main import app
from app.models import (
    Category,
    Discount,
    DiscountRedemption,
    DiscountTarget,
    Product,
    ProductVariant,
)
from app.models.operations import AuditRecord
from app.services import promotion_service
from app.services.inventory import create_order_with_reservations, expire_due_reservations
from app.services.promotion_service import PromotionNotApplicable, redeem, release_for_order
from tests.integration.test_cart_api import add, code, guest, sku
from tests.integration.test_cart_security import DownStore, _settings, peer
from tests.integration.test_delivery_api import create_zone, set_threshold
from tests.support.commerce import new_order, seed_sku, soon, wait_until_due

PROMOTIONS = "/api/v1/staff/promotions"
CART = "/api/v1/cart"
APPLY = f"{CART}/apply-code"
REMOVE = f"{CART}/code"
ORDERS = "/api/v1/staff/orders"


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.isoformat()


def create_promotion(client: TestClient, headers: dict, **fields) -> dict:
    body = {
        "code": fields.pop("code", f"P{uuid.uuid4().hex[:8]}"),
        "name": fields.pop("name", "Test promotion"),
        "kind": fields.pop("kind", "percent"),
        "status": fields.pop("status", "active"),
        **fields,
    }
    if body["kind"] == "percent":
        body.setdefault("percent_off", 10)
    else:
        body.setdefault("amount_off", 1000)
    res = client.post(PROMOTIONS, json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def apply(client: TestClient, headers: dict, value: str):
    return client.post(APPLY, json={"code": value}, headers=headers)


def facts(db: Session, variant_id: str) -> tuple[uuid.UUID, uuid.UUID | None, uuid.UUID]:
    variant = db.get(ProductVariant, uuid.UUID(variant_id))
    assert variant is not None
    product = db.get(Product, variant.product_id)
    assert product is not None
    return product.id, product.brand_id, product.category_id


def audits(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == action)))


def placed_order(db: Session, *, user_id=None, expires_at: datetime | None = None) -> uuid.UUID:
    """An order with one reserved line (as checkout will create it), committed."""
    variant = seed_sku(db, on_hand=5)
    order = new_order({variant.id: 1}, user_id=user_id)
    create_order_with_reservations(db, order, expires_at=expires_at or soon())
    db.commit()
    return order.id


# ---- staff permissions (B6) ----------------------------------------------------------------
def test_management_can_view_promotions_but_not_change_them(client, admin_auth, management_auth):
    promo = create_promotion(client, admin_auth["headers"])
    h = management_auth["headers"]
    assert client.get(PROMOTIONS, headers=h).status_code == 200
    assert client.get(f"{PROMOTIONS}/{promo['id']}", headers=h).status_code == 200
    body = {"code": "MGMT10", "name": "x", "kind": "percent", "percent_off": 10}
    assert client.post(PROMOTIONS, json=body, headers=h).status_code == 403
    res = client.patch(f"{PROMOTIONS}/{promo['id']}", json={"status": "disabled"}, headers=h)
    assert res.status_code == 403
    assert client.get(f"{PROMOTIONS}/{promo['id']}", headers=h).json()["status"] == "active"


@pytest.mark.parametrize(
    ("who", "read"),
    # Sales views promotions (promotions:read, final matrix 2026-10-26) but cannot change them.
    [("sales_auth", 200), ("operations_auth", 403), ("customer_auth", 403), (None, 401)],
)
def test_other_roles_and_anonymous_callers_are_refused(client, request, admin_auth, who, read):
    promo = create_promotion(client, admin_auth["headers"])
    headers = request.getfixturevalue(who)["headers"] if who else {}
    expected = 403 if who else 401
    body = {"code": "NOPE10", "name": "x", "kind": "percent", "percent_off": 10}
    calls = [
        client.get(PROMOTIONS, headers=headers),
        client.get(f"{PROMOTIONS}/{promo['id']}", headers=headers),
        client.post(PROMOTIONS, json=body, headers=headers),
        client.patch(f"{PROMOTIONS}/{promo['id']}", json={"name": "y"}, headers=headers),
    ]
    assert [r.status_code for r in calls] == [read, read, expected, expected]


# ---- staff create, read, update ------------------------------------------------------------
def test_create_normalises_the_code_stores_kigali_dates_in_utc_and_audits(client, db, admin_auth):
    promo = create_promotion(
        client,
        admin_auth["headers"],
        code="  welcome-10 ",
        starts_at="2026-11-01T00:00:00",
        ends_at="2026-12-01T00:00:00",
        status="draft",
    )
    assert promo["code"] == "WELCOME-10"
    assert promo["starts_at"] == "2026-11-01T00:00:00+02:00"  # shown in Kigali time
    stored = db.get(Discount, uuid.UUID(promo["id"]))
    assert stored is not None and stored.code == "WELCOME-10"
    assert stored.starts_at == datetime(2026, 10, 31, 22, 0, tzinfo=UTC)
    assert stored.ends_at == datetime(2026, 11, 30, 22, 0, tzinfo=UTC)
    assert promo["active_redemptions"] == 0 and promo["targets"] == []
    [record] = audits(db, "promotion.create")
    assert record.entity_id == promo["id"] and record.change_summary["code"] == "WELCOME-10"


def test_codes_are_unique_ignoring_case(client, db, admin_auth):
    create_promotion(client, admin_auth["headers"], code="SUMMER")
    body = {"code": "summer", "name": "x", "kind": "fixed", "amount_off": 500}
    res = client.post(PROMOTIONS, json=body, headers=admin_auth["headers"])
    assert res.status_code == 409 and code(res) == "promotion_code_taken"
    other = create_promotion(client, admin_auth["headers"], code="WINTER")
    res = client.patch(
        f"{PROMOTIONS}/{other['id']}", json={"code": "Summer"}, headers=admin_auth["headers"]
    )
    assert res.status_code == 409 and code(res) == "promotion_code_taken"
    db.add(Discount(code="lower", name="x", kind="percent", percent_off=5))
    with pytest.raises(Exception, match="code_upper_case"):
        db.commit()  # the database refuses a code that is not upper-case
    db.rollback()


@pytest.mark.parametrize(
    "body",
    [
        {"code": "BAD CODE", "name": "x", "kind": "percent", "percent_off": 10},
        {"code": "OK10", "name": "x", "kind": "percent"},
        {"code": "OK10", "name": "x", "kind": "fixed", "amount_off": "1000"},
        {"code": "OK10", "name": "x", "kind": "percent", "percent_off": 10, "value": 10},
        {"code": "OK10", "name": "", "kind": "percent", "percent_off": 10},
        {
            "code": "OK10",
            "name": "x",
            "kind": "percent",
            "percent_off": 10,
            "applies_to": "targets",
        },
        {
            "code": "OK10",
            "name": "x",
            "kind": "percent",
            "percent_off": 10,
            "applies_to": "targets",
            "targets": [{"variant_id": str(uuid.uuid4())}],
        },
    ],
)
def test_create_refuses_malformed_input(client, db, admin_auth, body):
    res = client.post(PROMOTIONS, json=body, headers=admin_auth["headers"])
    assert res.status_code == 422, res.text
    assert db.scalar(select(Discount.id)) is None


def test_create_refuses_unknown_targets(client, db, admin_auth):
    body = {
        "code": "TARGETED",
        "name": "x",
        "kind": "percent",
        "percent_off": 10,
        "applies_to": "targets",
        "targets": [{"brand_id": str(uuid.uuid4())}],
    }
    res = client.post(PROMOTIONS, json=body, headers=admin_auth["headers"])
    assert res.status_code == 422
    assert db.scalar(select(Discount.id)) is None


def test_list_get_and_status_filter(client, admin_auth):
    h = admin_auth["headers"]
    first = create_promotion(client, h, status="draft")
    second = create_promotion(client, h, status="active")
    page = client.get(PROMOTIONS, params={"size": 1}, headers=h).json()
    assert page["total"] == 2 and page["size"] == 1 and len(page["items"]) == 1
    drafts = client.get(PROMOTIONS, params={"status": "draft"}, headers=h).json()
    assert [p["id"] for p in drafts["items"]] == [first["id"]]
    assert client.get(f"{PROMOTIONS}/{second['id']}", headers=h).json()["code"] == second["code"]
    res = client.get(f"{PROMOTIONS}/{uuid.uuid4()}", headers=h)
    assert res.status_code == 404 and code(res) == "promotion_not_found"
    assert client.get(PROMOTIONS, params={"status": "expired"}, headers=h).status_code == 422


def test_update_status_kind_and_targets_with_audit(client, db, admin_auth):
    h = admin_auth["headers"]
    variant = sku(db)
    product_id, brand_id, _ = facts(db, variant)
    promo = create_promotion(client, h, status="draft")
    url = f"{PROMOTIONS}/{promo['id']}"
    assert client.patch(url, json={"status": "active"}, headers=h).json()["status"] == "active"
    assert client.patch(url, json={"status": "disabled"}, headers=h).json()["status"] == "disabled"
    res = client.patch(url, json={"status": "draft"}, headers=h)
    assert res.status_code == 409 and code(res) == "invalid_status_transition"
    assert client.patch(url, json={"kind": "fixed"}, headers=h).status_code == 422  # no amount
    changed = client.patch(
        url,
        json={
            "kind": "fixed",
            "amount_off": 700,
            "percent_off": None,
            "applies_to": "targets",
            "targets": [{"product_id": str(product_id)}, {"brand_id": str(brand_id)}],
        },
        headers=h,
    ).json()
    assert (changed["kind"], changed["amount_off"], changed["percent_off"]) == ("fixed", 700, None)
    assert len(changed["targets"]) == 2
    replaced = client.patch(
        url, json={"targets": [{"product_id": str(product_id)}]}, headers=h
    ).json()
    assert [t["product_id"] for t in replaced["targets"]] == [str(product_id)]
    before = len(audits(db, "promotion.update"))
    client.patch(url, json={"name": changed["name"]}, headers=h)  # nothing changes
    assert len(audits(db, "promotion.update")) == before
    db.expire_all()
    assert len(list(db.scalars(select(DiscountTarget)))) == 1


# ---- applying codes to a cart --------------------------------------------------------------
def test_adr_007_example_through_the_cart(client, db, admin_auth, customer_auth):
    create_promotion(client, admin_auth["headers"], code="TEN", percent_off=10)
    h = customer_auth["headers"]
    add(client, sku(db, price=1005), 1, h)
    body = apply(client, h, "ten").json()  # case-insensitive
    assert body["discount"]["applied"] is True and body["discount"]["code"] == "TEN"
    assert (body["merchandise_subtotal"], body["discount_total"]) == (1005, 101)
    assert body["subtotal_after_discount"] == 904
    assert body["lines"][0]["discount_amount"] == 101


def test_apply_replace_remove_and_repeat(client, db, admin_auth, customer_auth):
    a = create_promotion(client, admin_auth["headers"], code="FIVE", percent_off=5)
    create_promotion(client, admin_auth["headers"], code="FLAT", kind="fixed", amount_off=300)
    h = customer_auth["headers"]
    add(client, sku(db, price=10_000), 1, h)
    assert apply(client, h, "FIVE").json()["discount_total"] == 500
    again = apply(client, h, "FIVE").json()  # repeat: same result
    assert again["discount_total"] == 500 and again["discount"]["code"] == "FIVE"
    replaced = apply(client, h, "flat").json()  # one code per cart: replaces FIVE
    assert replaced["discount"]["code"] == "FLAT" and replaced["discount_total"] == 300
    removed = client.delete(REMOVE, headers=h).json()
    assert removed["discount"] is None and removed["discount_total"] == 0
    assert removed["subtotal_after_discount"] == 10_000
    assert client.delete(REMOVE, headers=h).status_code == 200  # idempotent
    assert client.get(CART, headers=h).json()["discount"] is None
    assert a["active_redemptions"] == 0  # applying a code reserves nothing
    assert db.scalar(select(DiscountRedemption.id)) is None


def test_codes_that_cannot_be_used_are_refused(client, db, admin_auth, customer_auth):
    h_admin = admin_auth["headers"]
    create_promotion(client, h_admin, code="DRAFTED", status="draft")
    create_promotion(client, h_admin, code="OFF", status="disabled")
    create_promotion(client, h_admin, code="LATER", starts_at=iso(now_utc() + timedelta(days=1)))
    create_promotion(
        client,
        h_admin,
        code="GONE",
        starts_at=iso(now_utc() - timedelta(days=2)),
        ends_at=iso(now_utc() - timedelta(days=1)),
    )
    create_promotion(client, h_admin, code="BIGSPEND", min_subtotal=50_000)
    h = customer_auth["headers"]
    add(client, sku(db, price=1000), 1, h)
    for value in ("NOSUCH", "DRAFTED", "OFF"):
        res = apply(client, h, value)
        assert res.status_code == 422 and code(res) == "promotion_unavailable", value
    for value, reason in (
        ("LATER", "not_started"),
        ("GONE", "expired"),
        ("BIGSPEND", "minimum_not_met"),
    ):
        res = apply(client, h, value)
        assert res.status_code == 422 and code(res) == "promotion_not_applicable", value
        assert res.json()["error"]["details"][0]["reason"] == reason
    assert client.get(CART, headers=h).json()["discount"] is None  # nothing was stored


def test_a_code_needs_a_cart(client, admin_auth, customer_auth):
    create_promotion(client, admin_auth["headers"], code="EARLY")
    res = apply(client, customer_auth["headers"], "EARLY")
    assert res.status_code == 404 and code(res) == "cart_not_found"
    assert apply(client, {}, "EARLY").status_code == 404  # a guest without a cart
    res = client.post(APPLY, json={"code": "EARLY", "amount": 1}, headers={})
    assert res.status_code == 422  # client amounts are refused


def test_staff_accounts_cannot_apply_codes(client, admin_auth):
    res = apply(client, admin_auth["headers"], "ANY")
    assert res.status_code == 403 and code(res) == "customer_only"


def test_targets_product_brand_and_category_with_subcategories(
    client, db, admin_auth, customer_auth
):
    h = customer_auth["headers"]
    in_child, other = sku(db, price=4000), sku(db, price=6000)
    _, _, child_category = facts(db, in_child)
    parent = Category(name="Parent", slug=f"parent-{uuid.uuid4().hex[:8]}")
    db.add(parent)
    db.flush()
    db.get(Category, child_category).parent_id = parent.id  # type: ignore[union-attr]
    db.commit()
    create_promotion(
        client,
        admin_auth["headers"],
        code="PARENT",
        percent_off=50,
        applies_to="targets",
        targets=[{"category_id": str(parent.id)}],
    )
    add(client, in_child, 1, h)
    add(client, other, 1, h)
    body = apply(client, h, "PARENT").json()
    shares = {line["variant_id"]: line["discount_amount"] for line in body["lines"]}
    assert shares == {in_child: 2000, other: 0}  # the subcategory's line only
    assert body["discount_total"] == 2000

    product_id, brand_id, _ = facts(db, other)
    create_promotion(
        client,
        admin_auth["headers"],
        code="BRAND",
        kind="fixed",
        amount_off=100,
        applies_to="targets",
        targets=[{"brand_id": str(brand_id)}],
    )
    shares = {
        line["variant_id"]: line["discount_amount"]
        for line in apply(client, h, "BRAND").json()["lines"]
    }
    assert shares == {in_child: 0, other: 100}
    create_promotion(
        client,
        admin_auth["headers"],
        code="PRODUCT",
        kind="fixed",
        amount_off=250,
        applies_to="targets",
        targets=[{"product_id": str(product_id)}],
    )
    assert apply(client, h, "PRODUCT").json()["discount_total"] == 250


def test_no_eligible_lines_is_refused(client, db, admin_auth, customer_auth):
    elsewhere = sku(db)
    product_id, _, _ = facts(db, elsewhere)
    create_promotion(
        client,
        admin_auth["headers"],
        code="ELSEWHERE",
        applies_to="targets",
        targets=[{"product_id": str(product_id)}],
    )
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    res = apply(client, h, "ELSEWHERE")
    assert res.status_code == 422 and res.json()["error"]["details"][0]["reason"] == (
        "no_eligible_items"
    )


def test_allocation_across_lines_sums_to_the_discount(client, db, admin_auth, customer_auth):
    create_promotion(client, admin_auth["headers"], code="SEVEN", percent_off=7)
    h = customer_auth["headers"]
    for price in (1001, 3003, 2002):
        add(client, sku(db, price=price), 1, h)
    body = apply(client, h, "SEVEN").json()
    shares = [line["discount_amount"] for line in body["lines"]]
    # payable = round_half_down(6006 x 0.93 = 5585.58) = 5586, discount 420
    assert body["discount_total"] == 420 and sum(shares) == 420
    assert shares == [70, 210, 140]  # proportional: 70.0, 210.0, 140.0 exactly


def test_max_discount_and_fixed_amount_never_make_a_total_negative(
    client, db, admin_auth, customer_auth
):
    create_promotion(client, admin_auth["headers"], code="CAPPED", percent_off=50, max_discount=999)
    create_promotion(client, admin_auth["headers"], code="HUGE", kind="fixed", amount_off=10**9)
    h = customer_auth["headers"]
    add(client, sku(db, price=5000), 1, h)
    assert apply(client, h, "CAPPED").json()["discount_total"] == 999
    body = apply(client, h, "HUGE").json()
    assert body["discount_total"] == 5000 and body["subtotal_after_discount"] == 0


def test_a_code_that_stops_applying_stays_but_discounts_nothing(
    client, db, admin_auth, customer_auth
):
    promo = create_promotion(client, admin_auth["headers"], code="SOON-OFF")
    h = customer_auth["headers"]
    add(client, sku(db, price=2000), 1, h)
    assert apply(client, h, "SOON-OFF").json()["discount_total"] == 200
    client.patch(
        f"{PROMOTIONS}/{promo['id']}", json={"status": "disabled"}, headers=admin_auth["headers"]
    )
    body = client.get(CART, headers=h).json()
    assert body["discount"]["applied"] is False and body["discount"]["reason"] == "not_active"
    assert body["discount_total"] == 0 and body["subtotal_after_discount"] == 2000
    assert body["lines"][0]["discount_amount"] == 0


def test_guest_carts_take_codes_and_merge_carries_them(client, db, admin_auth, customer_auth):
    create_promotion(client, admin_auth["headers"], code="GUEST5", kind="fixed", amount_off=50)
    created = add(client, sku(db, price=1000), 1)
    token = created.json()["cart_token"]
    assert apply(client, guest(token), "guest5").json()["discount_total"] == 50
    merged = client.post(
        f"{CART}/merge", headers={**customer_auth["headers"], "X-Cart-Token": token}
    ).json()
    assert merged["cart"]["discount"]["code"] == "GUEST5"
    assert merged["cart"]["discount_total"] == 50


# ---- delivery (module 12) ------------------------------------------------------------------
def test_delivery_is_never_discounted_and_uses_the_discounted_threshold_basis(
    client, db, admin_auth, customer_auth
):
    create_zone(client, admin_auth["headers"], "Gasabo", 2000)
    set_threshold(client, admin_auth["headers"], 200_000)
    create_promotion(client, admin_auth["headers"], code="KGL1000", kind="fixed", amount_off=1000)
    h = customer_auth["headers"]
    add(client, sku(db, price=200_500), 1, h)
    before = client.get(CART, params={"zone": "gasabo"}, headers=h).json()
    assert before["delivery"]["delivery_fee"] == 0  # 200 500 >= threshold
    apply(client, h, "KGL1000")
    after = client.get(CART, params={"zone": "gasabo"}, headers=h).json()
    assert after["subtotal_after_discount"] == 199_500
    assert after["delivery"]["delivery_fee"] == 2000  # below the threshold after discount
    assert after["delivery"]["free_delivery"] is False
    assert after["grand_total"] == 199_500 + 2000  # the fee itself is not discounted


# ---- usage limits --------------------------------------------------------------------------
def test_the_total_limit_counts_active_redemptions_only(client, db, admin_auth, customer_auth):
    promo = create_promotion(client, admin_auth["headers"], code="ONCE", usage_limit_total=1)
    discount_id = uuid.UUID(promo["id"])
    order_id = placed_order(db)
    redeem(
        db,
        discount_id=discount_id,
        order_id=order_id,
        user_id=None,
        customer_phone="0788 111 999",
        amount=100,
    )
    db.commit()
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    res = apply(client, h, "ONCE")
    assert res.json()["error"]["details"][0]["reason"] == "usage_limit_reached"
    release_for_order(db, order_id, reason="cancelled")
    db.commit()
    assert apply(client, h, "ONCE").status_code == 200  # a released use no longer counts
    assert (
        client.get(f"{PROMOTIONS}/{promo['id']}", headers=admin_auth["headers"]).json()[
            "active_redemptions"
        ]
        == 0
    )


def test_the_per_customer_limit_counts_by_account_or_phone(client, db, admin_auth, customer_auth):
    promo = create_promotion(client, admin_auth["headers"], code="MINE", usage_limit_per_customer=1)
    discount_id = uuid.UUID(promo["id"])
    customer_id = uuid.UUID(customer_auth["user"]["id"])
    # A guest order with the customer's phone, in another accepted format (Q26).
    redeem(
        db,
        discount_id=discount_id,
        order_id=placed_order(db),
        user_id=None,
        customer_phone="0788111222",  # = +250788111222, customer A's phone
        amount=100,
    )
    db.commit()
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    res = apply(client, h, "MINE")
    assert res.json()["error"]["details"][0]["reason"] == "customer_limit_reached"
    with pytest.raises(PromotionNotApplicable, match="customer_limit_reached"):
        redeem(  # the same account with another phone is still the same customer
            db,
            discount_id=discount_id,
            order_id=placed_order(db, user_id=customer_id),
            user_id=customer_id,
            customer_phone="+250788999000",
            amount=100,
        )
    db.rollback()
    stored = db.scalar(select(DiscountRedemption.customer_phone))
    assert stored == "+250788111222"  # stored canonical


def test_guest_limits_count_by_canonical_phone(db, client, admin_auth):
    promo = create_promotion(
        client, admin_auth["headers"], code="GPHONE", usage_limit_per_customer=1
    )
    discount_id = uuid.UUID(promo["id"])
    redeem(
        db,
        discount_id=discount_id,
        order_id=placed_order(db),
        user_id=None,
        customer_phone="+250 788 555 444",
        amount=10,
    )
    db.commit()
    with pytest.raises(PromotionNotApplicable, match="customer_limit_reached"):
        redeem(
            db,
            discount_id=discount_id,
            order_id=placed_order(db),
            user_id=None,
            customer_phone="0788-555-444",
            amount=10,
        )
    db.rollback()
    assert (
        redeem(
            db,
            discount_id=discount_id,
            order_id=placed_order(db),
            user_id=None,
            customer_phone="0788555445",
            amount=10,
        ).customer_phone
        == "+250788555445"
    )
    with pytest.raises(ValueError):
        redeem(
            db,
            discount_id=discount_id,
            order_id=placed_order(db),
            user_id=None,
            customer_phone="12345",
            amount=10,
        )


def test_redeem_refuses_codes_outside_their_window_or_status(db, client, admin_auth):
    h = admin_auth["headers"]
    later = create_promotion(client, h, starts_at=iso(now_utc() + timedelta(hours=1)))
    off = create_promotion(client, h, status="disabled")
    for promo, reason in ((later, "not_started"), (off, "not_active")):
        with pytest.raises(PromotionNotApplicable, match=reason):
            redeem(
                db,
                discount_id=uuid.UUID(promo["id"]),
                order_id=placed_order(db),
                user_id=None,
                customer_phone="0788000111",
                amount=1,
            )
        db.rollback()


def test_the_window_boundary_uses_database_time(db, client, admin_auth):
    """starts_at inclusive, ends_at exclusive, compared with the database clock."""
    promo = create_promotion(client, admin_auth["headers"])
    discount = db.get(Discount, uuid.UUID(promo["id"]))
    assert discount is not None
    at = promotion_service.database_now(db)
    discount.starts_at, discount.ends_at = at, at + timedelta(seconds=1)
    db.commit()
    lines = [(uuid.uuid4(), 1000)]
    variant = uuid.UUID(sku(db, price=1000))
    lines = [(variant, 1000)]
    assert promotion_service.quote(db, discount, lines, at=at).applied is True
    assert promotion_service.quote(
        db, discount, lines, at=at - timedelta(microseconds=1)
    ).reason == ("not_started")
    assert promotion_service.quote(db, discount, lines, at=at + timedelta(seconds=1)).reason == (
        "expired"
    )


# ---- redemption release lifecycle ----------------------------------------------------------
def test_cancellation_before_dispatch_releases_the_redemption_once(
    client, db, admin_auth, operations_auth
):
    promo = create_promotion(client, admin_auth["headers"], usage_limit_total=1)
    order_id = placed_order(db)
    redeem(
        db,
        discount_id=uuid.UUID(promo["id"]),
        order_id=order_id,
        user_id=None,
        customer_phone="0788123123",
        amount=500,
    )
    db.commit()
    res = client.patch(
        f"{ORDERS}/{order_id}/status",
        json={"status": "cancelled"},
        headers=operations_auth["headers"],
    )
    assert res.status_code == 200, res.text
    db.expire_all()
    redemption = db.scalar(select(DiscountRedemption))
    assert redemption is not None
    assert (redemption.status, redemption.release_reason) == ("released", "cancelled")
    assert redemption.released_at is not None
    assert release_for_order(db, order_id, reason="cancelled") == 0  # idempotent
    assert len(audits(db, "promotion.redemption_release")) == 1


def test_a_failed_cancellation_keeps_the_redemption(client, db, admin_auth, operations_auth):
    promo = create_promotion(client, admin_auth["headers"])
    order_id = placed_order(db)
    redeem(
        db,
        discount_id=uuid.UUID(promo["id"]),
        order_id=order_id,
        user_id=None,
        customer_phone="0788123124",
        amount=5,
    )
    db.commit()
    db.execute(text("UPDATE orders SET status = 'delivered' WHERE id = :id"), {"id": order_id})
    db.commit()
    db.expire_all()  # the request shares this session in tests
    res = client.patch(
        f"{ORDERS}/{order_id}/status",
        json={"status": "cancelled"},
        headers=operations_auth["headers"],
    )
    assert res.status_code == 409  # not before dispatch: nothing is released
    db.expire_all()
    assert db.scalar(select(DiscountRedemption.status)) == "active"


def test_reservation_expiry_releases_the_redemption(db, client, admin_auth):
    promo = create_promotion(client, admin_auth["headers"])
    order_id = placed_order(db, expires_at=soon(1))
    redeem(
        db,
        discount_id=uuid.UUID(promo["id"]),
        order_id=order_id,
        user_id=None,
        customer_phone="0788123125",
        amount=5,
    )
    db.commit()
    wait_until_due()
    assert expire_due_reservations(db).orders == 1
    db.expire_all()
    redemption = db.scalar(select(DiscountRedemption))
    assert redemption is not None
    assert (redemption.status, redemption.release_reason) == ("released", "expired")
    assert expire_due_reservations(db).orders == 0  # nothing expires twice
    assert release_for_order(db, order_id, reason="expired") == 0


def test_release_reason_and_amount_are_validated(db):
    with pytest.raises(ValueError):
        release_for_order(db, uuid.uuid4(), reason="payment_failed")


# ---- concurrency: the last use, with real PostgreSQL row locks -----------------------------
def test_two_checkouts_cannot_take_the_same_last_use(pg_engine: Engine, db, client, admin_auth):
    """Deterministic: A takes the code's row lock and records the last use without committing;
    B's redeem must wait on the lock, then see A's use and be refused."""
    assert pg_engine.url.database == "rwanda_ecommerce_test"
    promo = create_promotion(client, admin_auth["headers"], usage_limit_total=1)
    discount_id = uuid.UUID(promo["id"])
    orders = [placed_order(db), placed_order(db)]
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    a, b = make(), make()
    outcome: dict[str, object] = {}

    def checkout_b():
        try:
            redeem(
                b,
                discount_id=discount_id,
                order_id=orders[1],
                user_id=None,
                customer_phone="0788200002",
                amount=10,
            )
            b.commit()
            outcome["b"] = "redeemed"
        except PromotionNotApplicable as exc:
            b.rollback()
            outcome["b"] = exc.reason

    try:
        redeem(
            a,
            discount_id=discount_id,
            order_id=orders[0],
            user_id=None,
            customer_phone="0788200001",
            amount=10,
        )
        worker = threading.Thread(target=checkout_b)
        worker.start()
        time.sleep(0.5)
        assert worker.is_alive()  # B is waiting on A's row lock
        a.commit()
        worker.join(timeout=10)
        assert not worker.is_alive()
    finally:
        a.close()
        b.close()
    assert outcome["b"] == "usage_limit_reached"
    db.expire_all()
    assert len(list(db.scalars(select(DiscountRedemption)))) == 1


def test_many_concurrent_checkouts_take_each_use_once(pg_engine: Engine, db, client, admin_auth):
    promo = create_promotion(client, admin_auth["headers"], usage_limit_total=2)
    discount_id = uuid.UUID(promo["id"])
    orders = [placed_order(db) for _ in range(6)]
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    barrier = threading.Barrier(6)
    results: list[str] = []
    lock = threading.Lock()

    def checkout(i: int):
        session = make()
        try:
            barrier.wait(timeout=10)
            redeem(
                session,
                discount_id=discount_id,
                order_id=orders[i],
                user_id=None,
                customer_phone=f"07883000{i:02d}",
                amount=1,
            )
            session.commit()
            result = "redeemed"
        except PromotionNotApplicable as exc:
            session.rollback()
            result = exc.reason
        finally:
            session.close()
        with lock:
            results.append(result)

    threads = [threading.Thread(target=checkout, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(results) == ["redeemed"] * 2 + ["usage_limit_reached"] * 4
    db.expire_all()
    assert len(list(db.scalars(select(DiscountRedemption)))) == 2


def test_openapi_documents_the_promotion_routes():
    app.openapi_schema = None
    paths = app.openapi()["paths"]
    assert set(paths[PROMOTIONS]) == {"get", "post"}
    assert set(paths[f"{PROMOTIONS}/{{promotion_id}}"]) == {"get", "patch"}
    assert set(paths[APPLY]) == {"post"} and set(paths[REMOVE]) == {"delete"}
    for path, method in ((PROMOTIONS, "post"), (f"{PROMOTIONS}/{{promotion_id}}", "patch")):
        assert {"401", "403", "422"} <= set(paths[path][method]["responses"])


# ---- D-P2: the minimum is the whole merchandise subtotal before discount ----------------------
def test_the_minimum_compares_the_whole_merchandise_subtotal_for_all_codes(
    client, db, admin_auth, customer_auth
):
    create_promotion(client, admin_auth["headers"], code="MIN10K", min_subtotal=10_000)
    h = customer_auth["headers"]
    add(client, sku(db, price=9_999), 1, h)
    res = apply(client, h, "MIN10K")
    assert res.json()["error"]["details"][0]["reason"] == "minimum_not_met"
    add(client, sku(db, price=1), 1, h)  # 10 000 exactly: the minimum is inclusive
    assert apply(client, h, "MIN10K").json()["discount"]["applied"] is True


def test_a_targeted_code_meets_its_minimum_on_the_whole_cart(client, db, admin_auth, customer_auth):
    """Eligible lines total 1 000, below the 10 000 minimum; the whole cart totals 10 000."""
    eligible, other = sku(db, price=1_000), sku(db, price=9_000)
    product_id, _, _ = facts(db, eligible)
    create_promotion(
        client,
        admin_auth["headers"],
        code="TGT10K",
        kind="fixed",
        amount_off=100,
        min_subtotal=10_000,
        applies_to="targets",
        targets=[{"product_id": str(product_id)}],
    )
    h = customer_auth["headers"]
    add(client, eligible, 1, h)
    res = apply(client, h, "TGT10K")  # whole cart 1 000: below the minimum
    assert res.json()["error"]["details"][0]["reason"] == "minimum_not_met"
    add(client, other, 1, h)
    body = apply(client, h, "TGT10K").json()
    assert body["discount"]["applied"] is True and body["discount_total"] == 100
    shares = {line["variant_id"]: line["discount_amount"] for line in body["lines"]}
    assert shares == {eligible: 100, other: 0}  # the discount still goes to eligible lines only


def test_the_minimum_ignores_delivery_and_unpriced_lines(client, db, admin_auth, customer_auth):
    create_zone(client, admin_auth["headers"], "Kicukiro", 2000)
    set_threshold(client, admin_auth["headers"], 10**9)
    create_promotion(client, admin_auth["headers"], code="NODELIV", min_subtotal=5_000)
    h = customer_auth["headers"]
    add(client, sku(db, price=4_000), 1, h)
    gone = sku(db, price=5_000, on_hand=1)
    add(client, gone, 1, h)
    db.execute(  # the second line becomes unavailable and leaves the subtotal
        text("UPDATE inventory_balances SET on_hand = 0 WHERE variant_id = :v"), {"v": gone}
    )
    db.commit()
    res = apply(client, h, "NODELIV")  # 4 000 of priced merchandise; delivery never counts
    assert res.json()["error"]["details"][0]["reason"] == "minimum_not_met"


# ---- S5: refused promotion codes are limited (ADR-008, approved 2026-10-25) -----------------
CODE_REFUSALS = 20  # cart_code_refusals_per_window
CODE_WINDOW = 900  # cart_code_refusal_window_seconds


def test_refused_codes_are_limited_with_retry_after_and_the_window_expires(
    client, db, admin_auth, customer_auth, clock
):
    create_promotion(client, admin_auth["headers"], code="REAL10")
    h = customer_auth["headers"]
    add(client, sku(db, price=1000), 1, h)
    for i in range(CODE_REFUSALS):
        res = apply(client, h, f"GUESS{i:03d}")
        assert res.status_code == 422 and code(res) == "promotion_unavailable"
    blocked = apply(client, h, "REAL10")  # even a valid code, once the limit is reached
    assert blocked.status_code == 429 and code(blocked) == "rate_limited"
    assert 0 < int(blocked.headers["Retry-After"]) <= CODE_WINDOW
    assert client.get(CART, headers=h).json()["discount"] is None  # nothing was applied
    clock.advance(CODE_WINDOW + 1)
    assert apply(client, h, "REAL10").status_code == 200


def test_not_applicable_codes_count_too(client, db, admin_auth, customer_auth):
    create_promotion(client, admin_auth["headers"], code="BIGMIN", min_subtotal=10**9)
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    for _ in range(CODE_REFUSALS):
        assert code(apply(client, h, "BIGMIN")) == "promotion_not_applicable"
    assert apply(client, h, "BIGMIN").status_code == 429


def test_successful_applies_and_removal_never_use_the_budget(client, db, admin_auth, customer_auth):
    create_promotion(client, admin_auth["headers"], code="OKAY10")
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    for _ in range(CODE_REFUSALS + 5):
        assert apply(client, h, "OKAY10").status_code == 200
        assert client.delete(REMOVE, headers=h).status_code == 200
    for i in range(CODE_REFUSALS - 1):
        assert apply(client, h, f"MISS{i:03d}").status_code == 422
    assert apply(client, h, "OKAY10").status_code == 200  # 19 refusals: still allowed
    assert apply(client, h, "MISS999").status_code == 422  # the 20th refusal
    assert apply(client, h, "OKAY10").status_code == 429
    for _ in range(3):  # removing a code is never limited
        assert client.delete(REMOVE, headers=h).status_code == 200


def test_the_limit_follows_the_cart_owner_across_networks(client, db, customer_auth):
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    for i in range(CODE_REFUSALS):
        assert apply(peer(f"198.51.100.{i + 1}"), h, f"NET{i:03d}").status_code == 422
    assert apply(peer("198.51.100.250"), h, "ANYCODE").status_code == 429


def test_the_network_limit_covers_guests_and_customers_alike(client, db, customer_auth):
    """Switching from a guest cart to a customer session (or to new guest carts) on the same
    network does not reset the count: the network key is shared by every identity on it."""
    attacker = peer("203.0.113.7")
    guest_token = add(attacker, sku(db)).json()["cart_token"]
    for i in range(CODE_REFUSALS):
        assert apply(attacker, guest(guest_token), f"G{i:03d}X").status_code == 422
    add(attacker, sku(db), 1, customer_auth["headers"])
    assert apply(attacker, customer_auth["headers"], "AFTER1").status_code == 429
    other_network = peer("203.0.114.7")
    assert apply(other_network, customer_auth["headers"], "AFTER1").status_code == 422


def test_the_code_limit_is_skipped_with_a_warning_when_redis_is_down(
    client, db, admin_auth, customer_auth, caplog
):
    create_promotion(client, admin_auth["headers"], code="UPTIME")
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)  # created with the working limiter
    app.dependency_overrides[get_cart_rate_limiter] = lambda: CartRateLimiter(
        DownStore(), _settings()
    )
    with caplog.at_level(logging.WARNING):
        for i in range(CODE_REFUSALS + 3):
            assert apply(client, h, f"DOWN{i:03d}").status_code == 422  # fail open
        assert apply(client, h, "UPTIME").status_code == 200
    assert "Promotion-code limit skipped" in caplog.text
    assert "Promotion-code refusal not counted" in caplog.text
