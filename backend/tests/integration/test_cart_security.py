"""Module 11 cart security: abuse limits (S1, S3), merge audit (S4) and the evidence gaps of the
decision-readiness review (D-C1, D-C3, D-C7). Disposable per-test PostgreSQL schema.
"""

import hashlib
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.rate_limit import (
    CartRateLimiter,
    RateLimitStoreUnavailable,
    client_network,
    get_cart_rate_limiter,
)
from app.core.security import generate_session_token, hash_session_token
from app.main import app
from app.models import Cart
from app.models.identity import User
from app.models.operations import AuditRecord
from app.models.session import UserSession
from app.repositories.audit_repository import AuditRepository
from tests.support.commerce import seed_sku

CART = "/api/v1/cart"
ITEMS = f"{CART}/items"
MERGE = f"{CART}/merge"
LIMIT = 10  # default cart_guest_creations_per_ip (proposal pending approval)
REFUSALS = 20  # default cart_stock_refusals_per_window (proposal pending approval)


def sku(db: Session, on_hand: int = 10) -> str:
    variant = seed_sku(db, on_hand=on_hand)
    db.commit()
    return str(variant.id)


def peer(ip: str) -> TestClient:
    """A client whose direct peer address is `ip` (dependency overrides are shared)."""
    return TestClient(app, client=(ip, 50000))


def add(c: TestClient, variant_id: str, quantity: int = 1, headers: dict | None = None):
    return c.post(
        ITEMS, json={"variant_id": variant_id, "quantity": quantity}, headers=headers or {}
    )


def carts(db: Session) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Cart)) or 0


def code(res) -> str:
    return res.json()["error"]["code"]


class DownStore:
    """A rate-limit store whose Redis is unreachable."""

    def get(self, key):
        raise RateLimitStoreUnavailable

    def hit(self, key, window_seconds):
        raise RateLimitStoreUnavailable

    def reset(self, key):
        raise RateLimitStoreUnavailable


# ---- S1: guest-cart creation limit -----------------------------------------------------------
def test_new_guest_carts_are_limited_per_network_with_retry_after(client, db, clock):
    variant = sku(db, on_hand=50)
    c = peer("203.0.113.7")
    tokens = []
    for _ in range(LIMIT):
        res = add(c, variant)
        assert res.status_code == 200, res.text
        tokens.append(res.json()["cart_token"])
    over = add(c, variant)
    assert over.status_code == 429 and code(over) == "rate_limited"
    assert 0 < int(over.headers["Retry-After"]) <= 3600
    assert "cart_token" not in over.text and carts(db) == LIMIT
    # Existing carts keep working: the limit is on creation only.
    assert add(c, variant, 1, {"X-Cart-Token": tokens[0]}).status_code == 200
    assert c.get(CART, headers={"X-Cart-Token": tokens[0]}).status_code == 200
    clock.advance(3601)  # the window has passed
    assert add(c, variant).status_code == 200


def test_networks_are_counted_separately_and_ipv6_by_slash_64(client, db):
    variant = sku(db, on_hand=50)
    for _ in range(LIMIT):
        assert add(peer("2001:db8:1:1::1"), variant).status_code == 200
    same_64 = add(peer("2001:db8:1:1:ffff::9"), variant)
    assert same_64.status_code == 429  # same /64: same bucket
    assert add(peer("2001:db8:1:2::1"), variant).status_code == 200  # another /64
    assert add(peer("198.51.100.4"), variant).status_code == 200  # another IPv4 address


def test_ipv4_mapped_peers_are_limited_by_their_own_ipv4_address(client, db):
    """Dual-stack listeners see IPv4 clients as ::ffff:a.b.c.d; each keeps its own bucket."""
    variant = sku(db, on_hand=50)
    for _ in range(LIMIT):
        assert add(peer("::ffff:203.0.113.20"), variant).status_code == 200
    assert add(peer("::ffff:203.0.113.20"), variant).status_code == 429
    assert add(peer("203.0.113.20"), variant).status_code == 429  # the same client, unmapped
    assert add(peer("::ffff:203.0.113.21"), variant).status_code == 200  # another IPv4 client


