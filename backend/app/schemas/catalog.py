from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.images import PublicImage


class CatalogReference(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str


class StoreReference(BaseModel):
    """A store's public identity: the "Sold by" summary (ADR-014 phase 2)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str


class CatalogCategory(CatalogReference):
    sort_order: int
    parent_id: UUID | None
    description: str | None = Field(default=None, description="Short storefront subtitle")
    image: PublicImage | None = None
    spotlight_product_slug: str | None = Field(
        default=None,
        description="The public product staff chose for the home page's category spotlight "
        "(in this category or a subcategory); null when none is chosen or it is not public",
    )
    menu_brands: list[CatalogReference] = Field(
        default_factory=list,
        description="The active brands staff chose for this main category's menu, in order "
        "(ADR-012, 2026-11-16); empty when none are chosen",
    )
    children: list[CatalogCategory] = Field(
        default_factory=list, description="Active subcategories, in merchandising order"
    )


class CatalogBrand(CatalogReference):
    product_count: int = Field(ge=0, description="Public products of this brand")
    logo: PublicImage | None = None


class CatalogVariant(BaseModel):
    id: UUID
    sku: str
    name: str
    attributes: dict[str, Any]
    price: int = Field(description="Whole RWF, VAT-inclusive")
    compare_at_price: int | None
    currency_code: Literal["RWF"]
    stock_status: Literal["in_stock", "low_stock", "out_of_stock"] = Field(
        description="low_stock: available units at or below the variant's low-stock threshold "
        "(only when the threshold is above zero). Exact quantities are not public."
    )
    in_stock: bool
    images: list[PublicImage]


class CatalogRating(BaseModel):
    """Approved customer reviews only (module 20)."""

    average: float | None = Field(
        ge=1, le=5, description="One decimal place; null when there are no reviews"
    )
    count: int = Field(ge=0, description="Number of approved reviews")


class RatingBucket(BaseModel):
    stars: int = Field(ge=1, le=5)
    count: int = Field(ge=0)


class CatalogRatingDetail(CatalogRating):
    distribution: list[RatingBucket] = Field(
        description="Approved reviews per star rating, 5 stars first (always five entries)"
    )


class CatalogProduct(BaseModel):
    id: UUID
    name: str
    slug: str
    is_featured: bool = Field(description="Picked by staff for the storefront's Featured section")
    created_at: datetime = Field(description="When the product was created (newest sort)")
    model: str | None
    description: str | None
    specifications: dict[str, Any]
    warranty_text: str | None
    category: CatalogReference
    brand: CatalogReference | None
    store: StoreReference = Field(description="Sold by: the approved store that sells it")
    images: list[PublicImage]
    variants: list[CatalogVariant]
    rating: CatalogRating


class CatalogProductDetail(CatalogProduct):
    """One product: the summary plus the rating distribution."""

    rating: CatalogRatingDetail


class BrandFacet(BaseModel):
    slug: str
    name: str
    count: int = Field(ge=0)


class CategoryFacet(BaseModel):
    slug: str
    name: str
    count: int = Field(ge=0)


class PriceBandFacet(BaseModel):
    min_price: int | None = Field(description="Whole RWF, inclusive; null: no lower bound")
    max_price: int | None = Field(description="Whole RWF, inclusive; null: no upper bound")
    count: int = Field(ge=0)


class AvailabilityFacet(BaseModel):
    in_stock: int = Field(ge=0)
    out_of_stock: int = Field(ge=0)


class RatingFacet(BaseModel):
    min_rating: int = Field(ge=1, le=5)
    count: int = Field(ge=0)


class CatalogAttribute(BaseModel):
    """A furniture attribute (ADR-014 phase 6). Labels are the frontend's (English and
    Kinyarwanda messages), keyed by `key` and by each choice code."""

    key: str
    kind: Literal["choice", "number", "boolean"]
    unit: Literal["cm", "kg"] | None = None
    choices: list[str] = Field(default_factory=list, description="Choice codes, in display order")
    filterable: bool = Field(description="Offered as a storefront filter")


class CatalogAttributes(BaseModel):
    """The attributes and the attribute set of each category. A category without its own set
    uses its main category's, else `default_set`. Sets guide the editor; nothing is required."""

    attributes: list[CatalogAttribute]
    default_set: list[str]
    sets: dict[str, list[str]] = Field(description="Category slug -> attribute keys, in order")


class AttributeValueFacet(BaseModel):
    value: str = Field(description="The attribute code (app/core/furniture.py)")
    count: int = Field(ge=0)


class AttributeFacet(BaseModel):
    key: Literal["material", "color", "style"]
    values: list[AttributeValueFacet] = Field(
        description="Codes with matches, in the attribute's order; a chosen code without matches "
        "is listed with count 0"
    )


class CatalogFacets(BaseModel):
    """Option counts for the listing's filter panel. Each group ignores its own filter and
    applies the others: a count is what the list would show with that option picked."""

    total: int = Field(ge=0, description="Products matching every filter sent")
    brands: list[BrandFacet] = Field(
        description="Brands with matches, by name; a selected brand without matches is listed "
        "with count 0"
    )
    categories: list[CategoryFacet] = Field(
        description="Categories with matches, in the storefront menu's order (one can be "
        "chosen); a chosen category without matches is listed with count 0"
    )
    price_bands: list[PriceBandFacet] = Field(
        description="Fixed bands; a product counts in every band one of its variants is in"
    )
    availability: AvailabilityFacet
    ratings: list[RatingFacet] = Field(description="4 stars and up, 3 and up, 2 and up, 1 and up")
    attributes: list[AttributeFacet] = Field(
        default_factory=list,
        description="The furniture filters (ADR-014 phase 6): material, color and style, each "
        "ignoring its own filter",
    )
