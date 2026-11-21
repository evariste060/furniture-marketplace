"""Staff category and brand management (module 5, RE-018; 'catalog:manage').

Rules:
- Slugs are generated from the name when none is sent (app.core.slugs: lowercase ASCII,
  hyphens, smallest free -N suffix). An explicitly sent slug must be unused (409 slug_taken).
  A rename keeps the existing slug, so public URLs only change when a new slug is sent.
- A category cannot become its own ancestor, directly or through any descendant (409).
- The tree has at most two levels, main category then subcategory (category hierarchy,
  2026-11-16): a parent must be a main category, and a category with subcategories cannot be
  moved under another one (422 on parent_id).
- PUT /staff/categories/order renumbers the categories under one parent (or the main categories)
  1, 2, 3, ... in the order sent; the list must hold every one of them exactly once (409
  category_order_mismatch otherwise, e.g. after a concurrent change).
- DELETE removes a category only when no product uses it and it has no child categories, and a
  brand only when no product uses it (409 *_in_use). Otherwise deactivate with is_active=false.
- Every successful change commits together with its audit record (app.db.transaction.atomic);
  a request that changes nothing is not audited.
- Brand categories (ADR-012 decision 9, 2026-11-17): a brand belongs to one or more main
  categories, chosen when it is added (422 on category_ids for a missing category or a
  subcategory). Sending category_ids on update replaces them. When a main category is moved
  under another one, its brands move to that new main category, so no brand loses its category.
  Deleting a category removes its links.
- Images (B1, ADR-009): a category has at most one image and a brand one logo, stored like
  product images (private original plus public source under one new key). Uploading replaces the
  current one. Files are tracked in the media registry (app.services.media_registry): new files
  are registered and written before the row changes and discarded if the request fails; the
  files of a replaced or removed image, and of a deleted category or brand, are retired in the
  same transaction and deleted later by the cleanup worker (python -m app.worker).

Concurrency: every category change takes one transaction-scoped advisory lock (brands their
own), so slug allocation, the ancestor walk and the in-use checks cannot race each other. The
row being changed is also locked FOR UPDATE, which blocks a concurrent product insert that
references it until this transaction ends. The unique slug constraints and RESTRICT foreign keys
remain the final guard: a slug unique violation is reported as 409 slug_taken, and a delete
refused by a foreign key as 409 *_in_use. The catalogue keys are ON DELETE RESTRICT, which
PostgreSQL reports as restrict_violation (SQLSTATE 23001); a NO ACTION key reports
foreign_key_violation (23503). Any other integrity error is re-raised.
"""

import logging
import uuid
from typing import Any, Literal

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, field_error
from app.core.request_context import RequestContext
from app.core.slugs import first_free_slug, slugify
from app.db.transaction import atomic
from app.integrations.media import MediaStorage, Owner
from app.models import Brand, BrandCategory, Category, CategoryMenuBrand, Product
from app.models.identity import User
from app.repositories.category_tree import MAX_CATEGORY_DEPTH, category_depth, subtree_height
from app.schemas.catalog_admin import (
    SLUG_MAX_LENGTH,
    BrandCreateRequest,
    BrandUpdateRequest,
    CategoryCreateRequest,
    CategoryMenuBrandsRequest,
    CategoryOrderRequest,
    CategoryUpdateRequest,
)
from app.services.audit_service import AuditService
from app.services.image_processing import ProcessedImage
from app.services.media_registry import activate, discard_staged, retire, stage_image

logger = logging.getLogger("app.media")

# pg_advisory_xact_lock(bigint) keys; 7_302_116_001 is the staff-change lock.
CATEGORY_CHANGE_LOCK_KEY = 7_302_116_002
BRAND_CHANGE_LOCK_KEY = 7_302_116_003
# PostgreSQL SQLSTATEs for a delete refused by a referencing foreign key.
FOREIGN_KEY_VIOLATION = "23503"  # NO ACTION keys
RESTRICT_VIOLATION = "23001"  # ON DELETE RESTRICT keys (every catalogue reference, ADR-002)
REFERENCED_ROW_STATES = frozenset({FOREIGN_KEY_VIOLATION, RESTRICT_VIOLATION})

