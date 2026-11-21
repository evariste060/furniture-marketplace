"""Saved-address API schemas, mapped to the upstream `addresses` table (commerce schema).

Field limits mirror the column sizes so validation fails with 422 before any database error.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.identifiers import PHONE_INPUT_MAX_LENGTH, validate_rwanda_phone


def _phone(v: str | None) -> str | None:
    return validate_rwanda_phone(v) if v is not None else None


class AddressCreateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=80, description="e.g. Home, Office")
    recipient_name: str = Field(..., min_length=2, max_length=180, description="Recipient name")
    phone: str = Field(
        ...,
        max_length=PHONE_INPUT_MAX_LENGTH,
        description="Rwandan mobile number for delivery (stored as +2507XXXXXXXX)",
    )
    province: str | None = Field(default=None, max_length=120, description="Province")
    district: str = Field(..., min_length=2, max_length=120, description="District, e.g. Gasabo")
    sector: str | None = Field(default=None, max_length=120, description="Sector")
    cell: str | None = Field(default=None, max_length=120, description="Cell")
    village: str | None = Field(default=None, max_length=120, description="Village")
    street_address: str = Field(
        ..., min_length=3, max_length=240, description="Street, house number or landmark"
    )
    delivery_instructions: str | None = Field(
        default=None, max_length=500, description="Delivery guidance / instructions"
    )
    is_default: bool = Field(
        default=False,
        description="Make this the default address. A customer's first address always "
        "becomes the default.",
    )

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        return _phone(v)


class AddressUpdateRequest(BaseModel):
    """Partial update: only fields present in the body change."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, max_length=80)
    recipient_name: str | None = Field(default=None, min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=PHONE_INPUT_MAX_LENGTH)
    province: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, min_length=2, max_length=120)
    sector: str | None = Field(default=None, max_length=120)
    cell: str | None = Field(default=None, max_length=120)
    village: str | None = Field(default=None, max_length=120)
    street_address: str | None = Field(default=None, min_length=3, max_length=240)
    delivery_instructions: str | None = Field(default=None, max_length=500)
    is_default: bool | None = Field(
        default=None,
        description="true makes this the default. false is rejected for the current default: "
        "a customer with addresses always has exactly one default, so set another address "
        "as default instead.",
    )

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        return _phone(v)


class AddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    label: str | None = None
    recipient_name: str
    phone: str
    country_code: str
    province: str | None = None
    district: str | None = None
    sector: str | None = None
    cell: str | None = None
    village: str | None = None
    street_address: str | None = None
    delivery_instructions: str | None = None
    is_default: bool
    created_at: datetime
    updated_at: datetime
