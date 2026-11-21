from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.identifiers import PHONE_INPUT_MAX_LENGTH, validate_rwanda_phone
from app.schemas.images import PublicImage

OrderStatus = Literal["received", "confirmed", "processing", "dispatched", "delivered", "cancelled"]


PaymentMethod = Literal["mtn_momo", "airtel_money", "card", "cash_on_delivery"]
PaymentStatus = Literal[
    "created",
    "pending",
    "succeeded",
    "failed",
    "cancelled",
    "expired",
    "refunded",
    "partially_refunded",
]


class OrderStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OrderStatus
    reason: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
        Field(description="Optional; kept in the status history and the audit record"),
    ] = None


class OrderAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    staff_user_id: UUID = Field(description="Active staff user receiving fulfilment assignment")


class OrderFulfilmentResponse(BaseModel):
    id: UUID
    order_number: str
    status: OrderStatus
    fulfilment_assignee_user_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CustomerOrderStatusResponse(BaseModel):
    id: UUID
    order_number: str
    status: OrderStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderLineResponse(BaseModel):
    """One ordered line, as snapshotted at checkout (never re-read from the catalogue)."""

    id: UUID = Field(description="The order item; reviews are requested per item")
    sku: str
    product_name: str
    variant_name: str | None
    quantity: int
    unit_price: int = Field(description="Whole RWF, VAT-inclusive, at checkout")
    line_subtotal: int
    discount_amount: int = Field(description="This line's share of the order discount")
    line_total: int = Field(description="line_subtotal - discount_amount")
    image: PublicImage | None = Field(
        default=None,
        description="The variant's current first image, else the product's; null if none "
        "(display only, not a snapshot)",
    )
    product_slug: str | None = Field(
        default=None, description="The product's page, while the product is public; else null"
    )
    reviewed: bool = Field(default=False, description="A review was sent for this item")


class OrderPaymentResponse(BaseModel):
    method: PaymentMethod
    status: PaymentStatus = Field(
        description="created: not started; pending: due (cash on delivery: due on delivery); "
        "succeeded: paid"
    )
    amount: int
    created_at: datetime


class OrderHistoryEntry(BaseModel):
    status: OrderStatus
    reason: str | None
    created_at: datetime


class OrderDetailResponse(BaseModel):
    """An order with its lines, totals (whole RWF), delivery and payment, as snapshotted at
    checkout. Amounts are VAT-inclusive; tax_total is the VAT extracted from total (ADR-007)."""

    id: UUID
    order_number: str
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    currency_code: str
    subtotal: int = Field(description="Merchandise subtotal before discount")
    discount_total: int
    delivery_fee: int
    tax_total: int = Field(description="VAT included in total (18%, extracted; ADR-007)")
    total: int = Field(description="subtotal - discount_total + delivery_fee")
    tax_treatment: str | None = Field(description="vat_inclusive for checkout orders")
    discount_code: str | None
    delivery_zone: str | None
    recipient_name: str
    recipient_phone: str
    delivery_address: dict[str, Any]
    lines: list[OrderLineResponse]
    payment: OrderPaymentResponse | None = Field(description="The latest payment attempt")
    status_history: list[OrderHistoryEntry]


class StaffPaymentResponse(OrderPaymentResponse):
    provider: str | None
    succeeded_at: datetime | None


class StaffOrderDetailResponse(OrderDetailResponse):
    user_id: UUID | None = Field(description="Null for guest orders")
    customer_email: str | None
    customer_note: str | None
    fulfilment_assignee_user_id: UUID | None
    fulfilment_assignee_name: str | None = Field(
        default=None, description="The assignee's name, when assigned"
    )
    payments: list[StaffPaymentResponse] = Field(description="Every payment attempt, oldest first")


class OrderSummaryResponse(BaseModel):
    id: UUID
    order_number: str
    status: OrderStatus
    total: int
    item_count: int = Field(description="Units ordered")
    payment_method: PaymentMethod | None
    payment_status: PaymentStatus | None
    created_at: datetime


class OrderAssignee(BaseModel):
    id: UUID
    full_name: str | None
    role: str


class OrderAssigneesResponse(BaseModel):
    items: list[OrderAssignee] = Field(description="Active staff, by name")


class StaffOrderSummaryResponse(OrderSummaryResponse):
    """A staff order row: the summary plus who the order is for (frontend phase 6)."""

    customer_name: str = Field(description="The recipient's name, as entered at checkout")
    customer_phone: str = Field(description="The order's phone, +2507XXXXXXXX")


class OrderLookupRequest(BaseModel):
    """A guest looks up an order with its number and the order's phone (RE-026 B7)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"order_number": "ORD-261025-7KQ2MX", "phone": "0788123456"}]
        },
    )

    order_number: Annotated[
        str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=40)
    ]
    phone: str = Field(max_length=PHONE_INPUT_MAX_LENGTH, description="Any accepted format")

    @field_validator("phone")
    @classmethod
    def canonical_phone(cls, value: str) -> str:
        return validate_rwanda_phone(value)
