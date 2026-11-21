from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import MAX_MONEY_RWF, Entity

if TYPE_CHECKING:
    from app.models.inventory import InventoryBalance
    from app.models.media import MediaObject


class Category(Entity):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("slug", name="category_slug"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        CheckConstraint(
            "(image_media_id IS NULL) = (image_original_media_id IS NULL)",
            name="image_media_together",
        ),
        Index("ix_categories_parent_active", "parent_id", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # B1 (approved 2026-10-25; ADR-009): short storefront subtitle and one image: its public
    # source and its private original, both in the media registry (2026-10-26).
    description: Mapped[str | None] = mapped_column(String(500))
    image_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), unique=True
    )
    image_original_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), unique=True
    )
    image_media: Mapped[MediaObject | None] = relationship(
        foreign_keys=[image_media_id], lazy="selectin"
    )
    # The product staff showcase on the home page's category spotlight (approved 2026-11-11).
    # Null: the storefront shows the category's best seller. SET NULL if the product is deleted.
    spotlight_product_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "products.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_categories_spotlight_product_id_products",
        )
    )

    parent: Mapped[Category | None] = relationship(
        remote_side="Category.id", back_populates="children"
    )
    children: Mapped[list[Category]] = relationship(back_populates="parent")
    products: Mapped[list[Product]] = relationship(
        back_populates="category", foreign_keys="Product.category_id"
    )


class Brand(Entity):
    __tablename__ = "brands"
    __table_args__ = (
        UniqueConstraint("slug", name="brand_slug"),
        CheckConstraint(
            "(logo_media_id IS NULL) = (logo_original_media_id IS NULL)",
            name="logo_media_together",
        ),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    # B1 (approved 2026-10-25; ADR-009): one logo, stored like a category image.
    logo_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), unique=True
    )
    logo_original_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), unique=True
    )
    logo_media: Mapped[MediaObject | None] = relationship(
        foreign_keys=[logo_media_id], lazy="selectin"
    )

    products: Mapped[list[Product]] = relationship(back_populates="brand")


class Product(Entity):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("slug", name="product_slug"),
        CheckConstraint("status IN ('draft', 'active', 'hidden', 'archived')", name="valid_status"),
        Index("ix_products_status_category", "status", "category_id"),
        Index("ix_products_status_brand", "status", "brand_id"),
        Index("ix_products_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_products_featured", "status", postgresql_where=text("is_featured")),
        # Module 20 (SC-01, 2026-10-27): totals of approved reviews, kept by the review service.
        CheckConstraint(
            "rating_1_count >= 0 AND rating_2_count >= 0 AND rating_3_count >= 0 "
            "AND rating_4_count >= 0 AND rating_5_count >= 0",
            name="rating_counts_nonnegative",
        ),
        CheckConstraint(
            "rating_count = rating_1_count + rating_2_count + rating_3_count "
            "+ rating_4_count + rating_5_count",
            name="rating_count_matches_distribution",
        ),
        CheckConstraint(
            "(rating_count = 0 AND rating_average IS NULL) OR "
            "(rating_count > 0 AND rating_average IS NOT NULL "
            "AND rating_average BETWEEN 1 AND 5)",
            name="rating_average_valid",
        ),
    )

    name: Mapped[str] = mapped_column(String(240), nullable=False)
    slug: Mapped[str] = mapped_column(String(260), nullable=False)
    model: Mapped[str | None] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    specifications: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    warranty_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    brand_id: Mapped[UUID | None] = mapped_column(ForeignKey("brands.id", ondelete="RESTRICT"))
    # B2 (approved 2026-10-25): staff-picked products for the storefront's Featured section.
    is_featured: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    # Module 20 (SC-01, approved 2026-10-27): approved reviews only. rating_average has one
    # decimal and is null while there are none; the distribution counts 1..5 stars.
    rating_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    rating_average: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    rating_1_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    rating_2_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    rating_3_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    rating_4_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    rating_5_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Module 9: full-text search over name, model and brand name, maintained only by database
    # triggers (migration a3b4d2f1d8e6). Never written by the application; not loaded by default.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, nullable=False, server_default=text("''::tsvector"), deferred=True
    )

    category: Mapped[Category] = relationship(back_populates="products", foreign_keys=[category_id])
    brand: Mapped[Brand | None] = relationship(back_populates="products")
    variants: Mapped[list[ProductVariant]] = relationship(
        back_populates="product", cascade="save-update, merge"
    )
    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product", cascade="save-update, merge", order_by="ProductImage.sort_order"
    )


