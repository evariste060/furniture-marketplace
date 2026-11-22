"""Seller order schemas (ADR-014 phase 3).

A seller sees only their own store's part of an order and only the customer data its delivery
needs: the recipient's name and phone and the delivery address. Never the customer's email or
account, another store's lines, the order total, the delivery fee or the discount code.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.order import OrderStatus, PaymentMethod, PaymentStatus, SellerOrderStatus

SellerOrderMove = Literal["confirmed", "processing", "dispatched", "delivered"]


class SellerOrderStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SellerOrderMove = Field(
        description="The next step of your order: confirmed, processing, dispatched, delivered"
    )
    reason: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
        Field(description="Optional; kept in the history and the audit record"),
    ] = None


class SellerOrderLine(BaseModel):
    sku: str
    product_name: str
    variant_name: str | None
    quantity: int
    unit_price: int = Field(description="Whole RWF, VAT-inclusive, at checkout")
    line_subtotal: int
    discount_amount: int = Field(description="This line's share of the order discount")
    line_total: int


class SellerOrderHistoryEntry(BaseModel):
    status: SellerOrderStatus
    reason: str | None
    created_at: datetime


class SellerDeliveryAddress(BaseModel):
    province: str | None = None
    district: str | None = None
    sector: str | None = None
    cell: str | None = None
    village: str | None = None
    street_address: str | None = None
    delivery_instructions: str | None = None
    country_code: str | None = None


class SellerOrderMoney(BaseModel):
    subtotal: int
    discount_total: int = Field(description="Your share of the order discount")
    merchandise_total: int = Field(description="subtotal - discount_total; the commission base")
    commission_rate_bps: int = Field(description="Snapshot at checkout, in basis points")
    commission_amount: int
    seller_net_amount: int = Field(description="merchandise_total - commission_amount")


class SellerOrderSummary(SellerOrderMoney):
    id: UUID
    order_number: str
    status: SellerOrderStatus
    order_status: OrderStatus = Field(description="The whole order's status")
    payment_method: PaymentMethod | None
    payment_status: PaymentStatus | None
    units: int
    recipient_name: str
    created_at: datetime


class SellerOrderDetail(SellerOrderSummary):
    updated_at: datetime
    recipient_phone: str
    delivery_zone: str | None
    delivery_address: SellerDeliveryAddress
    lines: list[SellerOrderLine]
    status_history: list[SellerOrderHistoryEntry]


class EarningsBucket(BaseModel):
    orders: int
    merchandise_total: int
    commission_amount: int
    seller_net_amount: int


class SellerEarningsResponse(BaseModel):
    """Computed from seller orders; payouts are not built, so `earned` is owed by the
    platform, not paid."""

    store_id: UUID
    currency_code: Literal["RWF"] = "RWF"
    pending: EarningsBucket = Field(
        description="Seller orders confirmed and not yet earned (not delivered and paid)"
    )
    earned: EarningsBucket = Field(
        description="Delivered seller orders whose order payment succeeded"
    )
