"""Staff category and brand management schemas (module 5, RE-018; 'catalog:manage')."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.slugs import SLUG_PATTERN
from app.schemas.images import PublicImage

NAME_MAX_LENGTH = 160  # categories.name and brands.name
DESCRIPTION_MAX_LENGTH = 500  # categories.description (B1)
SLUG_MAX_LENGTH = 180  # categories.slug and brands.slug
SORT_ORDER_MIN, SORT_ORDER_MAX = -(2**31), 2**31 - 1  # PostgreSQL integer

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH)
]
Slug = Annotated[
    str,
    Field(
        min_length=1,
        max_length=SLUG_MAX_LENGTH,
        pattern=SLUG_PATTERN,
        description="Lowercase ASCII letters and digits, words joined by single hyphens",
    ),
]
SortOrder = Annotated[int, Field(ge=SORT_ORDER_MIN, le=SORT_ORDER_MAX)]
Description = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=DESCRIPTION_MAX_LENGTH),
]

SLUG_DESCRIPTION = (
    "Omit to generate one from the name (a taken slug gets -2, -3, ...). "
    "A slug given explicitly must be unused, otherwise 409."
)


def _reject_explicit_nulls(model: BaseModel, fields: tuple[str, ...]) -> None:
    nulls = [f for f in fields if f in model.model_fields_set and getattr(model, f) is None]
    if nulls:
        raise ValueError(f"These fields cannot be null: {', '.join(nulls)}.")


class CategoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    slug: Slug | None = Field(default=None, description=SLUG_DESCRIPTION)
    parent_id: uuid.UUID | None = Field(default=None, description="Omit or null for a top level")
    sort_order: SortOrder = 0
    is_active: bool = True
    description: Description | None = Field(
        default=None, description="Short storefront subtitle, 1-500 characters"
    )


class CategoryUpdateRequest(BaseModel):
    """Partial update. A rename keeps the slug unless a new slug is sent. parent_id: null
    moves the category to the top level; description: null clears it. The image has its own
    routes (POST and DELETE /staff/categories/{id}/image)."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    slug: Slug | None = None
    parent_id: uuid.UUID | None = None
    sort_order: SortOrder | None = None
    is_active: bool | None = Field(default=None, description="false deactivates (hides) it")
    description: Description | None = Field(
        default=None, description="Short storefront subtitle; null clears it"
    )
    spotlight_product_id: uuid.UUID | None = Field(
        default=None,
        description="The product the home page's category spotlight showcases: one in this "
        "category or a subcategory. null clears it (the storefront then shows the best seller)",
    )

    @model_validator(mode="after")
    def check_fields(self) -> "CategoryUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        _reject_explicit_nulls(self, ("name", "slug", "sort_order", "is_active"))
        return self


CATEGORY_ORDER_MAX = 1000  # categories listed in one reorder request


class CategoryOrderRequest(BaseModel):
    """The new order of the categories directly under one parent (category hierarchy,
    2026-11-16). category_ids lists every one of them, hidden ones included, exactly once."""

    model_config = ConfigDict(extra="forbid")

    parent_id: uuid.UUID | None = Field(
        default=None,
        description="The parent whose subcategories are reordered; null for the main categories",
    )
    category_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=CATEGORY_ORDER_MAX,
        description="Every category directly under parent_id, in the new order; sort_order "
        "becomes 1, 2, 3, ...",
    )

    @model_validator(mode="after")
    def check_unique(self) -> "CategoryOrderRequest":
        if len(set(self.category_ids)) != len(self.category_ids):
            raise ValueError("category_ids lists a category more than once.")
        return self


CATEGORY_MENU_BRANDS_MAX = 30


class CategoryMenuBrandsRequest(BaseModel):
    """The brands the storefront's category menu lists for a main category, in order. Replaces
    the whole list; an empty list clears it (the menu then lists the brands of its products)."""

    model_config = ConfigDict(extra="forbid")

    brand_ids: list[uuid.UUID] = Field(
        max_length=CATEGORY_MENU_BRANDS_MAX,
        description=f"At most {CATEGORY_MENU_BRANDS_MAX} brands, each once, in menu order",
    )

    @field_validator("brand_ids")
    @classmethod
    def _unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Each brand may be listed once.")
        return value


BRAND_CATEGORIES_MAX = 50
BRAND_CATEGORIES_DESCRIPTION = (
    "The main categories the brand belongs to, at least one, each once (ADR-012 decision 9)"
)


def _unique_ids(ids: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
    if ids is not None and len(set(ids)) != len(ids):
        raise ValueError("List each category once.")
    return ids


class BrandCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    slug: Slug | None = Field(default=None, description=SLUG_DESCRIPTION)
    is_active: bool = True
    category_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=BRAND_CATEGORIES_MAX, description=BRAND_CATEGORIES_DESCRIPTION
    )

    @field_validator("category_ids")
    @classmethod
    def unique_categories(cls, ids: list[uuid.UUID]) -> list[uuid.UUID]:
        return _unique_ids(ids) or []


class BrandUpdateRequest(BaseModel):
    """Partial update. A rename keeps the slug unless a new slug is sent. The logo has its own
    routes (POST and DELETE /staff/brands/{id}/logo)."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    slug: Slug | None = None
    is_active: bool | None = Field(default=None, description="false deactivates (hides) it")
    category_ids: list[uuid.UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=BRAND_CATEGORIES_MAX,
        description=BRAND_CATEGORIES_DESCRIPTION + "; replaces the current ones",
    )

    @field_validator("category_ids")
    @classmethod
    def unique_categories(cls, ids: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        return _unique_ids(ids)

    @model_validator(mode="after")
    def check_fields(self) -> "BrandUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        _reject_explicit_nulls(self, ("name", "slug", "is_active", "category_ids"))
        return self


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    parent_id: uuid.UUID | None
    sort_order: int
    is_active: bool
    description: str | None
    image: PublicImage | None = None
    spotlight_product_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class BrandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    logo: PublicImage | None = None
    created_at: datetime
    updated_at: datetime


class StaffCategoryItem(CategoryResponse):
    """A category in the staff list, hidden ones included (frontend phase 6)."""

    product_count: int = Field(ge=0, description="Products directly in it, any status")
    menu_brand_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="The brands its storefront menu lists, in order (main categories only; "
        "hidden brands included here, left out on the storefront)",
    )


class StaffCategoriesResponse(BaseModel):
    items: list[StaffCategoryItem] = Field(
        description="Every category, active or not, by sort_order then name; parent_id builds "
        "the tree"
    )


class StaffBrandItem(BrandResponse):
    """A brand in the staff list, hidden ones included (frontend phase 6)."""

    product_count: int = Field(ge=0, description="Products of this brand, any status")
    category_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="The main categories it belongs to (ADR-012 decision 9); empty only for a "
        "brand added before 2026-11-17 and not linked yet",
    )


class StaffBrandsResponse(BaseModel):
    items: list[StaffBrandItem] = Field(description="Every brand, active or not, by name")
