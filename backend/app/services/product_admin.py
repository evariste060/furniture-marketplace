"""Staff product and variant management (module 6; 'catalog:manage').

Rules:
- Product slugs are generated from the name when none is sent (app.core.slugs, smallest free -N
  suffix). An explicitly sent slug must be unused (409 slug_taken). A rename keeps the slug.
- SKUs are unique ignoring case (409 sku_taken) and may not contain "__" (422; the
  separator of bulk image file names).
- Publication guard (2026-10-26): a product becomes active only with at least one product
  image (409 product_has_no_images), and the last product image of an active product
  cannot be removed (409 last_product_image). Every path that activates a product or
  removes a product image calls ensure_publishable: product create and update, the
  catalogue import, image delete, moving an image to a variant, bulk image replace and
  bulk activate. Products already active without images are not deactivated.
- A variant DELETE deactivates it (is_active=false): stock and orders reference variants, so
  they are never removed. Deactivated variants are hidden from the public catalogue.
- Every successful change commits together with its audit record; a request that changes
  nothing is not audited. Price changes are audited with the old and new values.
- category_id and brand_id must reference existing rows (422). A new assignment (create, or a
  changed category_id or brand_id) must be to a visible category (active, and so is its main
  category) and an active brand (422; category hierarchy, 2026-11-16). A product already in a
  category or brand that was hidden later keeps it, and other edits to it still work; public
  visibility rules hide it until both are visible again.

The staff product list and detail ('catalog:read', 2026-10-26) show every product whatever its
status, so staff can find drafts; the public catalogue shows active products only.
Stores (ADR-014 phase 2): every product belongs to one store. Every function reachable by a
seller takes a CatalogScope (app.services.catalog_scope), with no default: a seller's scope is
their own store, and another store's product is 404 product_not_found. Sellers create products
in their own store; platform staff moderate (view, edit, hide, archive) products of every store
but do not create them (SC-05: 409 staff_product_creation_disabled).

Concurrency: every product or variant change takes one transaction-scoped advisory lock, so slug
and SKU allocation cannot race, and the row being changed is locked FOR UPDATE. The unique
constraints remain the final guard; their violations are reported as 409.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, literal, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.sql.selectable import ScalarSelect

from app.core.errors import Conflict, NotFound, field_error
from app.core.request_context import RequestContext
from app.core.slugs import first_free_slug, slugify
from app.db.transaction import atomic
from app.models import Brand, Category, MediaObject, Product, ProductImage, ProductVariant
from app.models.identity import User
from app.repositories.category_tree import category_visible
from app.schemas.pagination import page_offset
from app.schemas.product_admin import (
    PRODUCT_SLUG_MAX_LENGTH,
    ProductCreateRequest,
    ProductStatus,
    ProductUpdateRequest,
    VariantCreateRequest,
    VariantUpdateRequest,
)
from app.services.catalog_admin import _audit, _changes, _lock
from app.services.catalog_scope import CatalogScope
from app.services.inventory import stock_figures

# pg_advisory_xact_lock(bigint) keys: ...001 staff, ...002 categories, ...003 brands.
PRODUCT_CHANGE_LOCK_KEY = 7_302_116_004

PRODUCT_NOT_FOUND = "Product not found."
CATEGORY_HIDDEN = (
    "This category is hidden (it or its main category is inactive); choose a visible one."
)
BRAND_HIDDEN = "This brand is hidden; choose an active brand."
VARIANT_NOT_FOUND = "Variant not found for this product."
SLUG_TAKEN = "This slug is already used by another product."
SKU_TAKEN = "This SKU is already used by another variant."
NO_IMAGES = (
    "A product needs at least one product image before it can be active. Add an image (or a "
    "bulk upload), then activate it; until then it stays a draft."
)
LAST_IMAGE = "Upload a replacement or deactivate the product first."
NO_SLUG_FROM_NAME = "The name has no letters or digits to build a slug from; send a slug."
STAFF_CREATE_DISABLED = (
    "Marketplace administrators do not create products: every product belongs to a seller's "
    "store, and sellers add their own products. Administrators can view, edit, hide and archive "
    "products of every store."
)
# Long or structured fields: the audit records that they changed, not their full values.
SUMMARISED_FIELDS = frozenset({"description", "specifications", "warranty_text", "attributes"})


def _audit_changes(changes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        field: {"changed": True} if field in SUMMARISED_FIELDS else change
        for field, change in changes.items()
    }


def _slug_taken(db: Session, slug: str, exclude_id: uuid.UUID | None) -> bool:
    query = select(Product.id).where(Product.slug == slug)
    if exclude_id is not None:
        query = query.where(Product.id != exclude_id)
    return db.scalar(query.limit(1)) is not None


def _sku_taken(db: Session, sku: str, exclude_id: uuid.UUID | None) -> bool:
    query = select(ProductVariant.id).where(func.lower(ProductVariant.sku) == sku.lower())
    if exclude_id is not None:
        query = query.where(ProductVariant.id != exclude_id)
    return db.scalar(query.limit(1)) is not None


def _new_slug(db: Session, req: ProductCreateRequest) -> str:
    if req.slug is not None:
        if _slug_taken(db, req.slug, None):
            raise Conflict(SLUG_TAKEN, code="slug_taken")
        return req.slug
    base = slugify(req.name, PRODUCT_SLUG_MAX_LENGTH)
    if not base:
        raise field_error(("body", "name"), NO_SLUG_FROM_NAME)
    return first_free_slug(base, lambda s: _slug_taken(db, s, None), PRODUCT_SLUG_MAX_LENGTH)


def _check_references(
    db: Session, category_id: uuid.UUID | None, brand_id: uuid.UUID | None
) -> None:
    """The category and brand of a new assignment exist and are visible (None: not assigned)."""
    if category_id is not None:
        if db.get(Category, category_id) is None:
            raise field_error(("body", "category_id"), "Category not found.")
        if not db.scalar(select(category_visible(literal(category_id)))):
            raise field_error(("body", "category_id"), CATEGORY_HIDDEN)
    if brand_id is not None:
        brand = db.get(Brand, brand_id)
        if brand is None:
            raise field_error(("body", "brand_id"), "Brand not found.")
        if not brand.is_active:
            raise field_error(("body", "brand_id"), BRAND_HIDDEN)


def _locked_product(db: Session, product_id: uuid.UUID, scope: CatalogScope) -> Product:
    product = db.scalar(
        select(Product).where(Product.id == product_id, scope.products()).with_for_update()
    )
    if product is None:
        raise NotFound(PRODUCT_NOT_FOUND, code="product_not_found")
    return product


def _locked_variant(db: Session, product_id: uuid.UUID, variant_id: uuid.UUID) -> ProductVariant:
    variant = db.scalar(
        select(ProductVariant)
        .where(ProductVariant.id == variant_id, ProductVariant.product_id == product_id)
        .with_for_update()
    )
    if variant is None:
        raise NotFound(VARIANT_NOT_FOUND, code="variant_not_found")
    return variant


def _unique_conflict(exc: IntegrityError) -> Conflict | None:
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
    if "slug" in constraint:
        return Conflict(SLUG_TAKEN, code="slug_taken")
    if "sku" in constraint:
        return Conflict(SKU_TAKEN, code="sku_taken")
    return None


# ---- the publication guard (2026-10-26) --------------------------------------------------------
def has_publishable_image(
    db: Session, product_id: uuid.UUID, *, excluding_image_id: uuid.UUID | None = None
) -> bool:
    """At least one product image (not a variant image) whose public file is active."""
    query = (
        select(ProductImage.id)
        .join(MediaObject, MediaObject.id == ProductImage.public_media_id)
        .where(
            ProductImage.product_id == product_id,
            ProductImage.variant_id.is_(None),
            MediaObject.state == "active",
        )
    )
    if excluding_image_id is not None:
        query = query.where(ProductImage.id != excluding_image_id)
    return db.scalar(query.limit(1)) is not None


def ensure_publishable(
    db: Session,
    product_id: uuid.UUID | None,
    *,
    excluding_image_id: uuid.UUID | None = None,
) -> None:
    """The single publication guard: the product has (or, without excluding_image_id, keeps) a
    product image. product_id None is a product not created yet, which has none.
    Raises 409 product_has_no_images, or last_product_image when removing an image."""
    if product_id is not None and has_publishable_image(
        db, product_id, excluding_image_id=excluding_image_id
    ):
        return
    if excluding_image_id is not None:
        raise Conflict(LAST_IMAGE, code="last_product_image")
    raise Conflict(NO_IMAGES, code="product_has_no_images")


# ---- changes inside the caller's transaction (also used by the catalogue import, module 8) ----
# Each function expects PRODUCT_CHANGE_LOCK_KEY to be held and commits nothing; the caller owns
# the transaction. They apply the same rules and audit records as the routes.
def apply_product_create(
    db: Session,
    actor: User,
    req: ProductCreateRequest,
    ctx: RequestContext,
    *,
    store_id: uuid.UUID,
) -> Product:
    _check_references(db, req.category_id, req.brand_id)
    if req.status == "active":
        ensure_publishable(db, None)  # a new product has no images yet
    product = Product(
        name=req.name,
        slug=_new_slug(db, req),
        category_id=req.category_id,
        brand_id=req.brand_id,
        model=req.model,
        description=req.description,
        specifications=req.specifications,
        warranty_text=req.warranty_text,
        status=req.status,
        is_featured=req.is_featured,
        store_id=store_id,
    )
    db.add(product)
    db.flush()
    _audit(
        db,
        "catalog.product_create",
        "product",
        product.id,
        actor,
        ctx,
        {
            "name": product.name,
            "slug": product.slug,
            "status": product.status,
            "is_featured": product.is_featured,
            "category_id": product.category_id,
            "brand_id": product.brand_id,
            "store_id": product.store_id,
        },
    )
    return product


def apply_product_update(
    db: Session, actor: User, product: Product, req: ProductUpdateRequest, ctx: RequestContext
) -> bool:
    """Apply a partial update to a locked product. False when nothing changed (no audit)."""
    fields = req.model_fields_set
    # Only a changed category or brand is a new assignment; keeping a hidden one is allowed.
    _check_references(
        db,
        req.category_id
        if "category_id" in fields and req.category_id != product.category_id
        else None,
        req.brand_id if "brand_id" in fields and req.brand_id != product.brand_id else None,
    )
    if req.slug is not None and req.slug != product.slug:
        if _slug_taken(db, req.slug, product.id):
            raise Conflict(SLUG_TAKEN, code="slug_taken")
    if "status" in fields and req.status == "active" and product.status != "active":
        ensure_publishable(db, product.id)
    changes = _changes(product, {f: getattr(req, f) for f in fields})
    if not changes:
        return False
    db.flush()
    _audit(
        db,
        "catalog.product_update",
        "product",
        product.id,
        actor,
        ctx,
        {"changes": _audit_changes(changes)},
    )
    return True


def apply_variant_create(
    db: Session, actor: User, product: Product, req: VariantCreateRequest, ctx: RequestContext
) -> ProductVariant:
    if _sku_taken(db, req.sku, None):
        raise Conflict(SKU_TAKEN, code="sku_taken")
    variant = ProductVariant(
        product_id=product.id,
        sku=req.sku,
        name=req.name,
        attributes=req.attributes,
        price=req.price,
        compare_at_price=req.compare_at_price,
        low_stock_threshold=req.low_stock_threshold,
        is_active=req.is_active,
    )
    db.add(variant)
    db.flush()
    _audit(
        db,
        "catalog.variant_create",
        "product_variant",
        variant.id,
        actor,
        ctx,
        {
            "product_id": product.id,
            "sku": variant.sku,
            "price": variant.price,
            "compare_at_price": variant.compare_at_price,
            "low_stock_threshold": variant.low_stock_threshold,
            "is_active": variant.is_active,
        },
    )
    return variant


def apply_variant_update(
    db: Session,
    actor: User,
    variant: ProductVariant,
    req: VariantUpdateRequest,
    ctx: RequestContext,
) -> bool:
    """Apply a partial update to a locked variant. False when nothing changed (no audit)."""
    if req.sku is not None and req.sku != variant.sku:
        if _sku_taken(db, req.sku, variant.id):
            raise Conflict(SKU_TAKEN, code="sku_taken")
    changes = _changes(variant, {f: getattr(req, f) for f in req.model_fields_set})
    if not changes:
        return False
    db.flush()
    # Price changes appear here as {"price": {"from": old, "to": new}}.
    _audit(
        db,
        "catalog.variant_update",
        "product_variant",
        variant.id,
        actor,
        ctx,
        {"product_id": variant.product_id, "changes": _audit_changes(changes)},
    )
    return True


class ProductAdminService:
    # ---- products -----------------------------------------------------------------------------
    @staticmethod
    def create_product(
        db: Session,
        actor: User,
        req: ProductCreateRequest,
        ctx: RequestContext,
        *,
        scope: CatalogScope,
    ) -> Product:
        """A product in the scope's store. Platform staff have no store: 409 (SC-05)."""
        if scope.store_id is None:
            raise Conflict(STAFF_CREATE_DISABLED, code="staff_product_creation_disabled")
        try:
            with atomic(db):
                _lock(db, PRODUCT_CHANGE_LOCK_KEY)
                product = apply_product_create(db, actor, req, ctx, store_id=scope.store_id)
        except IntegrityError as exc:
            conflict = _unique_conflict(exc)
            if conflict is None:
                raise
            raise conflict from None
        return product

    @staticmethod
    def update_product(
        db: Session,
        actor: User,
        product_id: uuid.UUID,
        req: ProductUpdateRequest,
        ctx: RequestContext,
        *,
        scope: CatalogScope,
    ) -> Product:
        try:
            with atomic(db):
                _lock(db, PRODUCT_CHANGE_LOCK_KEY)
                product = _locked_product(db, product_id, scope)
                apply_product_update(db, actor, product, req, ctx)
        except IntegrityError as exc:
            conflict = _unique_conflict(exc)
            if conflict is None:
                raise
            raise conflict from None
        return product

    # ---- variants -----------------------------------------------------------------------------
    @staticmethod
    def create_variant(
        db: Session,
        actor: User,
        product_id: uuid.UUID,
        req: VariantCreateRequest,
        ctx: RequestContext,
        *,
        scope: CatalogScope,
    ) -> ProductVariant:
        try:
            with atomic(db):
                _lock(db, PRODUCT_CHANGE_LOCK_KEY)
                product = _locked_product(db, product_id, scope)
                variant = apply_variant_create(db, actor, product, req, ctx)
        except IntegrityError as exc:
            conflict = _unique_conflict(exc)
            if conflict is None:
                raise
            raise conflict from None
        return variant

    @staticmethod
    def update_variant(
        db: Session,
        actor: User,
        product_id: uuid.UUID,
        variant_id: uuid.UUID,
        req: VariantUpdateRequest,
        ctx: RequestContext,
        *,
        scope: CatalogScope,
    ) -> ProductVariant:
        try:
            with atomic(db):
                _lock(db, PRODUCT_CHANGE_LOCK_KEY)
                _locked_product(db, product_id, scope)
                variant = _locked_variant(db, product_id, variant_id)
                apply_variant_update(db, actor, variant, req, ctx)
        except IntegrityError as exc:
            conflict = _unique_conflict(exc)
            if conflict is None:
                raise
            raise conflict from None
        return variant

    @staticmethod
    def deactivate_variant(
        db: Session,
        actor: User,
        product_id: uuid.UUID,
        variant_id: uuid.UUID,
        ctx: RequestContext,
        *,
        scope: CatalogScope,
    ) -> None:
        """DELETE semantics: the variant is kept and deactivated. Repeating it is a no-op."""
        with atomic(db):
            _lock(db, PRODUCT_CHANGE_LOCK_KEY)
            _locked_product(db, product_id, scope)
            variant = _locked_variant(db, product_id, variant_id)
            if not variant.is_active:
                return
            variant.is_active = False
            db.flush()
            _audit(
                db,
                "catalog.variant_deactivate",
                "product_variant",
                variant.id,
                actor,
                ctx,
                {"product_id": product_id, "sku": variant.sku},
            )


