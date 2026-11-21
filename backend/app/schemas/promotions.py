"""Promotion schemas (module 13; plan §5; RE-026 B3, B6; ADR-007).

Codes are case-insensitive: they are trimmed and upper-cased on input and stored upper-case.
Amounts are whole RWF integers (strict: strings, floats and booleans are refused). Start and end
date-times without an offset are Africa/Kigali local time (app.core.kigali_time); responses show
them in Kigali time, with their +02:00 offset. Any field not listed is refused (422).
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.kigali_time import local_to_utc
from app.models.common import MAX_MONEY_RWF

CODE_MAX_LENGTH = 40
CODE_PATTERN = r"^[A-Z0-9][A-Z0-9_-]*$"  # after upper-casing; as the discounts check
MAX_TARGETS = 100

Kind = Literal["percent", "fixed"]
AppliesTo = Literal["all", "targets"]
PromotionStatus = Literal["draft", "active", "disabled"]


def _normalise_code(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


PromotionCode = Annotated[
    str,
    BeforeValidator(_normalise_code),
    StringConstraints(min_length=3, max_length=CODE_MAX_LENGTH, pattern=CODE_PATTERN),
    Field(description="Letters, digits, '-' or '_'; case-insensitive (stored upper-case)"),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Percent = Annotated[int, Field(strict=True, ge=1, le=100, description="Whole percent")]
Amount = Annotated[int, Field(strict=True, ge=1, le=MAX_MONEY_RWF, description="Whole RWF")]
MinSubtotal = Annotated[int, Field(strict=True, ge=0, le=MAX_MONEY_RWF, description="Whole RWF")]
UsageLimit = Annotated[int, Field(strict=True, ge=1, le=2**31 - 1)]
LOCAL_TIME = (
    "Africa/Kigali local time when sent without an offset (e.g. 2026-11-01T00:00:00); "
    "stored in UTC. Starts at this instant, inclusive."
)


class PromotionTarget(BaseModel):
    """Exactly one of category_id (which includes its subcategories), brand_id, product_id."""

    model_config = ConfigDict(extra="forbid")

    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> "PromotionTarget":
        if sum(v is not None for v in (self.category_id, self.brand_id, self.product_id)) != 1:
            raise ValueError("A target names exactly one of category_id, brand_id, product_id.")
        return self

    def key(self) -> tuple[str, uuid.UUID]:
        for field in ("category_id", "brand_id", "product_id"):
            value = getattr(self, field)
            if value is not None:
                return field, value
        raise AssertionError("unreachable")  # pragma: no cover


def _utc(value: datetime | None) -> datetime | None:
    return local_to_utc(value) if value is not None else None


def _check_targets(targets: list[PromotionTarget]) -> list[PromotionTarget]:
    keys = [target.key() for target in targets]
    if len(set(keys)) != len(keys):
        raise ValueError("A target is listed more than once.")
    return targets


class PromotionCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "code": "WELCOME10",
                    "name": "Welcome 10%",
                    "kind": "percent",
                    "percent_off": 10,
                    "applies_to": "all",
                    "status": "draft",
                    "starts_at": "2026-11-01T00:00:00",
                    "ends_at": "2026-12-01T00:00:00",
                }
            ]
        },
    )

    code: PromotionCode
    name: Name
    kind: Kind
    percent_off: Percent | None = Field(default=None, description="Only for kind 'percent'")
    amount_off: Amount | None = Field(default=None, description="Only for kind 'fixed'")
    applies_to: AppliesTo = "all"
    targets: list[PromotionTarget] = Field(
        default_factory=list, max_length=MAX_TARGETS, description="Required for 'targets'"
    )
    status: PromotionStatus = "draft"
    starts_at: datetime | None = Field(default=None, description=LOCAL_TIME)
    ends_at: datetime | None = Field(
        default=None, description="Same format; the code stops working at this instant"
    )
    min_subtotal: MinSubtotal = Field(
        default=0,
        description="Smallest merchandise subtotal of the whole cart or order, before discount "
        "and without delivery (whole RWF), whatever the targets",
    )
    max_discount: Amount | None = Field(default=None, description="Caps the discount (whole RWF)")
    usage_limit_total: UsageLimit | None = None
    usage_limit_per_customer: UsageLimit | None = None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def as_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value)

    @field_validator("targets")
    @classmethod
    def unique_targets(cls, value: list[PromotionTarget]) -> list[PromotionTarget]:
        return _check_targets(value)

    @model_validator(mode="after")
    def check_rules(self) -> "PromotionCreateRequest":
        problem = consistency_problem(
            self.kind,
            self.percent_off,
            self.amount_off,
            self.applies_to,
            len(self.targets),
            self.starts_at,
            self.ends_at,
        )
        if problem:
            raise ValueError(problem)
        return self


class PromotionUpdateRequest(BaseModel):
    """Partial update. `targets`, when sent, replaces every target. The result must still be
    consistent (checked against the stored promotion): for example, a change of kind needs the
    matching percent_off or amount_off. Nullable fields (percent_off, amount_off, starts_at,
    ends_at, max_discount and the usage limits) accept null to clear them."""

    model_config = ConfigDict(extra="forbid")

    code: PromotionCode | None = None
    name: Name | None = None
    kind: Kind | None = None
    percent_off: Percent | None = None
    amount_off: Amount | None = None
    applies_to: AppliesTo | None = None
    targets: list[PromotionTarget] | None = Field(default=None, max_length=MAX_TARGETS)
    status: PromotionStatus | None = None
    starts_at: datetime | None = Field(default=None, description=LOCAL_TIME)
    ends_at: datetime | None = None
    min_subtotal: MinSubtotal | None = None
    max_discount: Amount | None = None
    usage_limit_total: UsageLimit | None = None
    usage_limit_per_customer: UsageLimit | None = None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def as_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value)

    @field_validator("targets")
    @classmethod
    def unique_targets(cls, value: list[PromotionTarget] | None) -> list[PromotionTarget] | None:
        return _check_targets(value) if value is not None else None

    @model_validator(mode="after")
    def check_fields(self) -> "PromotionUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        required = ("code", "name", "kind", "applies_to", "targets", "status", "min_subtotal")
        nulls = [f for f in required if f in self.model_fields_set and getattr(self, f) is None]
        if nulls:
            raise ValueError(f"These fields cannot be null: {', '.join(nulls)}.")
        return self


def consistency_problem(
    kind: str,
    percent_off: int | None,
    amount_off: int | None,
    applies_to: str,
    target_count: int,
    starts_at: datetime | None,
    ends_at: datetime | None,
) -> str | None:
    """Why a complete promotion is inconsistent, or None. Shared by create and update."""
    if kind == "percent" and (percent_off is None or amount_off is not None):
        return "A 'percent' promotion needs percent_off and no amount_off."
    if kind == "fixed" and (amount_off is None or percent_off is not None):
        return "A 'fixed' promotion needs amount_off and no percent_off."
    if applies_to == "targets" and target_count == 0:
        return "A promotion that applies to 'targets' needs at least one target."
    if applies_to == "all" and target_count:
        return "A promotion that applies to 'all' takes no targets."
    if starts_at is not None and ends_at is not None and ends_at <= starts_at:
        return "ends_at must be after starts_at."
    return None


class PromotionTargetResponse(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    brand_id: uuid.UUID | None
    product_id: uuid.UUID | None


class PromotionResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: Kind
    percent_off: int | None
    amount_off: int | None
    applies_to: AppliesTo
    targets: list[PromotionTargetResponse]
    status: PromotionStatus
    starts_at: datetime | None = Field(description="Africa/Kigali time (+02:00)")
    ends_at: datetime | None = Field(description="Africa/Kigali time (+02:00)")
    min_subtotal: int
    max_discount: int | None
    usage_limit_total: int | None
    usage_limit_per_customer: int | None
    active_redemptions: int = Field(description="Uses counted towards the limits (active only)")
    created_at: datetime
    updated_at: datetime


class ApplyCodeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"code": "welcome10"}]}
    )

    code: Annotated[
        str,
        BeforeValidator(_normalise_code),
        StringConstraints(min_length=1, max_length=CODE_MAX_LENGTH),
        Field(description="The promotion code, in any letter case"),
    ]
