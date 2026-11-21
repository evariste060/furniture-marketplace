"""Server-side order pricing (RE-026), slice S1: trusted merchandise subtotal.

Only approved rules are applied:
- Unit prices come from product_variants.price. A client never supplies a price or total
  (AGENTS.md; ADR-002 'Integrity rules and indexes'). compare_at_price is not used: whether it
  drives a discount is unresolved.
- A SKU must be sellable and available under the ADR-002 stock lifecycle (approved 2026-10-22),
  using the same checks as app/services/inventory.py.
- Amounts are whole RWF integers (ADR-007). Price times a whole quantity is exact, so no rounding
  happens here; any amount above MAX_MONEY_RWF is rejected rather than stored.

Delivery fees, discounts, tax and the order total are not calculated yet: they are added by the
delivery, promotions and checkout modules (docs/IMPLEMENTATION_PLAN.md). Until then, asking for
the order total raises PricingPolicyNotApproved instead of defaulting any of them to zero.

This is a read-only quote and takes no locks. Its reads are separate statements, so under READ
COMMITTED a concurrent catalogue or stock change can land between them; checkout (RE-026 S5) must
reprice inside its order transaction, where create_order_with_reservations re-checks sellability
and stock under row locks.

Quantity and sellability use the inventory service's public check_quantity and check_sellable,
so the rules cannot drift between quoting and reserving.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProductVariant
from app.models.common import MAX_MONEY_RWF
from app.repositories.catalog import get_available_quantities
from app.services.inventory import InsufficientStock, check_quantity, check_sellable

CURRENCY_CODE = "RWF"  # product_variants and orders are constrained to RWF
MAX_AMOUNT = MAX_MONEY_RWF  # largest storable amount (ADR-007)


class PricingError(Exception):
    """Base class for pricing rule violations; messages are safe to show."""


class DuplicateSkuLine(PricingError):
    def __init__(self, variant_ids: Iterable[UUID]):
        self.variant_ids = sorted(variant_ids)
        super().__init__("Each SKU may appear on only one line.")


class AmountOutOfRange(PricingError):
    def __init__(self) -> None:
        super().__init__("The amount exceeds the largest storable order amount.")


class PricingPolicyNotApproved(PricingError):
    def __init__(self) -> None:
        super().__init__(
            "Delivery fee, discount and tax policies are not approved; "
            "an order total cannot be calculated."
        )


@dataclass(frozen=True)
class PricedLine:
    variant_id: UUID
    sku: str
    quantity: int
    unit_price: int
    line_subtotal: int


@dataclass(frozen=True)
class MerchandiseQuote:
    lines: tuple[PricedLine, ...]
    merchandise_subtotal: int
    currency_code: str = CURRENCY_CODE

    def order_total(self) -> int:
        """Not available until delivery, discount and tax policies are approved (RE-026)."""
        raise PricingPolicyNotApproved()


def validate_lines(lines: Iterable[tuple[UUID, int]]) -> dict[UUID, int]:
    """Requested quantity per SKU. Quantities are whole and positive; SKUs are not repeated."""
    requested: dict[UUID, int] = {}
    duplicates: set[UUID] = set()
    for variant_id, quantity in lines:
        if not isinstance(variant_id, UUID):
            raise ValueError("line variant_id must be a UUID")
        quantity = check_quantity(quantity, "line quantity")
        if variant_id in requested:
            duplicates.add(variant_id)
        requested[variant_id] = quantity
    if duplicates:
        raise DuplicateSkuLine(duplicates)
    if not requested:
        raise ValueError("at least one line is required")
    return requested


def quote_merchandise(session: Session, lines: Iterable[tuple[UUID, int]]) -> MerchandiseQuote:
    """Price the requested lines from trusted database prices; lines keep the request order.

    Raises ValueError (non-UUID SKU id, invalid quantity or no lines), DuplicateSkuLine, UnknownSku,
    SkuNotSellable, InsufficientStock or AmountOutOfRange. Nothing is written.
    """
    requested = validate_lines(lines)
    check_sellable(session, set(requested))
    variants = {
        row.id: row
        for row in session.execute(
            select(ProductVariant.id, ProductVariant.sku, ProductVariant.price).where(
                ProductVariant.id.in_(list(requested))
            )
        )
    }
    available = get_available_quantities(session, list(requested))
    priced = []
    for variant_id, quantity in requested.items():
        if quantity > available.get(variant_id, 0):
            raise InsufficientStock(variant_id, quantity, available.get(variant_id, 0))
        variant = variants[variant_id]
        priced.append(
            PricedLine(
                variant_id=variant_id,
                sku=variant.sku,
                quantity=quantity,
                unit_price=variant.price,
                line_subtotal=_storable(variant.price * quantity),
            )
        )
    subtotal = _storable(sum(line.line_subtotal for line in priced))
    return MerchandiseQuote(lines=tuple(priced), merchandise_subtotal=subtotal)


def _storable(amount: int) -> int:
    if amount > MAX_AMOUNT:
        raise AmountOutOfRange()
    return amount
