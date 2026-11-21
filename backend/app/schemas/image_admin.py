"""Staff product image schemas (module 7; 'catalog:manage')."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ALT_TEXT_MAX_LENGTH = 300  # product_images.alt_text
SORT_ORDER_MAX = 2**31 - 1  # PostgreSQL integer

AltText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=ALT_TEXT_MAX_LENGTH)
]

# OpenAPI examples. Placeholder IDs and the example.rw host; IMAGE_PUBLIC_BASE_URL sets the real
# prefix.
# FastAPI removes null values from the OpenAPI document, so the examples avoid null; nulls are
# described on the fields instead.
EXAMPLE_KEY = (
    "products/1a2b3c4d-5e6f-4a8b-9c0d-1e2f3a4b5c6d/3f2a9c4e8b7d4f1a9e6c5b4a3d2e1f0a-9b1c2d3e4f5a"
)
EXAMPLE_VARIANT_ID = "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b"
IMAGE_EXAMPLE: dict[str, Any] = {
    "id": "6f1c2e9a-3b4d-4e5f-8a9b-0c1d2e3f4a5b",
    "product_id": "1a2b3c4d-5e6f-4a8b-9c0d-1e2f3a4b5c6d",
    "variant_id": EXAMPLE_VARIANT_ID,
    "image_ref": f"{EXAMPLE_KEY}.jpg",
    "url": f"https://media.example.rw/{EXAMPLE_KEY}.jpg",
    "thumbnail_url": f"https://media.example.rw/{EXAMPLE_KEY}.jpg",
    "width": 2400,
    "height": 1800,
    "alt_text": "Front view",
    "sort_order": 0,
    "created_at": "2026-10-24T08:30:00Z",
    "updated_at": "2026-10-24T08:30:00Z",
}
UPDATE_EXAMPLES: dict[str, dict[str, Any]] = {
    "reorder": {"summary": "Move the image to position 2", "value": {"sort_order": 2}},
    "describe": {
        "summary": "Set the alt text and attach the image to a variant",
        "value": {"alt_text": "Black, back view", "variant_id": EXAMPLE_VARIANT_ID},
    },
    "everything": {
        "summary": "Change all three fields at once",
        "description": 'Send "alt_text": null to clear the alt text and "variant_id": null to '
        "make the image product-level.",
        "value": {"sort_order": 0, "alt_text": "Front view", "variant_id": EXAMPLE_VARIANT_ID},
    },
}


class ImageUpdateRequest(BaseModel):
    """Partial update. variant_id: null makes it a product-level image; alt_text: null clears
    it. The file itself cannot be replaced: delete the image and upload a new one."""

    model_config = ConfigDict(extra="forbid")

    sort_order: int | None = Field(
        default=None, ge=0, le=SORT_ORDER_MAX, description="Position; lower comes first"
    )
    alt_text: AltText | None = Field(
        default=None, description="1-300 characters after trimming; null clears it"
    )
    variant_id: uuid.UUID | None = Field(
        default=None,
        description="A variant of the same product; null makes the image product-level",
    )

    @model_validator(mode="after")
    def check_fields(self) -> "ImageUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        if "sort_order" in self.model_fields_set and self.sort_order is None:
            raise ValueError("These fields cannot be null: sort_order.")
        return self


REORDER_MAX_IMAGES = 99  # bulk upload file names name positions 1-99


class ImageOrderRequest(BaseModel):
    """The product's product-level images (not variant images) in their new order, each exactly
    once. The first becomes position 1 (sort_order 0), and so on."""

    model_config = ConfigDict(extra="forbid")

    image_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=REORDER_MAX_IMAGES,
        description="Every product-level image of the product, each once, in display order",
    )

    @model_validator(mode="after")
    def check_unique(self) -> "ImageOrderRequest":
        if len(set(self.image_ids)) != len(self.image_ids):
            raise ValueError("Each image may appear only once.")
        return self


class ImageResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [IMAGE_EXAMPLE]})

    id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None = Field(description="Set for a variant-specific image")
    image_ref: str = Field(description="Stored key of the public source")
    url: str = Field(description="Public URL of the public source (IMAGE_PUBLIC_BASE_URL + key)")
    thumbnail_url: str = Field(
        deprecated=True,
        description="Deprecated (ADR-009; kept for one release): the same URL as url. The "
        "frontend image loader requests the width it needs from url.",
    )
    width: int = Field(description="Public source width in pixels")
    height: int = Field(description="Public source height in pixels")
    alt_text: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime
