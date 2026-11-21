"""Delivery zone schemas (module 12; plan §5, RE-026 B1, B5, B6).

Requests never carry a zone's current fee history or timestamps: the server keeps them. A zone's
code and district cannot be changed after creation (D-D2); any field not listed is refused (422).
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.slugs import SLUG_PATTERN
from app.models.common import MAX_MONEY_RWF
from app.schemas.catalog_admin import SortOrder

District = Literal["Gasabo", "Kicukiro", "Nyarugenge"]  # RE-026 B1; delivery_zones check
ZONE_CODE_MAX_LENGTH = 60  # delivery_zones.code
ZONE_NAME_MAX_LENGTH = 160  # delivery_zones.name

ZoneCode = Annotated[
    str,
    Field(
        min_length=1,
        max_length=ZONE_CODE_MAX_LENGTH,
        pattern=SLUG_PATTERN,
        description="Lowercase ASCII letters and digits, words joined by single hyphens",
    ),
]
ZoneName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=ZONE_NAME_MAX_LENGTH)
]
Fee = Annotated[
    int,
    Field(strict=True, ge=0, le=MAX_MONEY_RWF, description="Whole RWF, VAT-inclusive (B1)"),
]


class DeliveryZoneCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "code": "kicukiro",
                    "name": "Kicukiro",
                    "district": "Kicukiro",
                    "fee": 2000,
                    "cod_available": True,
                    "sort_order": 2,
                }
            ]
        },
    )

    code: ZoneCode
    name: ZoneName
    district: District = Field(description="One zone per district")
    fee: Fee
    cod_available: bool = True
    sort_order: SortOrder = 0
    is_active: bool = True


class DeliveryZoneUpdateRequest(BaseModel):
    """Partial update. A new fee closes the current fee rule and starts a new one, so the
    history is kept; sending the current fee changes nothing."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"fee": 2500}, {"is_active": False}]}
    )

    name: ZoneName | None = None
    fee: Fee | None = None
    cod_available: bool | None = None
    sort_order: SortOrder | None = None
    is_active: bool | None = Field(default=None, description="false hides the zone from customers")

    @model_validator(mode="after")
    def check_fields(self) -> "DeliveryZoneUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        nulls = [f for f in self.model_fields_set if getattr(self, f) is None]
        if nulls:
            raise ValueError(f"These fields cannot be null: {', '.join(sorted(nulls))}.")
        return self


class PublicDeliveryZone(BaseModel):
    code: str
    name: str
    district: District
    fee: int = Field(description="Whole RWF, VAT-inclusive; waived at the free-delivery threshold")
    cod_available: bool = Field(description="Cash on delivery can be chosen in this zone")


class PublicDeliveryZonesResponse(BaseModel):
    items: list[PublicDeliveryZone] = Field(
        description="Active zones with a current fee, in display order"
    )
    free_delivery_threshold: int | None = Field(
        description="Delivery is free when the merchandise subtotal after discount is at least "
        "this amount (whole RWF). Null while it is not configured: no delivery can be quoted."
    )
    currency_code: str = "RWF"


class FeeRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fee: int
    currency_code: str
    is_active: bool = Field(description="True for the current fee; false for closed rules")
    starts_at: datetime | None
    ends_at: datetime | None = Field(description="Set when a later fee replaced this one")
    created_at: datetime


class StaffDeliveryZone(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    district: District
    cod_available: bool
    sort_order: int
    is_active: bool
    fee: int | None = Field(description="The current fee; null if the zone has none")
    fee_history: list[FeeRuleResponse] = Field(description="Every fee rule, newest first")
    created_at: datetime
    updated_at: datetime


class StaffDeliveryZonesResponse(BaseModel):
    items: list[StaffDeliveryZone] = Field(
        description="Every zone, active or not, in display order (at most one per district, so "
        "the list is not paginated)"
    )