def sorted_variants(product: Product) -> list[ProductVariant]:
    return sorted(product.variants, key=lambda v: (v.name, str(v.id)))


# ---- staff product list and detail ('catalog:read') -------------------------------------------
def product_image_exists():
    """True when the product has at least one product image (variant images not counted)."""
    return (
        select(ProductImage.id)
        .where(ProductImage.product_id == Product.id, ProductImage.variant_id.is_(None))
        .exists()
    )


def _count(column: Any, *conditions: Any) -> ScalarSelect[int]:
    return select(func.count(column)).where(*conditions).correlate(Product).scalar_subquery()


def list_staff_products(
    db: Session,
    *,
    status: ProductStatus | None,
    has_images: bool | None,
    category_id: uuid.UUID | None,
    brand_id: uuid.UUID | None,
    featured: bool | None,
    q: str | None,
    page: int,
    size: int,
    scope: CatalogScope,
    low_stock: bool | None = None,
    store_id: uuid.UUID | None = None,
) -> tuple[list[tuple[Product, int, int]], int]:
    """(product, variant count, product image count) rows, most recently updated first.
    low_stock: true keeps products with an active low-stock variant, false the others.
    store_id narrows a platform list to one store; a seller's scope is always their own."""
    conditions: list[Any] = [scope.products()]
    if store_id is not None:
        conditions.append(Product.store_id == store_id)
    if low_stock is not None:
        figures, columns = stock_figures()
        low = (
            figures.where(
                ProductVariant.product_id == Product.id,
                ProductVariant.is_active.is_(True),
                columns.is_low_stock,
            )
            .exists()
            .correlate(Product)
        )
        conditions.append(low if low_stock else ~low)
    if status is not None:
        conditions.append(Product.status == status)
    if has_images is not None:
        exists = product_image_exists()
        conditions.append(exists if has_images else ~exists)
    if category_id is not None:
        conditions.append(Product.category_id == category_id)
    if brand_id is not None:
        conditions.append(Product.brand_id == brand_id)
    if featured is not None:
        conditions.append(Product.is_featured.is_(featured))
    if q is not None:
        pattern = f"%{q.lower()}%"
        sku_match = (
            select(ProductVariant.id)
            .where(
                ProductVariant.product_id == Product.id,
                func.lower(ProductVariant.sku).like(pattern),
            )
            .exists()
        )
        conditions.append(
            or_(
                func.lower(Product.name).like(pattern),
                func.lower(Product.slug).like(pattern),
                func.lower(func.coalesce(Product.model, "")).like(pattern),
                sku_match,
            )
        )
    total = db.scalar(select(func.count(Product.id)).where(*conditions)) or 0
    variant_count = _count(ProductVariant.id, ProductVariant.product_id == Product.id)
    image_count = _count(
        ProductImage.id, ProductImage.product_id == Product.id, ProductImage.variant_id.is_(None)
    )
    rows = db.execute(
        select(Product, variant_count, image_count)
        .where(*conditions)
        .options(
            joinedload(Product.category),
            joinedload(Product.brand),
            joinedload(Product.store),
            selectinload(Product.images.and_(ProductImage.variant_id.is_(None))),
        )
        .order_by(Product.updated_at.desc(), Product.id.asc())
        .offset(page_offset(page, size))
        .limit(size)
    ).unique()
    return [(product, variants, images) for product, variants, images in rows], total


