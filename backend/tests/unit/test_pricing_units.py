"""RE-026 S1 pricing rules that need no database (PR-05; TC-06 tampering)."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.pricing import MerchandiseQuoteRequest
from app.services.inventory import MAX_QUANTITY
from app.services.pricing import (
    DuplicateSkuLine,
    MerchandiseQuote,
    PricedLine,
    PricingPolicyNotApproved,
    validate_lines,
)

SKU = str(uuid.uuid4())
CLIENT_AMOUNT_FIELDS = [
    "unit_price",
    "price",
    "line_subtotal",
    "line_total",
    "discount_amount",
    "tax_amount",
]
CLIENT_TOTAL_FIELDS = [
    "subtotal",
    "merchandise_subtotal",
    "discount_total",
    "delivery_fee",
    "tax_total",
    "total",
    "currency_code",
]


@pytest.mark.parametrize("field", CLIENT_AMOUNT_FIELDS)
def test_request_rejects_client_line_amounts(field):
    with pytest.raises(ValidationError) as exc:
        MerchandiseQuoteRequest.model_validate(
            {"lines": [{"variant_id": SKU, "quantity": 1, field: "1.00"}]}
        )
    assert exc.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("field", CLIENT_TOTAL_FIELDS)
def test_request_rejects_client_totals(field):
    with pytest.raises(ValidationError) as exc:
        MerchandiseQuoteRequest.model_validate(
            {"lines": [{"variant_id": SKU, "quantity": 1}], field: "0"}
        )
    assert exc.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("quantity", [0, -1, MAX_QUANTITY + 1, 1.5, "2", True, None])
def test_request_rejects_invalid_quantities(quantity):
    with pytest.raises(ValidationError):
        MerchandiseQuoteRequest.model_validate(
            {"lines": [{"variant_id": SKU, "quantity": quantity}]}
        )


def test_request_rejects_empty_and_duplicate_lines():
    with pytest.raises(ValidationError):
        MerchandiseQuoteRequest.model_validate({"lines": []})
    with pytest.raises(ValidationError, match="only one line"):
        MerchandiseQuoteRequest.model_validate(
            {"lines": [{"variant_id": SKU, "quantity": 1}, {"variant_id": SKU, "quantity": 2}]}
        )


def test_valid_request_carries_only_sku_and_quantity():
    request = MerchandiseQuoteRequest.model_validate(
        {"lines": [{"variant_id": SKU, "quantity": 3}]}
    )
    assert request.line_tuples() == [(uuid.UUID(SKU), 3)]


@pytest.mark.parametrize("quantity", [0, -5, MAX_QUANTITY + 1, 2.0, "1", True, None])
def test_service_rejects_invalid_quantities(quantity):
    with pytest.raises(ValueError):
        validate_lines([(uuid.uuid4(), quantity)])


@pytest.mark.parametrize("variant_id", ["not-a-uuid", SKU, 42, None])
def test_service_rejects_non_uuid_sku_ids(variant_id):
    with pytest.raises(ValueError, match="must be a UUID"):
        validate_lines([(variant_id, 1)])


def test_service_rejects_duplicate_and_empty_lines():
    first, second = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(DuplicateSkuLine) as exc:
        validate_lines([(first, 1), (second, 1), (first, 1)])
    assert exc.value.variant_ids == [first]
    with pytest.raises(ValueError, match="at least one line"):
        validate_lines([])


def test_service_keeps_request_order():
    first, second = uuid.uuid4(), uuid.uuid4()
    assert list(validate_lines([(second, 2), (first, 1)])) == [second, first]


def test_order_total_fails_closed_until_policies_are_approved():
    line = PricedLine(uuid.uuid4(), "SKU", 1, 10, 10)
    quote = MerchandiseQuote(lines=(line,), merchandise_subtotal=10)
    with pytest.raises(PricingPolicyNotApproved):
        quote.order_total()
