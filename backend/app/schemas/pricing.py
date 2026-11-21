"""Pricing request schemas (RE-026 S1).

A request names SKUs and quantities only. Any price, subtotal, discount, fee, tax or total field
is rejected (extra="forbid"), because the server computes every amount from database prices.
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.inventory import MAX_QUANTITY


class PricingLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: uuid.UUID
    quantity: int = Field(strict=True, ge=1, le=MAX_QUANTITY, description="Whole units")


class MerchandiseQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[PricingLineRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def _one_line_per_sku(self) -> "MerchandiseQuoteRequest":
        variant_ids = [line.variant_id for line in self.lines]
        if len(set(variant_ids)) != len(variant_ids):
            raise ValueError("each SKU may appear on only one line")
        return self

    def line_tuples(self) -> list[tuple[uuid.UUID, int]]:
        return [(line.variant_id, line.quantity) for line in self.lines]
