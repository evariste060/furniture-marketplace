"""Checkout rules without a database (module 14; ADR-007; §7 Q15, Q16, Q21)."""

import re
from datetime import UTC, datetime
from fractions import Fraction

import pytest
from pydantic import ValidationError

from app.core.money import vat_component
from app.schemas.checkout import CheckoutRequest
from app.schemas.order import OrderLookupRequest, OrderStatusUpdateRequest
from app.services.checkout_service import HOLDS, available_methods, new_order_number

ADDRESS = {
    "recipient_name": "Aline",
    "phone": "0788123456",
    "district": "Gasabo",
    "street_address": "KG 11 Ave",
}


@pytest.mark.parametrize(
    ("total", "vat"),
    [(0, 0), (118, 18), (1180, 180), (22_000, 3356), (100, 15), (59, 9), (1, 0)],
)
def test_vat_is_extracted_from_the_inclusive_total(total, vat):
    # 18/118 of the total, nearest whole RWF, an exact half down (ADR-007)
    assert vat_component(total) == vat


def test_vat_never_lands_on_an_exact_half_and_refuses_negative_amounts():
    """total x 18/118 = k + 1/2 would need 18 to divide 59 x (2k + 1), an odd number, so the
    half-down tie rule of ADR-007 never applies to VAT; ordinary rounding does."""
    assert all(Fraction(t * 18, 118).denominator != 2 for t in range(0, 20_000))
    assert vat_component(1_000) == 153  # 152.54 -> 153 (nearest)
    with pytest.raises(ValueError):
        vat_component(-1)


def test_payment_methods_follow_the_zone_and_never_offer_card():
    assert available_methods(True) == ["mtn_momo", "airtel_money", "cash_on_delivery"]
    assert available_methods(False) == ["mtn_momo", "airtel_money"]
    assert "card" not in available_methods(True)  # §7 Q21
    assert HOLDS["mtn_momo"].total_seconds() == 15 * 60  # §7 Q11
    assert HOLDS["cash_on_delivery"].total_seconds() == 24 * 3600  # §7 Q13


class _NoCollisions:
    def scalar(self, _query):
        return None


def test_order_numbers_are_random_and_dated_in_kigali_time():
    late_utc = datetime(2026, 10, 25, 23, 30, tzinfo=UTC)  # already the 26th in Kigali
    numbers = {new_order_number(_NoCollisions(), late_utc) for _ in range(50)}  # type: ignore[arg-type]
    assert len(numbers) == 50
    assert all(re.fullmatch(r"ORD-261026-[2-9A-HJ-NP-Z]{6}", n) for n in numbers)


def test_a_request_names_exactly_one_address_and_no_amounts():
    ok = CheckoutRequest.model_validate({"address": ADDRESS, "payment_method": "mtn_momo"})
    assert ok.address is not None and ok.address.phone == "+250788123456"
    for body in (
        {"payment_method": "mtn_momo"},
        {
            "address": ADDRESS,
            "address_id": "8f9b1e5e-1111-4a2b-9c3d-000000000001",
            "payment_method": "mtn_momo",
        },
        {"address": ADDRESS, "payment_method": "mtn_momo", "total": 1},
        {"address": {**ADDRESS, "unit_price": 1}, "payment_method": "mtn_momo"},
        {"address": ADDRESS, "payment_method": "paypal"},
    ):
        with pytest.raises(ValidationError):
            CheckoutRequest.model_validate(body)


def test_the_fingerprint_is_stable_and_tells_requests_apart():
    a = CheckoutRequest.model_validate({"address": ADDRESS, "payment_method": "mtn_momo"})
    same = CheckoutRequest.model_validate(
        {"payment_method": "mtn_momo", "address": {**ADDRESS, "phone": "+250 788 123 456"}}
    )
    other = CheckoutRequest.model_validate({"address": ADDRESS, "payment_method": "airtel_money"})
    assert a.fingerprint() == same.fingerprint()  # normalised before hashing
    assert a.fingerprint() != other.fingerprint()
    assert re.fullmatch(r"[0-9a-f]{64}", a.fingerprint())


def test_lookup_and_status_requests_are_normalised():
    req = OrderLookupRequest.model_validate(
        {"order_number": " ord-261025-abcdef ", "phone": "0788123456"}
    )
    assert (req.order_number, req.phone) == ("ORD-261025-ABCDEF", "+250788123456")
    with pytest.raises(ValidationError):
        OrderLookupRequest.model_validate({"order_number": "X", "phone": "123"})
    assert OrderStatusUpdateRequest.model_validate({"status": "cancelled"}).reason is None
    with pytest.raises(ValidationError):
        OrderStatusUpdateRequest.model_validate({"status": "cancelled", "reason": "x" * 501})
