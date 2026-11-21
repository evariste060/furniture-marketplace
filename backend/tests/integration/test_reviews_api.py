"""Reviews part 2 (module 20, scope change SC-01 approved 2026-10-27): review links for verified
buyers, submission, moderation with rating totals, the public list and the limits."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import LoginRateLimiter, get_review_submit_rate_limiter
from app.main import app
from app.models import (
    Order,
    OrderItem,
    OrderStatusHistory,
    ProductReview,
    ProductVariant,
    ReviewToken,
)
from app.services.review_service import hash_review_token
from tests.integration.test_cart_api import code
from tests.integration.test_cart_security import DownStore, peer
from tests.support.commerce import audit_count, new_order, seed_sku

API = "/api/v1"
STAFF = f"{API}/staff/reviews"
PHONE = "+250788123456"


# ---- helpers ---------------------------------------------------------------------------------


@dataclass
class Bought:
    item: OrderItem
    variant: ProductVariant
    slug: str

    @property
    def order(self) -> Order:
        return self.item.order


def delivered_item(
    db: Session,
    variant=None,
    *,
    user_id=None,
    status: str = "delivered",
    delivered_days_ago: float = 1,
    name: str = "Aline Uwase",
) -> Bought:
    """One order with one item of `variant` (a new public product if None), delivered
    `delivered_days_ago` days ago unless `status` says otherwise."""
    variant = variant or seed_sku(db, on_hand=5)
    order = new_order({variant.id: 1}, user_id=user_id)
    order.order_number = order.order_number.upper()  # as checkout writes them
    order.status = status
    order.recipient_name = name
    order.recipient_phone = PHONE
    order.items[0].product_id = variant.product_id
    order.items[0].product_name_snapshot = variant.product.name
    db.add(order)
    db.flush()
    if status == "delivered":
        db.add(
            OrderStatusHistory(
                order_id=order.id,
                status="delivered",
                created_at=datetime.now(UTC) - timedelta(days=delivered_days_ago),
            )
        )
    db.commit()
    return Bought(order.items[0], variant, variant.product.slug)


def customer_link(client: TestClient, auth: dict, bought: Bought):
    return client.post(
        f"{API}/customers/me/orders/{bought.item.order_id}/items/{bought.item.id}/review-link",
        headers=auth["headers"],
    )


def guest_link(client: TestClient, order: Order, item_id, phone: str = PHONE):
    return client.post(
        f"{API}/orders/review-link",
        json={"order_number": order.order_number, "phone": phone, "order_item_id": str(item_id)},
    )


def admin_link(db: Session, bought: Bought) -> str:
    """A link token for a delivered item, issued as the service would (no customer needed)."""
    token = uuid.uuid4().hex + uuid.uuid4().hex
    db.add(
        ReviewToken(
            order_item_id=bought.item.id,
            token_hash=hash_review_token(token),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
    )
    db.commit()
    return token


def submit(client: TestClient, token: str, **body):
    return client.post(f"{API}/reviews/{token}", json={"rating": 5, **body})


def review_for(db: Session, client: TestClient, bought: Bought, rating: int) -> str:
    res = submit(client, admin_link(db, bought), rating=rating)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def moderate(client: TestClient, auth: dict, review_id: str, action: str, **body):
    return client.post(f"{STAFF}/{review_id}/{action}", json=body or None, headers=auth["headers"])


def rating(client: TestClient, slug: str) -> dict:
    res = client.get(f"{API}/catalog/products/{slug}")
    assert res.status_code == 200, res.text
    return res.json()["rating"]


def public(client: TestClient, slug: str, **params) -> dict:
    res = client.get(f"{API}/catalog/products/{slug}/reviews", params=params)
    assert res.status_code == 200, res.text
    return res.json()


# ---- links -----------------------------------------------------------------------------------


def test_a_customer_reviews_a_delivered_item_once(client, db, customer_auth):
    item = delivered_item(db, user_id=uuid.UUID(customer_auth["user"]["id"]))
    res = customer_link(client, customer_auth, item)
    assert res.status_code == 201, res.text
    token = res.json()["token"]
    assert len(token) >= 43
    stored = db.scalar(select(ReviewToken).where(ReviewToken.order_item_id == item.item.id))
    assert stored is not None and stored.token_hash == hash_review_token(token)
    assert token not in stored.token_hash  # only the hash is kept

    info = client.get(f"{API}/reviews/{token}").json()
    assert info["status"] == "open"
    assert info["product"]["name"] == item.item.product_name_snapshot
    assert info["product"]["slug"] is not None

    sent = submit(client, token, rating=4, title="Good", body="Battery lasts.")
    assert sent.status_code == 201, sent.text
    assert sent.json()["status"] == "pending"
    review = db.get(ProductReview, uuid.UUID(sent.json()["id"]))
    assert review is not None
    assert review.author_name == "Aline U." and review.user_id == item.order.user_id

    assert client.get(f"{API}/reviews/{token}").json()["status"] == "used"
    again = submit(client, token)
    assert again.status_code == 409 and code(again) == "already_reviewed"
    reissue = customer_link(client, customer_auth, item)
    assert reissue.status_code == 409 and code(reissue) == "already_reviewed"


def test_asking_again_replaces_an_unused_link(client, db, customer_auth):
    item = delivered_item(db, user_id=uuid.UUID(customer_auth["user"]["id"]))
    first = customer_link(client, customer_auth, item).json()["token"]
    second = customer_link(client, customer_auth, item).json()["token"]
    assert first != second
    assert client.get(f"{API}/reviews/{first}").status_code == 404
    assert submit(client, first).status_code == 404
    assert submit(client, second).status_code == 201


def test_links_are_only_for_own_delivered_items(client, db, customer_auth, second_customer_auth):
    owner = uuid.UUID(customer_auth["user"]["id"])
    item = delivered_item(db, user_id=owner)
    other = customer_link(client, second_customer_auth, item)
    assert other.status_code == 404 and code(other) == "order_not_found"

    wrong_item = client.post(
        f"{API}/customers/me/orders/{item.item.order_id}/items/{uuid.uuid4()}/review-link",
        headers=customer_auth["headers"],
    )
    assert wrong_item.status_code == 404 and code(wrong_item) == "order_item_not_found"

    for status in ("received", "dispatched", "cancelled"):
        undelivered = delivered_item(db, user_id=owner, status=status)
        res = customer_link(client, customer_auth, undelivered)
        assert res.status_code == 409 and code(res) == "not_delivered", status

    assert (
        client.post(
            f"{API}/customers/me/orders/{item.item.order_id}/items/{item.item.id}/review-link"
        ).status_code
        == 401
    )


def test_links_expire_90_days_after_delivery(client, db, customer_auth):
    owner = uuid.UUID(customer_auth["user"]["id"])
    late = delivered_item(db, user_id=owner, delivered_days_ago=91)
    res = customer_link(client, customer_auth, late)
    assert res.status_code == 409 and code(res) == "review_link_expired"

    item = delivered_item(db, user_id=owner, delivered_days_ago=10)
    issued = customer_link(client, customer_auth, item).json()
    expires = datetime.fromisoformat(issued["expires_at"])
    assert timedelta(days=79) < expires - datetime.now(UTC) < timedelta(days=81)

    db.execute(
        update(ReviewToken)
        .where(ReviewToken.order_item_id == item.item.id)
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    db.commit()
    assert client.get(f"{API}/reviews/{issued['token']}").json()["status"] == "expired"
    sent = submit(client, issued["token"])
    assert sent.status_code == 409 and code(sent) == "review_link_expired"


def test_a_guest_gets_a_link_with_the_order_lookup(client, db):
    item = delivered_item(db)
    order = item.order
    wrong = guest_link(client, order, item.item.id, phone="+250788999999")
    assert wrong.status_code == 404 and code(wrong) == "order_not_found"
    missing = guest_link(client, order, uuid.uuid4())
    assert missing.status_code == 404 and code(missing) == "order_item_not_found"

    res = guest_link(client, order, item.item.id, phone="0788123456")  # any accepted format
    assert res.status_code == 201, res.text
    sent = submit(client, res.json()["token"], rating=3)
    assert sent.status_code == 201
    review = db.get(ProductReview, uuid.UUID(sent.json()["id"]))
    assert review is not None and review.user_id is None


def test_guest_link_failures_count_towards_the_lookup_limit(client, db):
    item = delivered_item(db)
    for _ in range(get_settings().order_lookup_max_failures_per_order):
        assert (
            guest_link(client, item.order, item.item.id, phone="+250788999999").status_code == 404
        )
    blocked = guest_link(client, item.order, item.item.id)
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers


def test_unknown_and_malformed_links(client):
    assert client.get(f"{API}/reviews/{'a' * 43}").status_code == 404
    assert code(client.get(f"{API}/reviews/{'a' * 43}")) == "review_link_not_found"
    for bad in ("short", "a" * 101, "a" * 30 + "%3Cx%3E"):
        assert client.get(f"{API}/reviews/{bad}").status_code == 422, bad


def test_a_product_no_longer_sold_cannot_be_reviewed(client, db, customer_auth):
    item = delivered_item(db, user_id=uuid.UUID(customer_auth["user"]["id"]))
    token = customer_link(client, customer_auth, item).json()["token"]
    db.execute(update(OrderItem).where(OrderItem.id == item.item.id).values(product_id=None))
    db.commit()
    info = client.get(f"{API}/reviews/{token}").json()
    assert info["product"]["slug"] is None and info["status"] == "open"
    res = submit(client, token)
    assert res.status_code == 409 and code(res) == "product_unavailable"


# ---- review text -----------------------------------------------------------------------------


def test_review_text_is_plain_text_and_validated(client, db, admin_auth):
    item = delivered_item(db)
    token = admin_link(db, item)
    for bad in (
        {"rating": 0},
        {"rating": 6},
        {"rating": "five"},
        {"title": "x" * 81},
        {"body": "x" * 2001},
        {"photo": "x"},
    ):
        assert submit(client, token, **bad).status_code == 422, bad

    script = '<script>alert("x")</script> <b>bold</b>'
    sent = submit(
        client, token, title=f"  {script}\x07 ", body="First line\r\n\r\n\r\n\r\nSecond <img src=x>"
    )
    assert sent.status_code == 201, sent.text
    approved = moderate(client, admin_auth, sent.json()["id"], "approve")
    assert approved.status_code == 200
    (review,) = public(client, item.slug)["items"]
    assert review["title"] == script  # stored and returned as text, never as markup
    assert review["body"] == "First line\n\nSecond <img src=x>"

    blank_item = delivered_item(db, item.variant)
    blank = submit(client, admin_link(db, blank_item), title="   ", body="\n \n")
    assert blank.status_code == 201
    stored = db.get(ProductReview, uuid.UUID(blank.json()["id"]))
    assert stored is not None and stored.title is None and stored.body is None


# ---- moderation and totals -------------------------------------------------------------------


def test_moderation_recalculates_the_totals_and_is_audited(client, db, admin_auth):
    first = delivered_item(db)
    variant = first.variant
    slug = first.slug
    ids = [review_for(db, client, first, 5)]
    ids += [review_for(db, client, delivered_item(db, variant), r) for r in (4, 2)]
    assert rating(client, slug)["count"] == 0  # pending reviews do not count
    assert public(client, slug)["total"] == 0

    for review_id in ids:
        res = moderate(client, admin_auth, review_id, "approve")
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "approved" and res.json()["moderated_at"]
    totals = rating(client, slug)
    assert totals["average"] == 3.7 and totals["count"] == 3  # 11 / 3
    assert totals["distribution"] == [
        {"stars": 5, "count": 1},
        {"stars": 4, "count": 1},
        {"stars": 3, "count": 0},
        {"stars": 2, "count": 1},
        {"stars": 1, "count": 0},
    ]
    listing = client.get(f"{API}/catalog/products").json()["items"]
    assert next(p for p in listing if p["slug"] == slug)["rating"] == {"average": 3.7, "count": 3}

    again = moderate(client, admin_auth, ids[0], "approve")
    assert again.status_code == 409 and code(again) == "review_already_approved"

    rejected = moderate(client, admin_auth, ids[2], "reject", reason="Off topic")
    assert rejected.status_code == 200
    assert rejected.json()["moderation_reason"] == "Off topic"
    assert rating(client, slug)["average"] == 4.5 and rating(client, slug)["count"] == 2
    assert moderate(client, admin_auth, ids[2], "reject").status_code == 409

    for review_id in ids[:2]:
        assert moderate(client, admin_auth, review_id, "reject").status_code == 200
    assert rating(client, slug) == {
        "average": None,
        "count": 0,
        "distribution": [{"stars": s, "count": 0} for s in (5, 4, 3, 2, 1)],
    }

    assert audit_count(db, "catalog.review_approve") == 3
    assert audit_count(db, "catalog.review_reject", uuid.UUID(ids[2])) == 1
    assert audit_count(db, "catalog.review_reject") == 3
    missing = moderate(client, admin_auth, str(uuid.uuid4()), "approve")
    assert missing.status_code == 404 and code(missing) == "review_not_found"


def test_the_public_list_shows_approved_reviews_newest_first(client, db, admin_auth):
    first = delivered_item(db, name="Jean Bosco Habimana")
    variant = first.variant
    slug = first.slug
    old = review_for(db, client, first, 5)
    new = review_for(db, client, delivered_item(db, variant, name="Grace"), 4)
    pending_item = delivered_item(db, variant)
    pending = review_for(db, client, pending_item, 1)
    rejected = review_for(db, client, delivered_item(db, variant), 1)
    for review_id in (old, new):
        moderate(client, admin_auth, review_id, "approve")
    moderate(client, admin_auth, rejected, "reject")

    page = public(client, slug)
    assert page["total"] == 2
    assert [r["id"] for r in page["items"]] == [new, old]
    assert [r["author_name"] for r in page["items"]] == ["Grace", "Jean H."]
    assert all(r["verified_purchase"] for r in page["items"])
    assert set(page["items"][0]) == {
        "id",
        "rating",
        "title",
        "body",
        "author_name",
        "verified_purchase",
        "created_at",
    }
    assert pending not in {r["id"] for r in page["items"]}
    assert [r["id"] for r in public(client, slug, size=1, page=2)["items"]] == [old]
    missing = client.get(f"{API}/catalog/products/no-such-product/reviews")
    assert missing.status_code == 404

    queue = client.get(STAFF, params={"status": "pending"}, headers=admin_auth["headers"]).json()
    assert [r["id"] for r in queue["items"]] == [pending]
    assert queue["items"][0]["order_number"] == pending_item.order.order_number
    assert queue["items"][0]["product_slug"] == slug
    everything = client.get(STAFF, headers=admin_auth["headers"]).json()
    assert everything["total"] == 4
    assert [r["id"] for r in everything["items"]][0] == rejected  # newest first
    assert (
        client.get(STAFF, params={"status": "x"}, headers=admin_auth["headers"]).status_code == 422
    )


def test_only_moderators_see_and_decide_reviews(client, db, customer_auth):
    item = delivered_item(db)
    review_id = review_for(db, client, item, 5)
    for auth in (customer_auth,):
        assert client.get(STAFF, headers=auth["headers"]).status_code == 403
        assert moderate(client, auth, review_id, "approve").status_code == 403
        assert moderate(client, auth, review_id, "reject").status_code == 403
    assert client.get(STAFF).status_code == 401
    assert client.post(f"{STAFF}/{review_id}/approve").status_code == 401
    review = db.get(ProductReview, uuid.UUID(review_id))
    db.refresh(review)
    assert review is not None and review.status == "pending"


# ---- limits ----------------------------------------------------------------------------------


def test_every_submission_counts_towards_the_limits(client, db):
    item = delivered_item(db)
    token = admin_link(db, item)
    db.execute(
        update(ReviewToken)
        .where(ReviewToken.order_item_id == item.item.id)
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    db.commit()
    for _ in range(get_settings().review_submit_max_per_token):
        assert submit(client, token).status_code == 409  # expired, but counted
    blocked = submit(client, token)
    assert blocked.status_code == 429 and code(blocked) == "rate_limited"
    assert int(blocked.headers["Retry-After"]) > 0
    assert submit(client, token, rating=9).status_code == 422  # never reaches the service


def test_the_network_limit_spans_links(client, db):
    attacker = peer("198.51.100.90")
    for n in range(get_settings().review_submit_max_per_ip):
        assert submit(attacker, f"{n:02d}" + "b" * 41).status_code == 404
    assert submit(attacker, admin_link(db, delivered_item(db))).status_code == 429
    assert submit(peer("198.51.100.91"), admin_link(db, delivered_item(db))).status_code == 201


def test_an_unreachable_limit_store_refuses_submissions(client, db):
    item = delivered_item(db)
    token = admin_link(db, item)
    app.dependency_overrides[get_review_submit_rate_limiter] = lambda: LoginRateLimiter(
        DownStore(), get_settings(), prefix="review_submit"
    )
    res = submit(client, token)
    assert res.status_code == 503 and code(res) == "review_unavailable"
    assert (
        db.scalar(select(ProductReview).where(ProductReview.order_item_id == item.item.id)) is None
    )


def test_order_lines_say_which_items_are_reviewed(client, db, customer_auth, second_customer_auth):
    """Frontend phase 5: the account's order page opens an order by its number and offers
    "Write a review" per line until the item is reviewed."""
    item = delivered_item(db, user_id=uuid.UUID(customer_auth["user"]["id"]))
    url = f"{API}/customers/me/orders/number/{item.order.order_number}"
    res = client.get(url, headers=customer_auth["headers"])
    assert res.status_code == 200, res.text
    [line] = res.json()["lines"]
    assert line["id"] == str(item.item.id)
    assert line["product_slug"] == item.slug and line["reviewed"] is False

    token = customer_link(client, customer_auth, item).json()["token"]
    assert submit(client, token).status_code == 201
    [line] = client.get(url, headers=customer_auth["headers"]).json()["lines"]
    assert line["reviewed"] is True

    # Another customer's order, and an unknown number, are both 404.
    assert client.get(url, headers=second_customer_auth["headers"]).status_code == 404
    unknown = client.get(
        f"{API}/customers/me/orders/number/ORD-NOPE", headers=customer_auth["headers"]
    )
    assert unknown.status_code == 404
    assert client.get(url).status_code == 401
