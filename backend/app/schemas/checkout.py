"""Checkout schemas (module 14; plan §5 "14 — orders & checkout"; RE-026).

A checkout request names only who the order is for, where it goes and how it will be paid:
the cart supplies the lines, and every price, discount, delivery fee, VAT amount and total is
computed on the server. Any other field (a price, a total, a discount) is refused (422).
"""

import hashlib
import json
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.identifiers import (
    EMAIL_MAX_LENGTH,
    PHONE_INPUT_MAX_LENGTH,
    validate_email_format,
    validate_rwanda_phone,
)
from app.schemas.order import OrderDetailResponse, PaymentMethod

Text120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class CheckoutAddress(BaseModel):
    """An address typed at checkout (the same fields and limits as a saved address)."""

    model_config = ConfigDict(extra="forbid")

    recipient_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=180)
    ]
    phone: str = Field(max_length=PHONE_INPUT_MAX_LENGTH, description="Rwandan mobile number")
    province: Text120 | None = None
    district: Text120 = Field(description="Gasabo, Kicukiro or Nyarugenge (delivery area)")
    sector: Text120 | None = None
    cell: Text120 | None = None
    village: Text120 | None = None
    street_address: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=240)
    ]
    delivery_instructions: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=500)
    ] = None

    @field_validator("phone")
    @classmethod
    def canonical_phone(cls, value: str) -> str:
        return validate_rwanda_phone(value)


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "address": {
                        "recipient_name": "Aline Uwase",
                        "phone": "0788123456",
                        "district": "Gasabo",
                        "street_address": "KG 11 Ave, house 4",
                    },
                    "payment_method": "cash_on_delivery",
                    "email": "aline@example.rw",
                }
            ]
        },
    )

    address_id: UUID | None = Field(
        default=None, description="Signed-in customers: one of their saved addresses"
    )
    address: CheckoutAddress | None = Field(
        default=None, description="An address typed at checkout (required for guests)"
    )
    payment_method: PaymentMethod = Field(
        description="Chosen at checkout (§7 Q15); must be one of the zone's available methods"
    )
    email: str | None = Field(
        default=None,
        max_length=EMAIL_MAX_LENGTH,
        description="Guests: optional contact email. Customers: the account email is used.",
    )
    note: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=1000)] = None

    @field_validator("email")
    @classmethod
    def email_format(cls, value: str | None) -> str | None:
        return validate_email_format(value) if value is not None else None

    @model_validator(mode="after")
    def one_address(self) -> "CheckoutRequest":
        if (self.address_id is None) == (self.address is None):
            raise ValueError("Send exactly one of address_id or address.")
        return self

    def fingerprint(self) -> str:
        """SHA-256 of the normalised request: the same request always gives the same value."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf8")).hexdigest()


class CheckoutResponse(BaseModel):
    order: OrderDetailResponse
    payment_methods_available: list[PaymentMethod] = Field(
        description="The methods offered for the delivery zone (§7 Q15, Q21)"
    )
    reservation_expires_at: datetime | None = Field(
        description="When the stock hold lapses unless the order is paid (mobile money, 15 "
        "minutes) or confirmed by staff (cash on delivery, 24 hours); §7 Q11, Q13"
    )
    replayed: bool = Field(
        description="True when this Idempotency-Key already placed the order: nothing new "
        "was created or reserved"
    )