@dataclass(frozen=True)
class ProductStock:
    sku: str | None
    price: int | None
    available_quantity: int
    has_low_stock: bool


def product_stock(db: Session, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, ProductStock]:
    """Price and stock of each product's active variants, for the staff list (one query)."""
    if not product_ids:
        return {}
    figures, columns = stock_figures()
    rows = db.execute(
        figures.add_columns(ProductVariant.product_id, ProductVariant.sku, ProductVariant.price)
        .where(ProductVariant.product_id.in_(product_ids), ProductVariant.is_active.is_(True))
        .order_by(ProductVariant.sku)
    ).mappings()
    found: dict[uuid.UUID, list[Any]] = {}
    for row in rows:
        found.setdefault(row["product_id"], []).append(row)
    return {
        product_id: ProductStock(
            sku=variants[0]["sku"],
            price=min(v["price"] for v in variants),
            available_quantity=sum(int(v["available_quantity"]) for v in variants),
            has_low_stock=any(v["is_low_stock"] for v in variants),
        )
        for product_id, variants in found.items()
    }


def get_staff_product(db: Session, product_id: uuid.UUID, scope: CatalogScope) -> Product:
    product = db.scalar(
        select(Product)
        .where(Product.id == product_id, scope.products())
        .options(selectinload(Product.variants), selectinload(Product.images))
    )
    if product is None:
        raise NotFound(PRODUCT_NOT_FOUND, code="product_not_found")
    return product


