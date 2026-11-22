"""Cart schemas (module 11; plan §5 and §7 Q10; RE-026 B7).

Requests carry only a variant and a quantity: prices and totals always come from the database
(pricing.quote_merchandise), and any other field, such as a price, is refused (422).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.catalog import StoreReference
from app.schemas.images import PublicImage

MAX_LINE_QUANTITY = 99  # §7 Q10
CART_TOKEN_PATTERN = r"^[A-Za-z0-9_-]{20,100}$"

LineStatus = Literal["available", "unavailable", "insufficient_stock", "amount_out_of_range"]


class CartItemAddRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"variant_id": "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b", "quantity": 1}]
        },
    )

    variant_id: uuid.UUID = Field(description="The variant (SKU) to add, from the catalogue")
    quantity: int = Field(
        ge=1,
        le=MAX_LINE_QUANTITY,
        description="Units to add; added to the line if the variant is already in the cart",
    )


class CartItemUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"quantity": 3}]})

    quantity: int = Field(
        ge=1, le=MAX_LINE_QUANTITY, description="New number of units on the line, 1 to 99"
    )


class CartLine(BaseModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    product_slug: str
    variant_name: str
    quantity: int
    status: LineStatus = Field(
        description="available: priced and counted; unavailable: the product is no longer sold; "
        "insufficient_stock: fewer units are available than requested; amount_out_of_range: the "
        "line would take the cart above the largest amount an order can hold (an extreme price). "
        "Only available lines count in the totals."
    )
    unit_price: int | None = Field(
        description="Whole RWF from the catalogue; null unless available"
    )
    line_subtotal: int | None = Field(description="unit_price x quantity; null unless available")
    discount_amount: int | None = Field(
        default=None,
        description="This line's share of the promotion discount (whole RWF): 0 when no code "
        "applies to it; null unless available",
    )
    previous_unit_price: int | None = Field(
        default=None,
        description="The price when the line was added (or topped up, or accepted), when it "
        "differs from unit_price; null otherwise. Display only: totals use unit_price. "
        "POST /cart/accept-prices clears it.",
    )
    image: PublicImage | None = Field(
        default=None, description="The variant's first image, else the product's; null if none"
    )
    store: StoreReference = Field(
        description='The store that sells the line ("Sold by", ADR-014 phase 5). Shown for '
        "every line; a line of a store that is no longer approved is unavailable."
    )


class CartDelivery(BaseModel):
    """The delivery quote for the zone asked for (module 12; RE-026 B1)."""

    zone_code: str
    zone_name: str
    district: str
    cod_available: bool
    zone_fee: int = Field(description="The zone's current fee, whole RWF, VAT-inclusive")
    delivery_fee: int = Field(description="What delivery costs this cart: 0 when free")
    free_delivery: bool = Field(
        description="True when subtotal_after_discount is at least free_delivery_threshold"
    )
    free_delivery_threshold: int


DiscountReason = Literal[
    "not_active",
    "not_started",
    "expired",
    "no_eligible_items",
    "minimum_not_met",
    "usage_limit_reached",
    "customer_limit_reached",
]


class CartDiscount(BaseModel):
    """The promotion code on the cart (module 13; RE-026 B3), re-checked on every read."""

    code: str
    name: str
    kind: Literal["percent", "fixed"]
    percent_off: int | None
    amount_off: int | None
    applied: bool = Field(description="False when the code does not apply right now (see reason)")
    reason: DiscountReason | None = Field(
        description="Why the code does not apply; null if it does"
    )
    amount: int = Field(
        description="The discount on eligible merchandise, whole RWF; 0 if not applied"
    )


class CartResponse(BaseModel):
    id: uuid.UUID | None = Field(description="Null while no cart exists yet")
    owner: Literal["customer", "guest"]
    expires_at: datetime | None = Field(
        description="Guest carts: 30 days after the last change; customer carts: null"
    )
    lines: list[CartLine]
    item_count: int = Field(description="Units on available lines")
    merchandise_subtotal: int = Field(
        description="Whole RWF, VAT-inclusive, of the available lines only (pricing service)"
    )
    currency_code: str = "RWF"
    has_unavailable_lines: bool
    has_price_changes: bool = Field(
        default=False, description="Some available line has a previous_unit_price"
    )
    discount: CartDiscount | None = Field(
        default=None, description="The promotion code on the cart, if any (module 13)"
    )
    discount_total: int = Field(
        default=0, description="The promotion discount (whole RWF); never applied to delivery"
    )
    subtotal_after_discount: int = Field(
        default=0,
        description="merchandise_subtotal - discount_total: the basis of the free-delivery "
        "threshold (RE-026 B1)",
    )
    delivery: CartDelivery | None = Field(
        default=None, description="Only when `zone` is given: the delivery quote"
    )
    grand_total: int | None = Field(
        default=None,
        description="Only when `zone` is given: subtotal_after_discount + "
        "delivery.delivery_fee, whole RWF, VAT-inclusive.",
    )
    cart_token: str | None = Field(
        default=None,
        description="Only in the response that created a guest cart: send it back in "
        "X-Cart-Token. It is shown once and cannot be retrieved again.",
    )


MergeOutcome = Literal["merged", "capped", "excluded"]


class MergeLine(BaseModel):
    variant_id: uuid.UUID
    sku: str
    guest_quantity: int = Field(description="Units on the guest cart's line")
    added_quantity: int = Field(description="Units added to the customer's cart")
    outcome: MergeOutcome = Field(
        description="merged: all units added; capped: fewer added (99-unit line limit or "
        "available stock); excluded: nothing added"
    )
    reason: Literal["line_limit", "insufficient_stock", "unavailable"] | None


class CartMergeResponse(BaseModel):
    cart: CartResponse
    merged_lines: list[MergeLine]
