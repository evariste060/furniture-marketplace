"""Staff inventory API schemas (ADR-002 stock lifecycle, approved 2026-10-22)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.inventory import MAX_QUANTITY

AdjustmentReason = Literal["receipt", "adjustment", "inspected_return"]
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9_.:-]{8,100}$"


class InventoryResponse(BaseModel):
    sku: str
    variant_id: uuid.UUID
    is_sellable: bool = Field(
        description="Variant active, product active, category active and brand active (or none)"
    )
    has_inventory_record: bool
    on_hand: int = Field(description="Physical units held")
    unavailable_quantity: int = Field(
        description="Units held but not sellable (included in on_hand)"
    )
    reserved_quantity: int = Field(description="Units in active (unpaid) reservations")
    committed_quantity: int = Field(
        description="Units in committed (paid, not dispatched) reservations"
    )
    available_quantity: int = Field(
        description="on_hand - unavailable - reserved - committed, never below 0"
    )


class InventoryListItem(InventoryResponse):
    """One SKU in the staff stock list (module 10). Same figures as GET /inventory/{sku}."""

    product_id: uuid.UUID
    product_name: str
    variant_name: str
    low_stock_threshold: int = Field(
        description="Low stock at or below this many available units; 0 disables it"
    )
    is_low_stock: bool = Field(
        description="available_quantity <= low_stock_threshold and low_stock_threshold > 0"
    )


class StockAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: AdjustmentReason = Field(
        description="receipt and inspected_return must add stock; adjustment may add or remove"
    )
    quantity_delta: int = Field(
        ge=-MAX_QUANTITY,
        le=MAX_QUANTITY,
        description="Signed change to physical on_hand; never zero",
        examples=[10, -2],
    )
    note: str | None = Field(default=None, max_length=500, description="Optional internal note")

    @field_validator("quantity_delta", mode="before")
    @classmethod
    def strict_int(cls, v: object) -> object:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("quantity_delta must be an integer")
        return v

    @field_validator("note")
    @classmethod
    def strip_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = "".join(ch for ch in v if ch.isprintable()).strip()
        return v or None

    @model_validator(mode="after")
    def check_direction(self) -> "StockAdjustmentRequest":
        if self.quantity_delta == 0:
            raise ValueError("quantity_delta must not be zero")
        if self.reason in ("receipt", "inspected_return") and self.quantity_delta < 0:
            raise ValueError(f"{self.reason} must increase stock")
        return self


class StockMovementResponse(BaseModel):
    id: uuid.UUID
    reason: str
    quantity_delta: int
    note: str | None
    created_at: datetime


class StockAdjustmentResponse(BaseModel):
    replayed: bool = Field(
        description="True when this Idempotency-Key was already applied; nothing changed again"
    )
    movement: StockMovementResponse
    inventory: InventoryResponse