# ---- bulk activate (2026-10-26) ----------------------------------------------------------------
def bulk_activate(
    db: Session,
    actor: User,
    product_ids: list[uuid.UUID],
    ctx: RequestContext,
    *,
    scope: CatalogScope,
) -> list[tuple[uuid.UUID, str]]:
    """Activate each product that passes the publication guard; one audit per activation.
    Outcomes: activated, skipped_no_images, already_active, not_found."""
    results: list[tuple[uuid.UUID, str]] = []
    with atomic(db):
        _lock(db, PRODUCT_CHANGE_LOCK_KEY)
        products = {
            product.id: product
            for product in db.scalars(
                select(Product)
                .where(Product.id.in_(product_ids), scope.products())
                .with_for_update()
            )
        }
        for product_id in product_ids:
            product = products.get(product_id)
            if product is None:
                results.append((product_id, "not_found"))
                continue
            if product.status == "active":
                results.append((product_id, "already_active"))
                continue
            if not has_publishable_image(db, product.id):
                results.append((product_id, "skipped_no_images"))
                continue
            apply_product_update(  # calls ensure_publishable, and audits the status change
                db, actor, product, ProductUpdateRequest.model_validate({"status": "active"}), ctx
            )
            results.append((product_id, "activated"))
    return results


def photo_file_name(slug: str, sort_order: int) -> str:
    """The bulk upload file name for a product image position (sort_order 0 is position 1)."""
    position = sort_order + 1
    return f"{slug}.jpg" if position == 1 else f"{slug}__{position}.jpg"


def next_photo_file_name(product: Product) -> str:
    """The file name for the position after the product's highest product image."""
    taken = [image.sort_order for image in product.images if image.variant_id is None]
    return photo_file_name(product.slug, max(taken) + 1 if taken else 0)
