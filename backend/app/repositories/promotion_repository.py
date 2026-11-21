"""Promotion queries (module 13). Repositories only flush; services commit."""

import uuid
from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Category,
    Discount,
    DiscountRedemption,
    DiscountTarget,
    Product,
    ProductVariant,
)


def by_code(db: Session, code: str) -> Discount | None:
    """Codes are stored upper-case; callers pass the upper-cased code."""
    return db.scalar(select(Discount).where(Discount.code == code))


def get(db: Session, discount_id: uuid.UUID, *, lock: bool = False) -> Discount | None:
    query = select(Discount).where(Discount.id == discount_id)
    if lock:  # and refresh a copy already loaded in this session
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def code_taken(db: Session, code: str, exclude_id: uuid.UUID | None = None) -> bool:
    query = select(Discount.id).where(Discount.code == code)
    if exclude_id is not None:
        query = query.where(Discount.id != exclude_id)
    return db.scalar(query.limit(1)) is not None


def page(db: Session, *, status: str | None, offset: int, limit: int) -> tuple[list[Discount], int]:
    query = select(Discount)
    count = select(func.count(Discount.id))
    if status is not None:
        query = query.where(Discount.status == status)
        count = count.where(Discount.status == status)
    rows = db.scalars(
        query.order_by(Discount.created_at.desc(), Discount.id).offset(offset).limit(limit)
    )
    return list(rows), int(db.scalar(count) or 0)


def targets(db: Session, discount_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[DiscountTarget]]:
    found: dict[uuid.UUID, list[DiscountTarget]] = defaultdict(list)
    if discount_ids:
        query = (
            select(DiscountTarget)
            .where(DiscountTarget.discount_id.in_(discount_ids))
            .order_by(DiscountTarget.created_at, DiscountTarget.id)
        )
        for target in db.scalars(query):
            found[target.discount_id].append(target)
    return found


def active_redemption_counts(db: Session, discount_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not discount_ids:
        return {}
    query = (
        select(DiscountRedemption.discount_id, func.count(DiscountRedemption.id))
        .where(
            DiscountRedemption.discount_id.in_(discount_ids),
            DiscountRedemption.status == "active",
        )
        .group_by(DiscountRedemption.discount_id)
    )
    return {discount_id: int(count) for discount_id, count in db.execute(query)}


def active_customer_redemptions(
    db: Session, discount_id: uuid.UUID, *, user_id: uuid.UUID | None, phones: set[str]
) -> int:
    """Active uses by one customer: by account or any of its phones for a registered customer,
    by phone for a guest (§7 Q26)."""
    identity = []
    if user_id is not None:
        identity.append(DiscountRedemption.user_id == user_id)
    if phones:
        identity.append(DiscountRedemption.customer_phone.in_(sorted(phones)))
    if not identity:
        return 0
    query = select(func.count(DiscountRedemption.id)).where(
        DiscountRedemption.discount_id == discount_id,
        DiscountRedemption.status == "active",
        or_(*identity),
    )
    return int(db.scalar(query) or 0)


def category_with_descendants(db: Session, category_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """The categories and every subcategory below them (recursive; cycles are refused by the
    catalogue service and by UNION's duplicate removal)."""
    if not category_ids:
        return set()
    seed = select(Category.id.label("id")).where(Category.id.in_(category_ids))
    tree = seed.cte("category_tree", recursive=True)
    tree = tree.union(select(Category.id).where(Category.parent_id == tree.c.id))
    return set(db.scalars(select(tree.c.id)))


def variant_facts(
    db: Session, variant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID | None, uuid.UUID]]:
    """(product_id, brand_id, category_id) of each variant."""
    if not variant_ids:
        return {}
    query = (
        select(ProductVariant.id, Product.id, Product.brand_id, Product.category_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(ProductVariant.id.in_(variant_ids))
    )
    return {row[0]: (row[1], row[2], row[3]) for row in db.execute(query)}


def existing(db: Session, model, ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    return set(db.scalars(select(model.id).where(model.id.in_(ids))))
