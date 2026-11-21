"""Catalogue import schemas (module 8; 'catalog:manage').

One data row describes one variant (SKU) and the product it belongs to. The column set is fixed
(IMPORT_COLUMNS) plus optional `attr:<key>` (variant attributes) and `spec:<key>` (product
specifications) columns. Field types reuse the module 6 product and variant schemas, so an
imported value obeys exactly the limits of the staff API.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.catalog import IMPORT_MAX_STORED_ERRORS
from app.schemas.catalog_admin import Slug
from app.schemas.product_admin import (
    LongText,
    ModelName,
    Price,
    ProductName,
    ProductSlug,
    ProductStatus,
    Sku,
    Threshold,
    VariantName,
)
from app.services.inventory import MAX_QUANTITY

ImportFormat = Literal["csv", "xlsx"]
ImportStatus = Literal["processing", "completed", "failed"]

MAX_IMPORT_ROWS = 5000  # data rows per file (plan §5 module 8)
MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 10 MB per uploaded file
MAX_IMPORT_COLUMNS = 100
DYNAMIC_KEY_MAX_LENGTH = 60
ATTRIBUTE_PREFIX = "attr:"
SPECIFICATION_PREFIX = "spec:"


@dataclass(frozen=True)
class ImportColumn:
    name: str
    required: bool
    kind: Literal["text", "integer", "boolean"]
    level: Literal["product", "variant"]
    description: str


IMPORT_COLUMNS: tuple[ImportColumn, ...] = (
    ImportColumn(
        "sku",
        True,
        "text",
        "variant",
        "Unique SKU of the variant (up to 80 characters, no spaces or '/'). An existing SKU is "
        "updated; a new SKU is created.",
    ),
    ImportColumn(
        "product_slug",
        True,
        "text",
        "product",
        "Slug of the product the SKU belongs to (lowercase letters, digits and single hyphens). "
        "Rows with the same product_slug are variants of one product; a new slug creates the "
        "product.",
    ),
    ImportColumn("product_name", True, "text", "product", "Product name (up to 240 characters)."),
    ImportColumn("category_slug", True, "text", "product", "Slug of an existing category."),
    ImportColumn("brand_slug", False, "text", "product", "Slug of an existing brand."),
    ImportColumn("model", False, "text", "product", "Model name (up to 160 characters)."),
    ImportColumn("description", False, "text", "product", "Product description."),
    ImportColumn("warranty_text", False, "text", "product", "Warranty information."),
    ImportColumn(
        "product_status",
        False,
        "text",
        "product",
        "draft, active, hidden or archived. A new product without a status is a draft.",
    ),
    ImportColumn(
        "variant_name", True, "text", "variant", "Variant name, e.g. '128 GB Black' (up to 180)."
    ),
    ImportColumn(
        "price", True, "integer", "variant", "Price in whole RWF, VAT-inclusive (digits only)."
    ),
    ImportColumn(
        "compare_at_price",
        False,
        "integer",
        "variant",
        "Display-only earlier price in whole RWF.",
    ),
    ImportColumn(
        "low_stock_threshold",
        False,
        "integer",
        "variant",
        "Show low stock at or below this many units; 0 disables it. New variants default to 0.",
    ),
    ImportColumn(
        "variant_active",
        False,
        "boolean",
        "variant",
        "true or false (also yes/no, 1/0). New variants default to true.",
    ),
    ImportColumn(
        "opening_stock",
        False,
        "integer",
        "variant",
        "New SKUs only: units received into stock (a 'receipt' movement). Needs the "
        "'inventory:adjust' permission. Leave blank for existing SKUs.",
    ),
)
COLUMNS_BY_NAME = {column.name: column for column in IMPORT_COLUMNS}
REQUIRED_COLUMNS = tuple(column.name for column in IMPORT_COLUMNS if column.required)
PRODUCT_FIELDS = tuple(column.name for column in IMPORT_COLUMNS if column.level == "product")
# Example dynamic columns in the template; any attr:<key> or spec:<key> header is accepted.
TEMPLATE_DYNAMIC_COLUMNS = ("attr:colour", "attr:storage", "spec:display")

Quantity = Annotated[int, Field(ge=0, le=MAX_QUANTITY)]
DynamicValue = Annotated[str, StringConstraints(min_length=1, max_length=500)]


class ImportRow(BaseModel):
    """A data row after cell cleaning; None means the cell was blank."""

    model_config = ConfigDict(extra="forbid", strict=True)

    sku: Sku
    product_slug: ProductSlug
    product_name: ProductName
    category_slug: Slug
    brand_slug: Slug | None = None
    model: ModelName | None = None
    description: LongText | None = None
    warranty_text: LongText | None = None
    product_status: ProductStatus | None = None
    variant_name: VariantName
    price: Price
    compare_at_price: Price | None = None
    low_stock_threshold: Threshold | None = None
    variant_active: bool | None = None
    opening_stock: Quantity | None = None
    attributes: dict[str, DynamicValue] = Field(default_factory=dict)
    specifications: dict[str, DynamicValue] = Field(default_factory=dict)


class ImportErrorEntry(BaseModel):
    row: int | None = Field(
        description="Spreadsheet row number (the header is row 1); null for a file-level error"
    )
    field: str | None = Field(description="Column header, or null when no single column applies")
    message: str = Field(description="What is wrong; submitted values are never echoed")


IMPORT_JOB_EXAMPLE: dict[str, Any] = {
    "id": "0b6f2a1e-8c4d-4f7a-9e3b-5d2c1a0f9e8d",
    "created_by_user_id": "4c3b2a19-0f8e-4d7c-8b6a-5f4e3d2c1b0a",
    "filename": "catalogue-october.xlsx",
    "file_format": "xlsx",
    "status": "completed",
    "total_rows": 3,
    "imported_rows": 2,
    "error_rows": 1,
    "errors": [
        {"row": 4, "field": "category_slug", "message": "No category has this slug."},
    ],
    "errors_truncated": False,
    "warnings": [
        {
            "row": 2,
            "field": "product_status",
            "message": "The product has no images, so it was saved as a draft instead of "
            "active. Upload images (bulk upload), then activate it.",
        }
    ],
    "created_at": "2026-10-24T09:00:00Z",
    "finished_at": "2026-10-24T09:00:02Z",
}


class ImportJobResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_extra={"examples": [IMPORT_JOB_EXAMPLE]}
    )

    id: uuid.UUID
    created_by_user_id: uuid.UUID
    filename: str
    file_format: ImportFormat
    status: ImportStatus = Field(
        description="completed: valid rows were applied (some rows may have errors); failed: "
        "the file was unusable or the import stopped unexpectedly, and nothing was changed"
    )
    total_rows: int = Field(description="Data rows read (blank rows are skipped)")
    imported_rows: int = Field(
        description="Valid rows applied in the import transaction (created or updated SKUs, "
        "including rows whose values already matched)"
    )
    error_rows: int = Field(description="Rows with at least one error; all are counted")
    errors: list[ImportErrorEntry] = Field(
        description=f"Row errors ordered by row, at most {IMPORT_MAX_STORED_ERRORS}"
    )
    errors_truncated: bool = Field(
        description=f"True when more than {IMPORT_MAX_STORED_ERRORS} errors were found and only "
        "the first ones are listed"
    )
    warnings: list[ImportErrorEntry] = Field(
        description="Rows applied with a change, ordered by row (2026-10-26): a product asked to "
        "be active without images is saved as a draft (or keeps its status)"
    )
    created_at: datetime
    finished_at: datetime | None
