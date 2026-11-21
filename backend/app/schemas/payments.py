"""Payment schemas (module 15; plan §5 "15 — payments"; §7 Q17, Q21)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.identifiers import PHONE_INPUT_MAX_LENGTH, validate_rwanda_phone
from app.schemas.order import OrderStatus, PaymentMethod, PaymentStatus
from app.schemas.pagination import Page

ProcessingStatus = Literal["pending", "processed", "duplicate", "needs_reconciliation", "rejected"]


class PaymentAccessRequest(BaseModel):
    """Guests prove access with the order's phone (order number + phone, §7 Q17); signed-in
    customers send nothing (the order must be theirs)."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"phone": "0788123456"}]}
    )

    phone: str | None = Field(default=None, max_length=PHONE_INPUT_MAX_LENGTH)

    @field_validator("phone")
    @classmethod
    def canonical_phone(cls, value: str | None) -> str | None:
        return validate_rwanda_phone(value) if value is not None else None


class PaymentMethodChangeRequest(PaymentAccessRequest):
    """Switch an unpaid order's payment method (frontend phase 4, 2026-10-27). Guests add the
    order's phone, as for initiate."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"payment_method": "cash_on_delivery"},
                {"payment_method": "airtel_money", "phone": "0788123456"},
            ]
        },
    )

    payment_method: PaymentMethod = Field(
        description="mtn_momo, airtel_money, or cash_on_delivery where the order's delivery zone "
        "allows it; never card"
    )


class PaymentStatusResponse(BaseModel):
    order_number: str
    order_status: OrderStatus
    method: PaymentMethod
    status: PaymentStatus = Field(
        description="created: not started; pending: started (mobile money) or due on delivery "
        "(cash on delivery); succeeded: paid; failed / cancelled: not paid (a new attempt may "
        "be started while the stock hold lasts); expired: the hold lapsed"
    )
    amount: int = Field(description="Whole RWF: the order total")
    currency_code: str
    provider: str | None = Field(description="mock (test stand-in, §7 Q21) or cod")
    reference: str | None = Field(description="The provider's reference, once started")
    instructions: str | None = None
    reservation_expires_at: datetime | None = Field(
        description="When the stock hold lapses unless the order is paid or confirmed"
    )


class WebhookAck(BaseModel):
    received: bool = True
    status: ProcessingStatus = Field(
        description="processed, duplicate (already received; nothing repeated) or "
        "needs_reconciliation (recorded for finance; nothing applied)"
    )


class StaffPaymentItem(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    method: PaymentMethod
    provider: str | None
    provider_reference: str | None
    status: PaymentStatus
    amount: int
    currency_code: str
    created_at: datetime
    succeeded_at: datetime | None
    needs_reconciliation: bool = Field(description="An event of this attempt needs review")


class StaffPaymentPage(Page[StaffPaymentItem]):
    """The staff payment list, with the summed amount of every attempt matching the filters."""

    amount_total: int = Field(
        ge=0, description="Sum of `amount` over all matching attempts (every page), whole RWF"
    )


class StaffPaymentEventItem(BaseModel):
    id: uuid.UUID
    attempt_id: uuid.UUID | None
    provider: str
    event_key: str
    verification_status: str
    processing_status: ProcessingStatus
    received_at: datetime
    processed_at: datetime | None
    result_summary: str | None
    payload_metadata: dict[str, Any] = Field(description="Sanitised: masked phone, no card data")
