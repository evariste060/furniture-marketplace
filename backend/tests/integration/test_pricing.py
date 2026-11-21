"""RE-026 S1 merchandise pricing on PostgreSQL (PR-05; TC-06 subtotal and tampering).

Prices, sellability and availability come from the database under the ADR-002 stock lifecycle.
Delivery, discount and tax are not priced (unapproved), so the order total fails closed.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models import AuditRecord, InventoryBalance, ProductVariant, StockReservation
from app.models.common import MAX_MONEY_RWF
from app.schemas.pricing import MerchandiseQuoteRequest
from app.services import inventory as inv
from app.services.inventory import InsufficientStock, SkuNotSellable, UnknownSku
from app.services.pricing import (
    AmountOutOfRange,
    DuplicateSkuLine,
    PricingPolicyNotApproved,
    quote_merchandise,
)
from tests.support.commerce import new_order, seed_sku, soon


@pytest.fixture
def sf(pg_engine):
    return sessionmaker(bind=pg_engine, expire_on_commit=False)


def make_sku(sf, on_hand=5, price: int | None = None, **overrides) -> ProductVariant:
    with sf() as s, s.begin():
        variant = seed_sku(s, on_hand=on_hand, **overrides)
        if price is not None:  # seed_sku fixes the price; override it in the same transaction
            variant.price = price
        return variant


def quote(sf, lines):
    with sf() as s:
        return quote_merchandise(s, lines)


def test_lines_are_priced_from_database_prices_in_whole_rwf(sf):
    phone = make_sku(sf, on_hand=10, price=125001)
    cable = make_sku(sf, on_hand=10, price=150)
    result = quote(sf, [(phone.id, 3), (cable.id, 7)])

    assert [(line.variant_id, line.quantity) for line in result.lines] == [
        (phone.id, 3),
        (cable.id, 7),
    ]
    assert [line.unit_price for line in result.lines] == [125001, 150]
    assert [line.line_subtotal for line in result.lines] == [375003, 1050]
    assert result.lines[0].sku == phone.sku
    assert result.merchandise_subtotal == 376053
    assert result.currency_code == "RWF"
    assert all(type(line.line_subtotal) is int for line in result.lines)
    assert type(result.merchandise_subtotal) is int
    with pytest.raises(PricingPolicyNotApproved):
        result.order_total()


def test_price_changes_in_the_database_are_reflected_and_compare_at_is_ignored(sf):
    variant = make_sku(sf, price=1000, compare_at_price=1500)
    assert quote(sf, [(variant.id, 2)]).merchandise_subtotal == 2000
    with sf() as s, s.begin():
        s.get(ProductVariant, variant.id).price = 900
    assert quote(sf, [(variant.id, 2)]).merchandise_subtotal == 1800


def test_tampered_request_amounts_are_rejected_before_pricing(sf):
    variant = make_sku(sf, price=1000)
    tampered = {
        "lines": [{"variant_id": str(variant.id), "quantity": 1, "unit_price": "1.00"}],
        "total": "1.00",
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MerchandiseQuoteRequest.model_validate(tampered)
    clean = MerchandiseQuoteRequest.model_validate(
        {"lines": [{"variant_id": str(variant.id), "quantity": 1}]}
    )
    assert quote(sf, clean.line_tuples()).merchandise_subtotal == 1000


def test_unknown_sku_is_rejected(sf):
    known = make_sku(sf)
    unknown = uuid4()
    with pytest.raises(UnknownSku) as exc:
        quote(sf, [(known.id, 1), (unknown, 1)])
    assert exc.value.variant_ids == [unknown]


@pytest.mark.parametrize("target", ["variant", "product", "category", "brand"])
def test_non_sellable_sku_is_rejected(sf, target):
    variant = make_sku(sf)
    with sf() as s, s.begin():
        row = s.get(ProductVariant, variant.id)
        if target == "variant":
            row.is_active = False
        elif target == "product":
            row.product.status = "draft"
        elif target == "category":
            row.product.category.is_active = False
        else:
            row.product.brand.is_active = False
    with pytest.raises(SkuNotSellable) as exc:
        quote(sf, [(variant.id, 1)])
    assert exc.value.variant_ids == [variant.id]


@pytest.mark.parametrize("quantity", [0, -1, 1.5, "1", True])
def test_invalid_quantities_are_rejected(sf, quantity):
    variant = make_sku(sf)
    with pytest.raises(ValueError):
        quote(sf, [(variant.id, quantity)])


def test_duplicate_sku_lines_are_rejected(sf):
    variant = make_sku(sf)
    with pytest.raises(DuplicateSkuLine):
        quote(sf, [(variant.id, 1), (variant.id, 1)])


def test_missing_inventory_record_means_unavailable(sf):
    variant = make_sku(sf, on_hand=None)
    with pytest.raises(InsufficientStock) as exc:
        quote(sf, [(variant.id, 1)])
    assert (exc.value.requested, exc.value.available) == (1, 0)


def test_active_committed_and_unavailable_units_reduce_availability(sf):
    variant = make_sku(sf, on_hand=6)
    with sf() as s:
        held = inv.create_order_with_reservations(
            s, new_order({variant.id: 1}), expires_at=soon()
        ).order.id
    with sf() as s:
        paid = inv.create_order_with_reservations(
            s, new_order({variant.id: 2}), expires_at=soon()
        ).order.id
    with sf() as s:
        inv.commit_order_reservations(s, paid)
    with sf() as s, s.begin():
        s.scalar(
            select(InventoryBalance).where(InventoryBalance.variant_id == variant.id)
        ).unavailable_quantity = 1
    # 6 on hand - 1 unavailable - 1 active - 2 committed = 2 available
    assert quote(sf, [(variant.id, 2)]).merchandise_subtotal == 2000
    with pytest.raises(InsufficientStock) as exc:
        quote(sf, [(variant.id, 3)])
    assert exc.value.available == 2

    # Released holds stop counting, exactly as in the reservation lifecycle.
    with sf() as s:
        inv.release_order_reservations(s, held, reason="cancelled")
    assert quote(sf, [(variant.id, 3)]).merchandise_subtotal == 3000


def test_amounts_beyond_the_storable_range_are_rejected(sf):
    variant = make_sku(sf, on_hand=2, price=MAX_MONEY_RWF)
    assert quote(sf, [(variant.id, 1)]).merchandise_subtotal == MAX_MONEY_RWF
    with pytest.raises(AmountOutOfRange):
        quote(sf, [(variant.id, 2)])


def test_quoting_writes_nothing(sf):
    variant = make_sku(sf, on_hand=3)

    def counts(s):
        return (
            s.scalar(select(func.count(StockReservation.id))),
            s.scalar(select(func.count(AuditRecord.id))),
            s.scalar(
                select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == variant.id)
            ),
        )

    with sf() as s:
        before = counts(s)
        quote_merchandise(s, [(variant.id, 2)])
        assert not (s.new or s.dirty or s.deleted)
        s.rollback()
        assert counts(s) == before