class ProductVariant(Entity):
    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("sku", name="variant_sku"),
        # SKUs are unique ignoring case (2026-10-26); "__" is refused by the API.
        Index("uq_product_variants_sku_lower", text("lower(sku)"), unique=True),
        CheckConstraint("price >= 0", name="price_nonnegative"),
        CheckConstraint(
            f"price <= {MAX_MONEY_RWF} AND compare_at_price <= {MAX_MONEY_RWF}",
            name="amounts_within_cap",
        ),
        CheckConstraint("low_stock_threshold >= 0", name="low_stock_nonnegative"),
        CheckConstraint("currency_code = 'RWF'", name="currency_rwf"),
        Index("ix_product_variants_product_active", "product_id", "is_active"),
        Index("ix_product_variants_price", "price"),
    )

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compare_at_price: Mapped[int | None] = mapped_column(BigInteger)
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="RWF", server_default="RWF"
    )
    low_stock_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")

    product: Mapped[Product] = relationship(back_populates="variants")
    inventory: Mapped[InventoryBalance | None] = relationship(
        back_populates="variant", uselist=False
    )
    images: Mapped[list[ProductImage]] = relationship(
        back_populates="variant", order_by="ProductImage.sort_order"
    )


class ProductImage(Entity):
    __tablename__ = "product_images"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        Index("ix_product_images_product_order", "product_id", "sort_order"),
        # One product-level image per position (2026-10-26): "<slug>__<n>" names one image.
        Index(
            "uq_product_images_product_position",
            "product_id",
            "sort_order",
            unique=True,
            postgresql_where=text("variant_id IS NULL"),
        ),
    )

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    variant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL")
    )
    # ADR-009 media registry (2026-10-26): the public source (with its dimensions) and the exact
    # uploaded original (private storage), stored under the same key.
    public_media_id: Mapped[UUID] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    original_media_id: Mapped[UUID] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    alt_text: Mapped[str | None] = mapped_column(String(300))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    product: Mapped[Product] = relationship(back_populates="images")
    variant: Mapped[ProductVariant | None] = relationship(back_populates="images")
    public_media: Mapped[MediaObject] = relationship(
        foreign_keys=[public_media_id], lazy="selectin"
    )
    original_media: Mapped[MediaObject] = relationship(foreign_keys=[original_media_id])

    @property
    def storage_key(self) -> str:
        """Key of the public source (the private original has the same key)."""
        return self.public_media.storage_key

    @property
    def width(self) -> int:
        return self.public_media.width or 0

    @property
    def height(self) -> int:
        return self.public_media.height or 0


# Module 8: stored row errors per import job; error_rows keeps the full count beyond this.
IMPORT_MAX_STORED_ERRORS = 1000


class ImportJob(Entity):
    """One catalogue import (module 8). The uploaded file itself is not stored.

    status is 'processing' while the request runs, then 'completed' (valid rows applied; some
    rows may have errors) or 'failed' (the file was unusable or the import hit an unexpected
    error; no catalogue changes were made). finished_at is set exactly when status is final.
    """

    __tablename__ = "import_jobs"
    __table_args__ = (
        CheckConstraint("file_format IN ('csv', 'xlsx')", name="valid_file_format"),
        CheckConstraint("status IN ('processing', 'completed', 'failed')", name="valid_status"),
        CheckConstraint(
            "total_rows >= 0 AND imported_rows >= 0 AND error_rows >= 0", name="counts_nonnegative"
        ),
        CheckConstraint("imported_rows + error_rows <= total_rows", name="counts_within_total"),
        CheckConstraint(
            "jsonb_typeof(errors) = 'array' "
            f"AND jsonb_array_length(errors) <= {IMPORT_MAX_STORED_ERRORS}",
            name="errors_capped_array",
        ),
        CheckConstraint(
            "(status = 'processing') = (finished_at IS NULL)", name="finished_when_final"
        ),
        CheckConstraint("jsonb_typeof(warnings) = 'array'", name="warnings_array"),
        Index("ix_import_jobs_created_by_created", "created_by_user_id", "created_at"),
    )

    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="processing", server_default="processing"
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    imported_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # [{row, field, message}], at most IMPORT_MAX_STORED_ERRORS entries.
    errors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    errors_truncated: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    # [{row, field, message}]: rows applied with a change, e.g. created as a draft (2026-10-26).
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrandCategory(Base):
    """A main category a brand belongs to (ADR-012 decision 9, approved 2026-11-17). Staff choose
    at least one when they add a brand. It describes the brand: products are not restricted by
    it, and the storefront menu has its own list (CategoryMenuBrand). Deleting the brand or the
    category removes its rows."""

    __tablename__ = "brand_categories"
    __table_args__ = (Index("ix_brand_categories_category_id", "category_id"),)

    brand_id: Mapped[UUID] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )


class CategoryMenuBrand(Base):
    """A brand the storefront's category menu lists under a main category, in staff order
    (category hierarchy, ADR-012 amendment, approved 2026-11-16). The list is the whole menu
    for that category: a brand is listed even before it has products there. Replaced as a whole
    by PUT /staff/categories/{id}/menu-brands; deleting the category or the brand removes its
    rows."""

    __tablename__ = "category_menu_brands"
    __table_args__ = (
        CheckConstraint("position >= 1", name="position_positive"),
        UniqueConstraint("category_id", "position", name="category_position"),
        Index("ix_category_menu_brands_brand_id", "brand_id"),
    )

    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )
    brand_id: Mapped[UUID] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
