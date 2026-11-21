"""Guest order lookup limits (module 14, D-O3; ADR-008 S6, approved 2026-10-25): 5 failed
lookups per order number and 20 per IP per 15 minutes; failures only; 429 with Retry-After;
fail closed (503) while the store is unreachable. Disposable per-test PostgreSQL schema."""

import pytest

from app.core.config import get_settings
from app.core.rate_limit import (
    LoginRateLimiter,
    RateLimitStoreUnavailable,
    get_order_lookup_rate_limiter,
)
from app.main import app
from tests.integration.test_cart_api import code
from tests.integration.test_cart_security import DownStore, peer
from tests.integration.test_checkout_api import checkout, guest_cart
from tests.integration.test_delivery_api import create_zone, set_threshold
from tests.support.memory_rate_limit import MemoryRateLimitStore

LOOKUP = "/api/v1/orders/lookup"
PER_ORDER, PER_IP, WINDOW = 5, 20, 900
PHONE = "0788123456"  # INLINE's phone
WRONG = "0788999999"


@pytest.fixture
def delivery(client, admin_auth) -> None:
    create_zone(client, admin_auth["headers"], "Gasabo", 2000)
    set_threshold(client, admin_auth["headers"], 200_000)


def lookup(c, number: str, phone: str):
    return c.post(LOOKUP, json={"order_number": number, "phone": phone})


def place(client, db) -> str:
    res = checkout(client, guest_cart(client, db))
    assert res.status_code == 201, res.text
    return res.json()["order"]["order_number"]


def test_the_policy_values_are_the_approved_ones():
    settings = get_settings()
    assert settings.order_lookup_max_failures_per_order == PER_ORDER
    assert settings.order_lookup_max_failures_per_ip == PER_IP
    assert settings.order_lookup_window_seconds == WINDOW


def test_five_failures_per_order_number_then_429_until_the_window_ends(client, db, delivery, clock):
    number = place(client, db)
    for _ in range(PER_ORDER):
        assert lookup(client, number, WRONG).status_code == 404
    blocked = lookup(client, number, PHONE)  # even the right phone, once the limit is reached
    assert blocked.status_code == 429 and code(blocked) == "rate_limited"
    assert 0 < int(blocked.headers["Retry-After"]) <= WINDOW
    assert "order_number" not in blocked.text and "+2507" not in blocked.text
    other = place(client, db)
    assert lookup(client, other, PHONE).status_code == 200  # another number is not affected
    clock.advance(WINDOW + 1)
    assert lookup(client, number, PHONE).status_code == 200


def test_unknown_numbers_count_like_wrong_phones(client, db, delivery):
    for _ in range(PER_ORDER):
        assert lookup(client, "ORD-000000-ZZZZZZ", PHONE).status_code == 404
    assert lookup(client, "ORD-000000-ZZZZZZ", PHONE).status_code == 429


def test_successful_lookups_are_not_counted(client, db, delivery):
    number = place(client, db)
    for _ in range(PER_ORDER * 3):
        assert lookup(client, number, PHONE).status_code == 200
    for _ in range(PER_ORDER - 1):
        assert lookup(client, number, WRONG).status_code == 404
    assert lookup(client, number, PHONE).status_code == 200  # 4 failures: still allowed
    assert lookup(client, number, WRONG).status_code == 404  # the 5th
    assert lookup(client, number, PHONE).status_code == 429


def test_twenty_failures_per_ip_across_order_numbers(client, db, delivery):
    attacker = peer("198.51.100.77")
    for i in range(PER_IP):
        assert lookup(attacker, f"ORD-000000-A{i:05d}", PHONE).status_code == 404
    number = place(client, db)
    blocked = lookup(attacker, number, PHONE)
    assert blocked.status_code == 429  # the IP limit, for any number
    assert lookup(peer("198.51.100.78"), number, PHONE).status_code == 200


def test_an_unreachable_store_answers_503_for_hits_and_misses_alike(client, db, delivery):
    number = place(client, db)
    app.dependency_overrides[get_order_lookup_rate_limiter] = lambda: LoginRateLimiter(
        DownStore(), get_settings(), prefix="order_lookup"
    )
    hit = lookup(client, number, PHONE)
    miss = lookup(client, number, WRONG)
    unknown = lookup(client, "ORD-000000-ZZZZZZ", PHONE)
    assert hit.status_code == miss.status_code == unknown.status_code == 503
    assert hit.json() == miss.json() == unknown.json()  # nothing tells a hit from a miss
    assert code(hit) == "order_lookup_unavailable"


class _FailsOnCount(MemoryRateLimitStore):
    """Reads work; counting a failure finds the store gone (an outage mid-request)."""

    def hit(self, key, window_seconds):
        raise RateLimitStoreUnavailable


def test_a_store_lost_while_counting_still_answers_the_404(client, db, delivery, clock):
    number = place(client, db)
    app.dependency_overrides[get_order_lookup_rate_limiter] = lambda: LoginRateLimiter(
        _FailsOnCount(clock), get_settings(), prefix="order_lookup"
    )
    res = lookup(client, number, WRONG)
    assert res.status_code == 404 and code(res) == "order_not_found"  # never a revealing 503
    assert lookup(client, number, PHONE).status_code == 200
