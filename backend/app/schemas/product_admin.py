"""Staff product and variant management schemas (module 6; 'catalog:manage'), and the staff
product list and detail ('catalog:read', 2026-10-26)."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.slugs import SLUG_PATTERN
from app.models.common import MAX_MONEY_RWF
from app.schemas.catalog import CatalogReference, StoreReference
from app.schemas.image_admin import ImageResponse
from app.schemas.images import PublicImage

PRODUCT_NAME_MAX_LENGTH = 240  # products.name
PRODUCT_SLUG_MAX_LENGTH = 260  # products.slug
MODEL_MAX_LENGTH = 160  # products.model
SKU_MAX_LENGTH = 80  # product_variants.sku
VARIANT_NAME_MAX_LENGTH = 180  # product_variants.name
THRESHOLD_MAX = 2**31 - 1  # PostgreSQL integer

ProductStatus = Literal["draft", "active", "hidden", "archived"]


ProductName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=PRODUCT_NAME_MAX_LENGTH),
]
ModelName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MODEL_MAX_LENGTH)
]
VariantName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=VARIANT_NAME_MAX_LENGTH),
]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ProductSlug = Annotated[
    str,
    Field(
        min_length=1,
        max_length=PRODUCT_SLUG_MAX_LENGTH,
        pattern=SLUG_PATTERN,
        description="Lowercase ASCII letters and digits, words joined by single hyphens",
    ),
]
# SKUs appear in URL paths (/inventory/{sku}), so whitespace and '/' are not allowed; "__" is
# the separator of bulk image file names ("<slug>__<n>.jpg"), so it is refused too (2026-10-26).
SKU_SEPARATOR = "__"


def _no_separator(value: str) -> str:
    if SKU_SEPARATOR in value:
        raise ValueError("A SKU may not contain '__'.")
    return value


Sku = Annotated[
    str,
    Field(
        min_length=1,
        max_length=SKU_MAX_LENGTH,
        pattern=r"^[^\s/]+$",
        description="Unique SKU, ignoring case; no spaces, '/' or '__'",
    ),
    AfterValidator(_no_separator),
]
Price = Annotated[int, Field(ge=0, le=MAX_MONEY_RWF, description="Whole RWF, VAT-inclusive")]
Threshold = Annotated[int, Field(ge=0, le=THRESHOLD_MAX)]

SLUG_DESCRIPTION = (
    "Omit to generate one from the name (a taken slug gets -2, -3, ...). "
    "A slug given explicitly must be unused, otherwise 409."
)


def _check_update(model: BaseModel, required: tuple[str, ...]) -> None:
    if not model.model_fields_set:
        raise ValueError("Provide at least one field to change.")
    nulls = [f for f in required if f in model.model_fields_set and getattr(model, f) is None]
    if nulls:
        raise ValueError(f"These fields cannot be null: {', '.join(nulls)}.")


class ProductCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProductName
    slug: ProductSlug | None = Field(default=None, description=SLUG_DESCRIPTION)
    category_id: uuid.UUID
    brand_id: uuid.UUID | None = None
    model: ModelName | None = None
    description: LongText | None = None
    specifications: dict[str, Any] = Field(default_factory=dict)
    warranty_text: LongText | None = None
    status: ProductStatus = "draft"
    is_featured: bool = Field(
        default=False, description="Show in the storefront's Featured section (B2)"
    )


class ProductUpdateRequest(BaseModel):
    """Partial update. A rename keeps the slug unless a new slug is sent. brand_id, model,
    description and warranty_text accept null to clear them."""

    model_config = ConfigDict(extra="forbid")

    name: ProductName | None = None
    slug: ProductSlug | None = None
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    model: ModelName | None = None
    description: LongText | None = None
    specifications: dict[str, Any] | None = None
    warranty_text: LongText | None = None
    status: ProductStatus | None = None
    is_featured: bool | None = Field(
        default=None, description="Show in the storefront's Featured section (B2)"
    )

    @model_validator(mode="after")
    def check_fields(self) -> "ProductUpdateRequest":
        _check_update(
            self, ("name", "slug", "category_id", "specifications", "status", "is_featured")
        )
        return self


class SellerProductCreateRequest(BaseModel):
    """A seller's new product (ADR-014 phase 2). The store is always the seller's own, taken
    from the session; store_id, is_featured and other merchandising fields are refused (422)."""

    model_config = ConfigDict(extra="forbid")

    name: ProductName
    slug: ProductSlug | None = Field(default=None, description=SLUG_DESCRIPTION)
    category_id: uuid.UUID
    brand_id: uuid.UUID | None = None
    model: ModelName | None = None
    description: LongText | None = None
    specifications: dict[str, Any] = Field(default_factory=dict)
    warranty_text: LongText | None = None
    status: ProductStatus = "draft"


class SellerProductUpdateRequest(BaseModel):
    """A seller's partial update of their own product: the staff fields without is_featured."""

    model_config = ConfigDict(extra="forbid")

    name: ProductName | None = None
    slug: ProductSlug | None = None
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    model: ModelName | None = None
    description: LongText | None = None
    specifications: dict[str, Any] | None = None
    warranty_text: LongText | None = None
    status: ProductStatus | None = None

    @model_validator(mode="after")
    def check_fields(self) -> "SellerProductUpdateRequest":
        _check_update(self, ("name", "slug", "category_id", "specifications", "status"))
        return self


class VariantCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: Sku
    name: VariantName
    attributes: dict[str, Any] = Field(default_factory=dict)
    price: Price
    compare_at_price: Price | None = Field(default=None, description="Display only")
    low_stock_threshold: Threshold = Field(
        default=0, description="Public low_stock at or below this many units; 0 disables it"
    )
    is_active: bool = True


class VariantUpdateRequest(BaseModel):
    """Partial update. compare_at_price accepts null to clear it."""

    model_config = ConfigDict(extra="forbid")

    sku: Sku | None = None
    name: VariantName | None = None
    attributes: dict[str, Any] | None = None
    price: Price | None = None
    compare_at_price: Price | None = None
    low_stock_threshold: Threshold | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def check_fields(self) -> "VariantUpdateRequest":
        _check_update(
            self, ("sku", "name", "attributes", "price", "low_stock_threshold", "is_active")
        )
        return self


class VariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    attributes: dict[str, Any]
    price: int
    compare_at_price: int | None
    currency_code: str
    low_stock_threshold: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductResponse(BaseModel):
    """Staff view: every variant, active or not."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    category_id: uuid.UUID
    brand_id: uuid.UUID | None
    model: str | None
    description: str | None
    specifications: dict[str, Any]
    warranty_text: str | None
    status: ProductStatus
    is_featured: bool
    store_id: uuid.UUID = Field(description="The store that owns the product (ADR-014)")
    variants: list[VariantResponse]
    created_at: datetime
    updated_at: datetime


class StaffProductListItem(BaseModel):
    """One row of the staff product list: every status, drafts included."""

    id: uuid.UUID
    name: str
    slug: str
    status: ProductStatus
    is_featured: bool
    category: CatalogReference
    brand: CatalogReference | None
    store: StoreReference = Field(description="The store that owns the product (ADR-014)")
    variant_count: int = Field(ge=0, description="Variants, active or not")
    image_count: int = Field(ge=0, description="Product images (variant images not counted)")
    image: PublicImage | None = Field(description="The first product image, if any")
    next_photo_file_name: str = Field(
        description="Bulk upload file name for the next free position, e.g. "
        "samsung-galaxy-a55__2.jpg (jpg, jpeg, png or webp)"
    )
    sku: str | None = Field(
        default=None, description="The first active variant's SKU (by SKU); null if none"
    )
    price: int | None = Field(
        default=None, description="Lowest active variant price, whole RWF; null if none"
    )
    available_quantity: int = Field(
        default=0, ge=0, description="Units available to sell across the active variants"
    )
    has_low_stock: bool = Field(
        default=False, description="An active variant is at or below its low-stock threshold"
    )
    created_at: datetime
    updated_at: datetime


class PhotoFileName(BaseModel):
    image_id: uuid.UUID
    position: int = Field(ge=1, description="1-based position (sort_order + 1)")
    file_name: str = Field(description="Upload a file with this name to replace this image")


class StaffProductDetail(ProductResponse):
    """ProductResponse plus every image of the product (variant images included), in order."""

    images: list[ImageResponse]
    photo_file_names: list[PhotoFileName] = Field(
        description="Bulk upload file names of the product images (variant images excluded)"
    )
    next_photo_file_name: str = Field(description="File name for the next free position")


BULK_ACTIVATE_MAX = 200
BulkActivateOutcome = Literal["activated", "skipped_no_images", "already_active", "not_found"]


class BulkActivateRequest(BaseModel):
    product_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=BULK_ACTIVATE_MAX, description="At most 200, no repeats"
    )

    @model_validator(mode="after")
    def _unique(self) -> "BulkActivateRequest":
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("Each product ID may appear once.")
        return self


class BulkActivateResult(BaseModel):
    product_id: uuid.UUID
    outcome: BulkActivateOutcome


class BulkActivateResponse(BaseModel):
    results: list[BulkActivateResult] = Field(description="One per requested ID, in order")
    activated: int
    skipped_no_images: int
    already_active: int
    not_found: int