def test_forwarding_headers_from_the_client_are_not_trusted(client, db):
    variant = sku(db, on_hand=50)
    c = peer("192.0.2.10")
    for i in range(LIMIT):
        spoofed = {"X-Forwarded-For": f"10.0.0.{i}", "X-Real-IP": f"10.1.0.{i}"}
        assert add(c, variant, 1, spoofed).status_code == 200
    rotated = add(c, variant, 1, {"X-Forwarded-For": "10.9.9.9", "Forwarded": "for=10.8.8.8"})
    assert rotated.status_code == 429


def test_customers_are_not_limited_by_the_guest_creation_limit(client, db, customer_auth):
    variant = sku(db, on_hand=50)
    c = peer("203.0.113.8")
    for _ in range(LIMIT):
        add(c, variant)
    assert add(c, variant).status_code == 429
    assert add(c, variant, 1, customer_auth["headers"]).status_code == 200


def test_unusable_addresses_share_one_bucket():
    assert client_network(None) == client_network("not-an-ip") == "unknown"
    assert client_network("203.0.113.7") == "203.0.113.7"
    assert client_network("2001:db8:1:1::5") == "2001:db8:1:1::/64"


def test_redis_down_refuses_new_guest_carts_but_existing_carts_keep_working(
    client, db, customer_auth, caplog
):
    variant = sku(db, on_hand=50)
    token = add(client, variant).json()["cart_token"]
    app.dependency_overrides[get_cart_rate_limiter] = lambda: CartRateLimiter(
        DownStore(), _settings()
    )
    with caplog.at_level(logging.WARNING):
        refused = add(client, variant)
        assert refused.status_code == 503 and code(refused) == "cart_creation_unavailable"
        assert carts(db) == 1
        kept = add(client, variant, 1, {"X-Cart-Token": token})
        assert kept.status_code == 200 and kept.json()["lines"][0]["quantity"] == 2
        assert add(client, variant, 1, customer_auth["headers"]).status_code == 200
    assert "rate-limit store is unavailable" in caplog.text  # never silent
    assert token not in caplog.text


def _settings():
    from app.core.config import get_settings

    return get_settings()


# ---- S3: stock probing -----------------------------------------------------------------------
def test_refusals_never_reveal_a_quantity(client, db, customer_auth):
    variant = sku(db, on_hand=7)
    res = add(client, variant, 8, customer_auth["headers"])
    assert res.status_code == 409 and code(res) == "insufficient_stock"
    assert "7" not in res.text and "8" not in res.text
    public = client.get(CART, headers=customer_auth["headers"]).json()
    assert "available_quantity" not in str(public) and "on_hand" not in str(public)


def test_repeated_refusals_are_limited_but_lowering_and_removing_still_work(
    client, db, customer_auth, clock
):
    h = customer_auth["headers"]
    probed, other = sku(db, on_hand=5), sku(db, on_hand=50)
    cart = add(client, other, 10, h).json()
    line = cart["lines"][0]["id"]
    for quantity in range(6, 6 + REFUSALS):
        assert add(client, probed, min(quantity, 99), h).status_code == 409
    blocked = add(client, probed, 1, h)  # would succeed, but the probe limit is reached
    assert blocked.status_code == 429 and code(blocked) == "rate_limited"
    assert int(blocked.headers["Retry-After"]) > 0
    raising = client.patch(f"{ITEMS}/{line}", json={"quantity": 11}, headers=h)
    assert raising.status_code == 429
    lowering = client.patch(f"{ITEMS}/{line}", json={"quantity": 3}, headers=h)
    assert lowering.status_code == 200 and lowering.json()["lines"][0]["quantity"] == 3
    assert client.get(CART, headers=h).status_code == 200
    assert client.delete(f"{ITEMS}/{line}", headers=h).status_code == 204
    clock.advance(901)
    assert add(client, probed, 1, h).status_code == 200


def test_the_probe_limit_follows_the_owner_across_networks(client, db, customer_auth):
    h = customer_auth["headers"]
    probed = sku(db, on_hand=2)
    for i in range(REFUSALS):
        assert add(peer(f"198.51.100.{i + 1}"), probed, 3, h).status_code == 409
    assert add(peer("198.51.100.200"), probed, 1, h).status_code == 429


def test_the_probe_limit_is_skipped_with_a_warning_when_redis_is_down(
    client, db, customer_auth, caplog
):
    app.dependency_overrides[get_cart_rate_limiter] = lambda: CartRateLimiter(
        DownStore(), _settings()
    )
    probed = sku(db, on_hand=2)
    with caplog.at_level(logging.WARNING):
        assert add(client, probed, 3, customer_auth["headers"]).status_code == 409
        assert add(client, probed, 1, customer_auth["headers"]).status_code == 200
    assert "stock-probe limit skipped" in caplog.text
    assert "refusal not counted" in caplog.text


# ---- S4: merge audit -------------------------------------------------------------------------
def merge_records(db: Session) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == "cart.merge")))


def test_a_merge_is_audited_with_ids_and_counts_only(client, db, customer_auth):
    h = customer_auth["headers"]
    a, b = sku(db, on_hand=50), sku(db, on_hand=50)
    res = add(client, a, 3)
    token = res.json()["cart_token"]
    add(client, b, 2, {"X-Cart-Token": token})
    merged = client.post(MERGE, headers={**h, "X-Cart-Token": token})
    assert merged.status_code == 200
    (record,) = merge_records(db)
    guest_id = db.scalar(select(Cart.id).where(Cart.guest_token_hash.is_not(None)))
    assert str(record.actor_user_id) == customer_auth["user"]["id"]
    assert record.entity_type == "cart" and record.entity_id == merged.json()["cart"]["id"]
    summary = record.change_summary
    assert summary["guest_cart_id"] == str(guest_id)
    assert (summary["guest_lines"], summary["merged"], summary["capped"]) == (2, 2, 0)
    assert (summary["excluded"], summary["units_added"]) == (0, 5)
    stored = str(summary) + str(record.entity_id)
    assert token not in stored and hashlib.sha256(token.encode()).hexdigest() not in stored
    assert h["Authorization"].split()[1] not in stored


def test_a_failed_audit_rolls_the_merge_back(client, db, customer_auth, monkeypatch):
    h = customer_auth["headers"]
    variant = sku(db, on_hand=50)
    token = add(client, variant, 2).json()["cart_token"]
    real = AuditRepository.create

    def fail_merge_audit(*args, **kwargs):
        if kwargs.get("action") == "cart.merge":
            raise RuntimeError("audit store unavailable")
        return real(*args, **kwargs)

    monkeypatch.setattr(AuditRepository, "create", staticmethod(fail_merge_audit))
    with pytest.raises(RuntimeError):
        client.post(MERGE, headers={**h, "X-Cart-Token": token})
    monkeypatch.undo()
    assert merge_records(db) == []
    assert client.get(CART, headers={"X-Cart-Token": token}).json()["lines"][0]["quantity"] == 2
    assert client.get(CART, headers=h).json()["lines"] == []
    assert client.post(MERGE, headers={**h, "X-Cart-Token": token}).status_code == 200
    assert len(merge_records(db)) == 1


def test_a_repeated_or_refused_merge_writes_no_audit(client, db, customer_auth):
    h = customer_auth["headers"]
    token = add(client, sku(db), 1).json()["cart_token"]
    assert client.post(MERGE, headers={**h, "X-Cart-Token": token}).status_code == 200
    assert client.post(MERGE, headers={**h, "X-Cart-Token": token}).status_code == 404
    unknown = client.post(MERGE, headers={**h, "X-Cart-Token": "u" * 43})
    assert unknown.status_code == 404
    assert len(merge_records(db)) == 1


# ---- evidence gaps (decision-readiness review) -----------------------------------------------
def test_dc1_a_guest_first_add_refused_with_422_creates_no_cart(client, db):
    variant = seed_sku(db, on_hand=5, is_active=False)
    db.commit()
    res = add(client, str(variant.id))
    assert res.status_code == 422 and "cart_token" not in res.text
    assert carts(db) == 0


