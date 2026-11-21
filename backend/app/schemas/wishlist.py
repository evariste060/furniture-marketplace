"""Wishlist schemas (module 21, scope change SC-01 approved 2026-10-27)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.engagement import WISHLIST_LIMIT
from app.schemas.catalog import CatalogProduct
from app.schemas.images import PublicImage


class WishlistItemResponse(BaseModel):
    product_id: UUID
    added_at: datetime
    available: bool = Field(
        description="false: the product is no longer sold (show 'No longer available' and a "
        "remove button)"
    )
    name: str
    slug: str
    image: PublicImage | None = Field(description="The product's first image, or null")
    product: CatalogProduct | None = Field(
        description="The public product summary while it is sold; null when not available"
    )


class WishlistIdsResponse(BaseModel):
    product_ids: list[UUID] = Field(description="Every saved product, newest first")
    count: int = Field(ge=0, le=WISHLIST_LIMIT)
    limit: int = Field(default=WISHLIST_LIMIT, description="Most products a wishlist can hold")


class WishlistChangeResponse(BaseModel):
    product_id: UUID
    in_wishlist: bool
    count: int = Field(ge=0, le=WISHLIST_LIMIT, description="Saved products after the change")