CATEGORY_NOT_FOUND = "Category not found."
BRAND_NOT_FOUND = "Brand not found."
SLUG_TAKEN = "This slug is already used by another {entity}."
CATEGORY_CYCLE = "A category cannot be moved under itself or one of its subcategories."
PARENT_NOT_MAIN = "A subcategory can only be placed under a main category."
HAS_SUBCATEGORIES = "A category with subcategories can only be a main category."
CATEGORY_ORDER_MISMATCH = (
    "List every category under this parent exactly once; reload the categories and try again."
)
MENU_BRANDS_MAIN_ONLY = "Only a main category has a menu brand list."
MENU_BRAND_NOT_FOUND = "Brand not found."
MENU_BRAND_HIDDEN = "This brand is hidden; show it before adding it to a menu."
BRAND_CATEGORY_NOT_FOUND = "Category not found."
BRAND_CATEGORY_NOT_MAIN = "A brand belongs to main categories; choose the main category."
BRAND_CATEGORY_IN_MENU = (
    "This brand is in the store menu of {name}; take it off that menu before removing the category."
)
TOP_LEVEL = "top-level"  # audit entity_id of a reorder of the main categories
CATEGORY_IN_USE = (
    "The category still has products or subcategories; deactivate it with is_active=false."
)
BRAND_IN_USE = "The brand still has products; deactivate it with is_active=false."
NO_SLUG_FROM_NAME = "The name has no letters or digits to build a slug from; send a slug."

Model = type[Category] | type[Brand]
ImageField = Literal["image", "logo"]  # categories.image_* and brands.logo_*


def _lock(db: Session, key: int) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def _slug_taken(db: Session, model: Model, slug: str, exclude_id: uuid.UUID | None) -> bool:
    query = select(model.id).where(model.slug == slug)
    if exclude_id is not None:
        query = query.where(model.id != exclude_id)
    return db.scalar(query.limit(1)) is not None


def _generated_slug(db: Session, model: Model, name: str) -> str:
    base = slugify(name, SLUG_MAX_LENGTH)
    if not base:
        raise field_error(("body", "name"), NO_SLUG_FROM_NAME)
    return first_free_slug(base, lambda s: _slug_taken(db, model, s, None), SLUG_MAX_LENGTH)


def _explicit_slug(
    db: Session, model: Model, slug: str, exclude_id: uuid.UUID | None, entity: str
) -> str:
    if _slug_taken(db, model, slug, exclude_id):
        raise Conflict(SLUG_TAKEN.format(entity=entity), code="slug_taken")
    return slug


def _locked_category(db: Session, category_id: uuid.UUID) -> Category:
    category = db.scalar(select(Category).where(Category.id == category_id).with_for_update())
    if category is None:
        raise NotFound(CATEGORY_NOT_FOUND, code="category_not_found")
    return category


def _locked_brand(db: Session, brand_id: uuid.UUID) -> Brand:
    brand = db.scalar(select(Brand).where(Brand.id == brand_id).with_for_update())
    if brand is None:
        raise NotFound(BRAND_NOT_FOUND, code="brand_not_found")
    return brand


def _check_parent(db: Session, category_id: uuid.UUID | None, parent_id: uuid.UUID) -> None:
    """The parent exists and is neither the category itself nor one of its descendants."""
    if parent_id == category_id:
        raise Conflict(CATEGORY_CYCLE, code="category_cycle")
    if db.scalar(select(Category.id).where(Category.id == parent_id)) is None:
        raise field_error(("body", "parent_id"), "Parent category not found.")
    if category_id is not None:
        seen: set[uuid.UUID] = set()
        ancestor: uuid.UUID | None = parent_id
        while ancestor is not None and ancestor not in seen:
            if ancestor == category_id:
                raise Conflict(CATEGORY_CYCLE, code="category_cycle")
            seen.add(ancestor)
            ancestor = db.scalar(select(Category.parent_id).where(Category.id == ancestor))
    _check_depth(db, category_id, parent_id)