def test_dc3_a_merge_never_lowers_a_line_above_current_stock(client, db, customer_auth):
    h = customer_auth["headers"]
    variant = sku(db, on_hand=10)
    add(client, variant, 8, h)
    token = add(client, variant, 2).json()["cart_token"]
    db.execute(
        text("UPDATE inventory_balances SET on_hand = 5 WHERE variant_id = :v"), {"v": variant}
    )
    db.commit()
    res = client.post(MERGE, headers={**h, "X-Cart-Token": token}).json()
    assert res["cart"]["lines"][0]["quantity"] == 8  # kept, now flagged
    assert res["cart"]["lines"][0]["status"] == "insufficient_stock"
    (line,) = res["merged_lines"]
    assert (line["added_quantity"], line["outcome"], line["reason"]) == (
        0,
        "excluded",
        "insufficient_stock",
    )


def test_dc7_a_staff_flagged_account_without_a_role_has_no_cart(client, db):
    user = User(email="flagged@example.com", full_name="Flagged", password_hash="x", is_staff=True)
    db.add(user)
    db.flush()
    raw = generate_session_token()
    now = datetime.now(UTC)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(raw),
            last_active_at=now,
            expires_at=now + timedelta(days=1),
        )
    )
    db.commit()
    h = {"Authorization": f"Bearer {raw}"}
    for res in (client.get(CART, headers=h), add(client, sku(db), 1, h)):
        assert res.status_code == 403 and code(res) == "customer_only"
    assert carts(db) == 0


def test_dc7_an_invalid_bearer_is_401_on_every_cart_route(client, db):
    bad = {"Authorization": "Bearer not-a-session", "X-Cart-Token": "t" * 43}
    item = "6f1c2e9a-3b4d-4e5f-8a9b-0c1d2e3f4a5b"
    attempts = [
        client.patch(f"{ITEMS}/{item}", json={"quantity": 1}, headers=bad),
        client.delete(f"{ITEMS}/{item}", headers=bad),
        client.post(MERGE, headers=bad),
    ]
    assert [r.status_code for r in attempts] == [401] * 3


# ---- configuration ---------------------------------------------------------------------------
@pytest.mark.parametrize("origins", ["*", "https://shop.example.rw,*", "https://*.example.rw"])
def test_wildcard_cors_origins_are_refused(origins):
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="explicit origins"):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://x:y@127.0.0.1:1/x",
            audit_hmac_key="k" * 40,
            cors_origins=origins,
        )


# ---- review follow-ups -----------------------------------------------------------------------
def test_a_probe_refused_new_guest_request_does_not_use_the_creation_budget(
    client, db, customer_auth, clock
):
    c = peer("203.0.113.40")
    probed, plenty = sku(db, on_hand=2), sku(db, on_hand=50)
    for _ in range(REFUSALS):  # refusals from this network, by a customer
        assert add(c, probed, 3, customer_auth["headers"]).status_code == 409
    assert add(c, plenty).status_code == 429  # a new guest cart: refused by the probe limit
    assert carts(db) == 0
    clock.advance(901)  # the probe window has passed; the creation window has not
    for _ in range(LIMIT):  # the whole creation budget is still available
        assert add(c, plenty).status_code == 200
    assert add(c, plenty).status_code == 429


def test_a_price_change_during_a_cart_read_is_flagged_not_a_500(
    client, db, customer_auth, monkeypatch
):
    from app.models import ProductVariant
    from app.services import cart_service
    from app.services.pricing import AmountOutOfRange

    h = customer_auth["headers"]
    raised, cheap = sku(db, on_hand=99), sku(db, on_hand=99)
    add(client, raised, 60, h)
    add(client, cheap, 1, h)
    real = cart_service.quote_merchandise
    calls = {"n": 0}

    def price_changes_mid_read(session, lines):
        calls["n"] += 1
        if calls["n"] == 1:  # a staff price change lands after the amount check
            session.execute(
                ProductVariant.__table__.update()
                .where(ProductVariant.id == raised)
                .values(price=20_000_000_000)
            )
            raise AmountOutOfRange()
        return real(session, lines)

    monkeypatch.setattr(cart_service, "quote_merchandise", price_changes_mid_read)
    res = client.get(CART, headers=h)
    assert res.status_code == 200, res.text
    status = {line["variant_id"]: line["status"] for line in res.json()["lines"]}
    assert status == {raised: "amount_out_of_range", cheap: "available"}
    assert res.json()["merchandise_subtotal"] == 1000
