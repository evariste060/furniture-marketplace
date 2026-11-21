"""Store and seller application schemas (ADR-014 phase 1).

Text is plain text: control and other non-printable characters are removed and the ends
trimmed; the description keeps its line breaks. Blank optional fields become null. The phone is a
Rwandan mobile number in any accepted form, stored canonical (+2507XXXXXXXX); the contact email
is stored in lower case. Requests forbid unknown fields, so a seller can never send owner_user_id,
status, slug or a commission (422).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.identifiers import validate_email_format, validate_rwanda_phone
from app.models.marketplace import (
    COMMISSION_BPS_MAX,
    STORE_DESCRIPTION_MAX_LENGTH,
    STORE_DISTRICT_MAX_LENGTH,
    STORE_EMAIL_MAX_LENGTH,
    STORE_NAME_MAX_LENGTH,
    STORE_NAME_MIN_LENGTH,
    STORE_REASON_MAX_LENGTH,
    STORE_REASON_MIN_LENGTH,
    STORE_SECTOR_MAX_LENGTH,
    STORE_STREET_MAX_LENGTH,
)
from app.schemas.banners import plain_text
from app.schemas.images import PublicImage
from app.schemas.reviews import _blank_to_none, _paragraphs

StoreStatus = Literal["pending", "approved", "rejected", "suspended"]
StoreDecision = Literal["approved", "rejected", "suspended"]
REASON_REQUIRED = "Give a reason of at least 10 characters when rejecting or suspending a store."


def _email(value: str) -> str:
    return validate_email_format(value)


def _phone(value: str) -> str:
    return validate_rwanda_phone(value)


StoreName = Annotated[
    str,
    BeforeValidator(plain_text),
    StringConstraints(min_length=STORE_NAME_MIN_LENGTH, max_length=STORE_NAME_MAX_LENGTH),
]
District = Annotated[
    str,
    BeforeValidator(plain_text),
    StringConstraints(min_length=2, max_length=STORE_DISTRICT_MAX_LENGTH),
]
ContactEmail = Annotated[
    str,
    BeforeValidator(plain_text),
    StringConstraints(min_length=3, max_length=STORE_EMAIL_MAX_LENGTH),
    AfterValidator(_email),
]
ContactPhone = Annotated[str, BeforeValidator(plain_text), AfterValidator(_phone)]
Description = Annotated[
    Annotated[str, StringConstraints(max_length=STORE_DESCRIPTION_MAX_LENGTH)] | None,
    BeforeValidator(_paragraphs),
]
Sector = Annotated[
    Annotated[str, StringConstraints(max_length=STORE_SECTOR_MAX_LENGTH)] | None,
    BeforeValidator(_blank_to_none),
]
Street = Annotated[
    Annotated[str, StringConstraints(max_length=STORE_STREET_MAX_LENGTH)] | None,
    BeforeValidator(_blank_to_none),
]
Reason = Annotated[
    Annotated[
        str,
        StringConstraints(min_length=STORE_REASON_MIN_LENGTH, max_length=STORE_REASON_MAX_LENGTH),
    ]
    | None,
    BeforeValidator(_blank_to_none),
]
APPLICATION_EXAMPLE: dict[str, Any] = {
    "name": "Kigali Oak Works",
    "description": "Hand-made solid wood tables and chairs.",
    "contact_email": "sales@oakworks.example.rw",
    "contact_phone": "0788 123 456",
    "district": "Gasabo",
    "sector": "Kimironko",
    "street_address": "KG 11 Ave",
}


class StoreApplicationRequest(BaseModel):
    """A seller application, and its edit or resubmission (PUT sends every field again)."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [APPLICATION_EXAMPLE]})

    name: StoreName
    description: Description = None
    contact_email: ContactEmail
    contact_phone: ContactPhone
    district: District
    sector: Sector = None
    street_address: Street = None


class StoreProfileUpdate(BaseModel):
    """Partial update of an approved store. name, contact_email, contact_phone and district
    cannot be cleared; description, sector and street_address accept null."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"description": "Solid wood only."}]}
    )

    name: StoreName | None = None
    description: Description = None
    contact_email: ContactEmail | None = None
    contact_phone: ContactPhone | None = None
    district: District | None = None
    sector: Sector = None
    street_address: Street = None

    @model_validator(mode="after")
    def check_fields(self) -> "StoreProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        required = ("name", "contact_email", "contact_phone", "district")
        nulls = [f for f in required if f in self.model_fields_set and getattr(self, f) is None]
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null.")
        return self


class StoreStatusRequest(BaseModel):
    """An administrator decision. A reason (10-500 characters) is required to reject or suspend
    and is shown to the seller; it is optional when approving or reinstating and then kept in the
    history only."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"status": "approved"},
                {"status": "rejected", "reason": "Please add your shop's street address."},
            ]
        },
    )

    status: StoreDecision
    reason: Reason = None

    @model_validator(mode="after")
    def check_reason(self) -> "StoreStatusRequest":
        if self.status in ("rejected", "suspended") and self.reason is None:
            raise ValueError(REASON_REQUIRED)
        return self


class StoreCommissionRequest(BaseModel):
    """A store's own commission in whole basis points (1000 = 10%), or null to inherit the
    platform default."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"commission_rate_bps": 750}]}
    )

    commission_rate_bps: int | None = Field(strict=True, ge=0, le=COMMISSION_BPS_MAX)


class SellerStoreResponse(BaseModel):
    """The caller's own store or application. Never carries another store's data, the owner's
    account details, the commission override or the review history."""

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    contact_email: str
    contact_phone: str
    district: str
    sector: str | None
    street_address: str | None
    logo: PublicImage | None
    cover: PublicImage | None
    status: StoreStatus
    status_reason: str | None = Field(description="Why it is rejected or suspended, else null")
    submitted_at: datetime
    reviewed_at: datetime | None
    approved_at: datetime | None
    effective_commission_rate_bps: int = Field(
        description="The commission that applies to this store, in basis points (read-only)"
    )


class StaffPerson(BaseModel):
    id: uuid.UUID
    full_name: str | None


class StaffStoreOwner(StaffPerson):
    email: str | None
    phone: str | None


class StaffStoreSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: StoreStatus
    district: str
    submitted_at: datetime
    reviewed_at: datetime | None
    owner: StaffStoreOwner


class StoreHistoryEntry(BaseModel):
    status: StoreStatus
    reason: str | None
    store_name: str
    actor: StaffPerson | None
    created_at: datetime


class StaffStoreDetail(StaffStoreSummary):
    description: str | None
    contact_email: str
    contact_phone: str
    sector: str | None
    street_address: str | None
    logo: PublicImage | None
    cover: PublicImage | None
    status_reason: str | None
    approved_at: datetime | None
    reviewed_by: StaffPerson | None
    commission_rate_bps: int | None = Field(description="The store's override; null inherits")
    effective_commission_rate_bps: int
    history: list[StoreHistoryEntry]