def _check_depth(db: Session, category_id: uuid.UUID | None, parent_id: uuid.UUID) -> None:
    """The category (with everything below it) still fits in MAX_CATEGORY_DEPTH levels."""
    height = subtree_height(db, category_id) if category_id is not None else 1
    if category_depth(db, parent_id) + height <= MAX_CATEGORY_DEPTH:
        return
    message = HAS_SUBCATEGORIES if height > 1 else PARENT_NOT_MAIN
    raise field_error(("body", "parent_id"), message)


def _check_spotlight_product(db: Session, category_id: uuid.UUID, product_id: uuid.UUID) -> None:
    """The product exists and is in the category or one of its subcategories."""
    ancestor = db.scalar(select(Product.category_id).where(Product.id == product_id))
    if ancestor is None:
        raise field_error(("body", "spotlight_product_id"), "Product not found.")
    seen: set[uuid.UUID] = set()
    while ancestor is not None and ancestor not in seen:
        if ancestor == category_id:
            return
        seen.add(ancestor)
        ancestor = db.scalar(select(Category.parent_id).where(Category.id == ancestor))
    raise field_error(
        ("body", "spotlight_product_id"),
        "The product is not in this category or its subcategories.",
    )


def _changes(row: Any, values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Apply the values that differ from the row; return {field: {from, to}} for the audit."""
    changes = {}
    for field, new in values.items():
        old = getattr(row, field)
        if old != new:
            changes[field] = {"from": old, "to": new}
            setattr(row, field, new)
    return changes


def _audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str,
    actor: User,
    ctx: RequestContext,
    details: dict[str, Any],
) -> None:
    AuditService.log_event(
        db=db,
        action=action,
        status="success",
        actor=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        context=ctx,
        details=details,
    )


def _sqlstate(exc: IntegrityError) -> str | None:
    """SQLSTATE of the driver error. psycopg 3 sets it on the exception and on its diagnostics;
    anything else (no driver error, another driver) gives None."""
    orig = getattr(exc, "orig", None)
    state = getattr(orig, "sqlstate", None) or getattr(
        getattr(orig, "diag", None), "sqlstate", None
    )
    return state if isinstance(state, str) else None


def _category_usage(db: Session, category_id: uuid.UUID) -> tuple[int, int]:
    """(products, child categories) that reference the category."""
    products = db.scalar(select(func.count(Product.id)).where(Product.category_id == category_id))
    children = db.scalar(select(func.count(Category.id)).where(Category.parent_id == category_id))
    return int(products or 0), int(children or 0)


def _brand_usage(db: Session, brand_id: uuid.UUID) -> int:
    """Products that reference the brand."""
    return int(db.scalar(select(func.count(Product.id)).where(Product.brand_id == brand_id)) or 0)


def _delete_row(db: Session, model: Model, row_id: uuid.UUID) -> None:
    """DELETE in SQL, not session.delete(): the ORM would first set referencing products'
    brand_id (or category_id) to NULL. A plain DELETE lets the RESTRICT foreign keys refuse."""
    db.execute(delete(model).where(model.id == row_id))


def _is_slug_violation(exc: IntegrityError) -> bool:
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
    return "slug" in constraint


def brand_category_ids(db: Session, brand_id: uuid.UUID) -> list[uuid.UUID]:
    """The main categories a brand belongs to, in tree order (sort order, then name)."""
    return list(
        db.scalars(
            select(BrandCategory.category_id)
            .join(Category, Category.id == BrandCategory.category_id)
            .where(BrandCategory.brand_id == brand_id)
            .order_by(Category.sort_order, Category.name)
        )
    )


def _check_brand_categories(db: Session, category_ids: list[uuid.UUID]) -> None:
    """Every id must be an existing main category. FOR SHARE: a concurrent move under another
    category or a delete waits for this transaction."""
    parents = dict(
        db.execute(
            select(Category.id, Category.parent_id)
            .where(Category.id.in_(category_ids))
            .with_for_update(read=True)
        ).all()
    )
    for category_id in category_ids:
        if category_id not in parents:
            raise field_error(("body", "category_ids"), BRAND_CATEGORY_NOT_FOUND)
        if parents[category_id] is not None:
            raise field_error(("body", "category_ids"), BRAND_CATEGORY_NOT_MAIN)


def _set_brand_categories(db: Session, brand_id: uuid.UUID, category_ids: list[uuid.UUID]) -> None:
    db.execute(delete(BrandCategory).where(BrandCategory.brand_id == brand_id))
    db.flush()
    db.add_all(BrandCategory(brand_id=brand_id, category_id=c) for c in category_ids)
    db.flush()


def _link_brands(
    db: Session, category_id: uuid.UUID, brand_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """A brand in a main category's store menu belongs to that category: link the ones that are
    not yet. Returns the brands linked."""
    have = set(
        db.scalars(
            select(BrandCategory.brand_id).where(
                BrandCategory.category_id == category_id, BrandCategory.brand_id.in_(brand_ids)
            )
        )
    )
    added = [b for b in brand_ids if b not in have]
    db.add_all(BrandCategory(brand_id=b, category_id=category_id) for b in added)
    db.flush()
    return added


def _check_menu_links(db: Session, brand_id: uuid.UUID, removed: set[uuid.UUID]) -> None:
    """A category cannot be taken from a brand while that category's store menu lists it."""
    if not removed:
        return
    listed = db.scalars(
        select(Category.name)
        .join(CategoryMenuBrand, CategoryMenuBrand.category_id == Category.id)
        .where(CategoryMenuBrand.brand_id == brand_id, Category.id.in_(removed))
        .order_by(Category.sort_order, Category.name)
    ).first()
    if listed is not None:
        raise field_error(("body", "category_ids"), BRAND_CATEGORY_IN_MENU.format(name=listed))


def _move_brand_links(db: Session, from_id: uuid.UUID, to_id: uuid.UUID) -> list[uuid.UUID]:
    """A main category becoming a subcategory of `to_id`: its brands now belong to `to_id`.
    Returns the brands moved."""
    moved = list(
        db.scalars(select(BrandCategory.brand_id).where(BrandCategory.category_id == from_id))
    )
    if not moved:
        return []
    already = set(
        db.scalars(
            select(BrandCategory.brand_id).where(
                BrandCategory.category_id == to_id, BrandCategory.brand_id.in_(moved)
            )
        )
    )
    db.execute(delete(BrandCategory).where(BrandCategory.category_id == from_id))
    db.add_all(BrandCategory(brand_id=b, category_id=to_id) for b in moved if b not in already)
    db.flush()
    return moved


class CatalogAdminService:
    # ---- categories ---------------------------------------------------------------------------
    @staticmethod
    def create_category(
        db: Session, actor: User, req: CategoryCreateRequest, ctx: RequestContext
    ) -> Category:
        try:
            with atomic(db):
                _lock(db, CATEGORY_CHANGE_LOCK_KEY)
                if req.parent_id is not None:
                    _check_parent(db, None, req.parent_id)
                slug = (
                    _explicit_slug(db, Category, req.slug, None, "category")
                    if req.slug is not None
                    else _generated_slug(db, Category, req.name)
                )
                category = Category(
                    name=req.name,
                    slug=slug,
                    parent_id=req.parent_id,
                    sort_order=req.sort_order,
                    is_active=req.is_active,
                    description=req.description,
                )
                db.add(category)
                db.flush()
                _audit(
                    db,
                    "catalog.category_create",
                    "category",
                    category.id,
                    actor,
                    ctx,
                    {
                        "name": category.name,
                        "slug": category.slug,
                        "parent_id": category.parent_id,
                        "sort_order": category.sort_order,
                        "is_active": category.is_active,
                        "description": category.description,
                    },
                )
        except IntegrityError as exc:
            if not _is_slug_violation(exc):
                raise
            raise Conflict(SLUG_TAKEN.format(entity="category"), code="slug_taken") from None
        return category

    @staticmethod
    def update_category(
        db: Session,
        actor: User,
        category_id: uuid.UUID,
        req: CategoryUpdateRequest,
        ctx: RequestContext,
    ) -> Category:
        fields = req.model_fields_set
        try:
            with atomic(db):
                _lock(db, CATEGORY_CHANGE_LOCK_KEY)
                category = _locked_category(db, category_id)
                values = {f: getattr(req, f) for f in fields}
                if req.slug is not None and req.slug != category.slug:
                    _explicit_slug(db, Category, req.slug, category.id, "category")
                if "parent_id" in fields and req.parent_id not in (None, category.parent_id):
                    assert req.parent_id is not None
                    _check_parent(db, category.id, req.parent_id)
                if req.spotlight_product_id not in (None, category.spotlight_product_id):
                    assert req.spotlight_product_id is not None
                    _check_spotlight_product(db, category.id, req.spotlight_product_id)
                becomes_sub = (
                    "parent_id" in fields
                    and req.parent_id is not None
                    and category.parent_id is None
                )
                changes = _changes(category, values)
                if not changes:
                    return category  # nothing changed: no write, no audit
                db.flush()
                if becomes_sub:
                    assert req.parent_id is not None
                    moved = _move_brand_links(db, category.id, req.parent_id)
                    if moved:
                        changes["brands_moved_to_parent"] = {"from": None, "to": moved}
                _audit(
                    db,
                    "catalog.category_update",
                    "category",
                    category.id,
                    actor,
                    ctx,
                    {"changes": changes},
                )
        except IntegrityError as exc:
            if not _is_slug_violation(exc):
                raise
            raise Conflict(SLUG_TAKEN.format(entity="category"), code="slug_taken") from None
        return category

    @staticmethod
    def delete_category(
        db: Session, actor: User, category_id: uuid.UUID, ctx: RequestContext
    ) -> None:
        try:
            with atomic(db):
                _lock(db, CATEGORY_CHANGE_LOCK_KEY)
                category = _locked_category(db, category_id)
                products, children = _category_usage(db, category.id)
                if products or children:
                    raise Conflict(
                        CATEGORY_IN_USE,
                        code="category_in_use",
                        details={"products": products, "child_categories": children},
                    )
                details = {"name": category.name, "slug": category.slug}
                media = (category.image_media_id, category.image_original_media_id)
                _delete_row(db, Category, category.id)
                retire(db, media)  # the cleanup worker deletes the image files
                _audit(db, "catalog.category_delete", "category", category_id, actor, ctx, details)
        except IntegrityError as exc:
            if _sqlstate(exc) not in REFERENCED_ROW_STATES:
                raise
            raise Conflict(CATEGORY_IN_USE, code="category_in_use") from None

    @staticmethod
    def reorder_categories(
        db: Session, actor: User, req: CategoryOrderRequest, ctx: RequestContext
    ) -> None:
        """sort_order 1, 2, 3, ... for the categories under req.parent_id, in the order sent.
        Only the rows whose position changes are written; nothing changed: no audit."""
        with atomic(db):
            _lock(db, CATEGORY_CHANGE_LOCK_KEY)
            if req.parent_id is not None and db.get(Category, req.parent_id) is None:
                raise field_error(("body", "parent_id"), "Parent category not found.")
            siblings = {
                c.id: c
                for c in db.scalars(
                    select(Category).where(Category.parent_id == req.parent_id).with_for_update()
                    if req.parent_id is not None
                    else select(Category).where(Category.parent_id.is_(None)).with_for_update()
                )
            }
            if set(siblings) != set(req.category_ids):
                raise Conflict(CATEGORY_ORDER_MISMATCH, code="category_order_mismatch")
            changes = []
            for position, category_id in enumerate(req.category_ids, start=1):
                category = siblings[category_id]
                if category.sort_order != position:
                    changes.append({"id": category_id, "from": category.sort_order, "to": position})
                    category.sort_order = position
            if not changes:
                return
            db.flush()
            _audit(
                db,
                "catalog.category_reorder",
                "category",
                req.parent_id or TOP_LEVEL,
                actor,
                ctx,
                {"parent_id": req.parent_id, "changes": changes},
            )

    @staticmethod
    def set_menu_brands(
        db: Session,
        actor: User,
        category_id: uuid.UUID,
        req: CategoryMenuBrandsRequest,
        ctx: RequestContext,
    ) -> list[uuid.UUID]:
        """Replace a main category's menu brand list (ADR-012 amendment, 2026-11-16) and return
        it. Every brand must exist; a brand that is not already listed must be active (hidden
        ones stay listed but the storefront leaves them out). A listed brand belongs to the
        category (ADR-012 decision 9): the ones not linked yet are linked. Nothing changed: no
        audit."""
        with atomic(db):
            _lock(db, CATEGORY_CHANGE_LOCK_KEY)
            category = _locked_category(db, category_id)
            if category.parent_id is not None:
                raise field_error(("body", "brand_ids"), MENU_BRANDS_MAIN_ONLY)
            current = list(
                db.scalars(
                    select(CategoryMenuBrand.brand_id)
                    .where(CategoryMenuBrand.category_id == category_id)
                    .order_by(CategoryMenuBrand.position)
                )
            )
            wanted = list(req.brand_ids)
            if wanted == current:
                return current
            # FOR SHARE: a concurrent delete or deactivation of these brands waits for this.
            active = dict(
                db.execute(
                    select(Brand.id, Brand.is_active)
                    .where(Brand.id.in_(wanted))
                    .with_for_update(read=True)
                ).all()
            )
            for brand_id in wanted:
                if brand_id not in active:
                    raise field_error(("body", "brand_ids"), MENU_BRAND_NOT_FOUND)
                if not active[brand_id] and brand_id not in current:
                    raise field_error(("body", "brand_ids"), MENU_BRAND_HIDDEN)
            db.execute(
                delete(CategoryMenuBrand).where(CategoryMenuBrand.category_id == category_id)
            )
            db.flush()
            db.add_all(
                CategoryMenuBrand(category_id=category_id, brand_id=brand_id, position=position)
                for position, brand_id in enumerate(wanted, start=1)
            )
            db.flush()
            linked = _link_brands(db, category_id, wanted)
            summary: dict[str, object] = {"from": current, "to": wanted}
            if linked:
                summary["brands_linked"] = linked
            _audit(
                db,
                "catalog.category_menu_brands",
                "category",
                category_id,
                actor,
                ctx,
                summary,
            )
        return wanted

    # ---- brands -------------------------------------------------------------------------------
    @staticmethod
    def create_brand(
        db: Session, actor: User, req: BrandCreateRequest, ctx: RequestContext
    ) -> Brand:
        try:
            with atomic(db):
                _lock(db, BRAND_CHANGE_LOCK_KEY)
                slug = (
                    _explicit_slug(db, Brand, req.slug, None, "brand")
                    if req.slug is not None
                    else _generated_slug(db, Brand, req.name)
                )
                _check_brand_categories(db, req.category_ids)
                brand = Brand(name=req.name, slug=slug, is_active=req.is_active)
                db.add(brand)
                db.flush()
                _set_brand_categories(db, brand.id, req.category_ids)
                _audit(
                    db,
                    "catalog.brand_create",
                    "brand",
                    brand.id,
                    actor,
                    ctx,
                    {
                        "name": brand.name,
                        "slug": brand.slug,
                        "is_active": brand.is_active,
                        "category_ids": req.category_ids,
                    },
                )
        except IntegrityError as exc:
            if not _is_slug_violation(exc):
                raise
            raise Conflict(SLUG_TAKEN.format(entity="brand"), code="slug_taken") from None
        return brand

    @staticmethod
    def update_brand(
        db: Session,
        actor: User,
        brand_id: uuid.UUID,
        req: BrandUpdateRequest,
        ctx: RequestContext,
    ) -> Brand:
        try:
            with atomic(db):
                _lock(db, BRAND_CHANGE_LOCK_KEY)
                brand = _locked_brand(db, brand_id)
                if req.slug is not None and req.slug != brand.slug:
                    _explicit_slug(db, Brand, req.slug, brand.id, "brand")
                fields = req.model_fields_set - {"category_ids"}
                changes = _changes(brand, {f: getattr(req, f) for f in fields})
                if req.category_ids is not None:
                    current = brand_category_ids(db, brand.id)
                    if set(req.category_ids) != set(current):
                        # Store menus change under the category lock (taken after the brand
                        # lock, as nowhere takes them the other way round).
                        _lock(db, CATEGORY_CHANGE_LOCK_KEY)
                        _check_brand_categories(db, req.category_ids)
                        _check_menu_links(db, brand.id, set(current) - set(req.category_ids))
                        _set_brand_categories(db, brand.id, req.category_ids)
                        changes["category_ids"] = {"from": current, "to": req.category_ids}
                if not changes:
                    return brand  # nothing changed: no write, no audit
                db.flush()
                _audit(
                    db, "catalog.brand_update", "brand", brand.id, actor, ctx, {"changes": changes}
                )
        except IntegrityError as exc:
            if not _is_slug_violation(exc):
                raise
            raise Conflict(SLUG_TAKEN.format(entity="brand"), code="slug_taken") from None
        return brand

    @staticmethod
    def delete_brand(db: Session, actor: User, brand_id: uuid.UUID, ctx: RequestContext) -> None:
        try:
            with atomic(db):
                _lock(db, BRAND_CHANGE_LOCK_KEY)
                brand = _locked_brand(db, brand_id)
                products = _brand_usage(db, brand.id)
                if products:
                    raise Conflict(
                        BRAND_IN_USE, code="brand_in_use", details={"products": products}
                    )
                details = {"name": brand.name, "slug": brand.slug}
                media = (brand.logo_media_id, brand.logo_original_media_id)
                _delete_row(db, Brand, brand.id)
                retire(db, media)  # the cleanup worker deletes the logo files
                _audit(db, "catalog.brand_delete", "brand", brand_id, actor, ctx, details)
        except IntegrityError as exc:
            if _sqlstate(exc) not in REFERENCED_ROW_STATES:
                raise
            raise Conflict(BRAND_IN_USE, code="brand_in_use") from None

    # ---- category images and brand logos (B1) ------------------------------------------------
    @staticmethod
    def set_category_image(
        db: Session,
        storage: MediaStorage,
        actor: User,
        category_id: uuid.UUID,
        processed: ProcessedImage,
        upload_bytes: int,
        ctx: RequestContext,
    ) -> Category:
        category = _set_image(
            db, storage, actor, ctx, Category, category_id, "image", processed, upload_bytes
        )
        assert isinstance(category, Category)
        return category

    @staticmethod
    def remove_category_image(
        db: Session, actor: User, category_id: uuid.UUID, ctx: RequestContext
    ) -> Category:
        category = _remove_image(db, actor, ctx, Category, category_id, "image")
        assert isinstance(category, Category)
        return category

    @staticmethod
    def set_brand_logo(
        db: Session,
        storage: MediaStorage,
        actor: User,
        brand_id: uuid.UUID,
        processed: ProcessedImage,
        upload_bytes: int,
        ctx: RequestContext,
    ) -> Brand:
        brand = _set_image(
            db, storage, actor, ctx, Brand, brand_id, "logo", processed, upload_bytes
        )
        assert isinstance(brand, Brand)
        return brand

    @staticmethod
    def remove_brand_logo(
        db: Session, actor: User, brand_id: uuid.UUID, ctx: RequestContext
    ) -> Brand:
        brand = _remove_image(db, actor, ctx, Brand, brand_id, "logo")
        assert isinstance(brand, Brand)
        return brand


def _locked(db: Session, model: Model, row_id: uuid.UUID) -> Category | Brand:
    if model is Category:
        _lock(db, CATEGORY_CHANGE_LOCK_KEY)
        return _locked_category(db, row_id)
    _lock(db, BRAND_CHANGE_LOCK_KEY)
    return _locked_brand(db, row_id)


def _entity(model: Model) -> str:
    return "category" if model is Category else "brand"


def _set_image(
    db: Session,
    storage: MediaStorage,
    actor: User,
    ctx: RequestContext,
    model: Model,
    row_id: uuid.UUID,
    field: ImageField,
    processed: ProcessedImage,
    upload_bytes: int,
) -> Category | Brand:
    """Stage the new image (TX-A, files), then point the row at it and retire the replaced
    image (TX-B). The replaced files stay until the cleanup worker removes them."""
    entity = _entity(model)
    owner: Owner = "categories" if model is Category else "brands"
    with atomic(db):  # 404 before anything is stored
        _locked(db, model, row_id)
    staged = stage_image(db, storage, owner, row_id, processed)
    try:
        with atomic(db):
            row = _locked(db, model, row_id)
            previous = getattr(row, f"{field}_media")
            replaced = (
                getattr(row, f"{field}_media_id"),
                getattr(row, f"{field}_original_media_id"),
            )
            setattr(row, f"{field}_media_id", staged.public_id)
            setattr(row, f"{field}_original_media_id", staged.original_id)
            activate(db, staged)
            retire(db, replaced)
            db.flush()
            _audit(
                db,
                f"catalog.{entity}_{field}_upload",
                entity,
                row.id,
                actor,
                ctx,
                {
                    "image_ref": staged.key,
                    "sha256": staged.sha256,
                    "replaced_image_ref": previous.storage_key if previous else None,
                    "width": staged.width,
                    "height": staged.height,
                    "content_type": staged.content_type,
                    "upload_bytes": upload_bytes,
                },
            )
    except BaseException:
        discard_staged(db, storage, staged)
        raise
    db.refresh(row)
    return row


def _remove_image(
    db: Session,
    actor: User,
    ctx: RequestContext,
    model: Model,
    row_id: uuid.UUID,
    field: ImageField,
) -> Category | Brand:
    """Clear the row's image and retire its files. Nothing to remove: no write, no audit."""
    entity = _entity(model)
    with atomic(db):
        row = _locked(db, model, row_id)
        previous = getattr(row, f"{field}_media")
        if previous is None:
            return row
        retired = (
            getattr(row, f"{field}_media_id"),
            getattr(row, f"{field}_original_media_id"),
        )
        setattr(row, f"{field}_media_id", None)
        setattr(row, f"{field}_original_media_id", None)
        db.flush()
        retire(db, retired)
        _audit(
            db,
            f"catalog.{entity}_{field}_delete",
            entity,
            row.id,
            actor,
            ctx,
            {"image_ref": previous.storage_key},
        )
    db.refresh(row)
    return row
