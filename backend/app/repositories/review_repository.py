"""Queries for review links and product reviews (module 20)."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Product
from app.models.commerce import Order, OrderItem, OrderStatusHistory
from app.models.engagement import ProductReview, ReviewToken
from app.schemas.pagination import page_offset


class ReviewRepository:
    @staticmethod
    def delivered_at(db: Session, order_id: uuid.UUID) -> datetime | None:
        """When the order was marked delivered (its latest 'delivered' history row)."""
        return db.scalar(
            select(func.max(OrderStatusHistory.created_at)).where(
                OrderStatusHistory.order_id == order_id, OrderStatusHistory.status == "delivered"
            )
        )

    @staticmethod
    def review_exists(db: Session, order_item_id: uuid.UUID) -> bool:
        return (
            db.scalar(select(ProductReview.id).where(ProductReview.order_item_id == order_item_id))
            is not None
        )

    @staticmethod
    def token_for_item(db: Session, order_item_id: uuid.UUID) -> ReviewToken | None:
        return db.scalar(
            select(ReviewToken).where(ReviewToken.order_item_id == order_item_id).with_for_update()
        )

    @staticmethod
    def upsert_unused_token(
        db: Session, order_item_id: uuid.UUID, token_hash: str, expires_at: datetime
    ) -> bool:
        """Store a new hash for the item's link unless the link was already used. Returns
        False when the existing link is used (nothing changed)."""
        stmt = (
            insert(ReviewToken)
            .values(
                id=uuid.uuid4(),
                order_item_id=order_item_id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                constraint="review_token_order_item",
                set_={"token_hash": token_hash, "expires_at": expires_at, "updated_at": func.now()},
                where=ReviewToken.used_at.is_(None),
            )
            .returning(ReviewToken.id)
        )
        return db.execute(stmt).scalar_one_or_none() is not None

    @staticmethod
    def token_by_hash(db: Session, token_hash: str, *, lock: bool = False) -> ReviewToken | None:
        stmt = select(ReviewToken).where(ReviewToken.token_hash == token_hash)
        return db.scalar(stmt.with_for_update() if lock else stmt)

    @staticmethod
    def item_with_order(db: Session, order_item_id: uuid.UUID) -> tuple[OrderItem, Order]:
        row = db.execute(
            select(OrderItem, Order)
            .join(Order, Order.id == OrderItem.order_id)
            .where(OrderItem.id == order_item_id)
        ).one()
        return row[0], row[1]

    @staticmethod
    def lock_review(db: Session, review_id: uuid.UUID) -> ProductReview | None:
        return db.scalar(
            select(ProductReview).where(ProductReview.id == review_id).with_for_update()
        )

    @staticmethod
    def lock_product(db: Session, product_id: uuid.UUID) -> Product:
        return db.scalars(select(Product).where(Product.id == product_id).with_for_update()).one()

    @staticmethod
    def approved_distribution(db: Session, product_id: uuid.UUID) -> dict[int, int]:
        rows = db.execute(
            select(ProductReview.rating, func.count())
            .where(ProductReview.product_id == product_id, ProductReview.status == "approved")
            .group_by(ProductReview.rating)
        ).all()
        return {int(rating): int(count) for rating, count in rows}

    @staticmethod
    def approved_page(
        db: Session, product_id: uuid.UUID, page: int, size: int
    ) -> tuple[list[ProductReview], int]:
        where = (ProductReview.product_id == product_id, ProductReview.status == "approved")
        total = db.scalar(select(func.count()).select_from(ProductReview).where(*where)) or 0
        items = list(
            db.scalars(
                select(ProductReview)
                .where(*where)
                .order_by(ProductReview.created_at.desc(), ProductReview.id)
                .offset(page_offset(page, size))
                .limit(size)
            )
        )
        return items, total

    @staticmethod
    def staff_row(db: Session, review_id: uuid.UUID) -> tuple[ProductReview, Product, Order]:
        row = db.execute(
            select(ProductReview, Product, Order)
            .join(Product, Product.id == ProductReview.product_id)
            .join(OrderItem, OrderItem.id == ProductReview.order_item_id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(ProductReview.id == review_id)
        ).one()
        return row[0], row[1], row[2]

    @staticmethod
    def staff_page(
        db: Session, status: str | None, page: int, size: int
    ) -> tuple[list[tuple[ProductReview, Product, Order]], int]:
        base = (
            select(ProductReview, Product, Order)
            .join(Product, Product.id == ProductReview.product_id)
            .join(OrderItem, OrderItem.id == ProductReview.order_item_id)
            .join(Order, Order.id == OrderItem.order_id)
        )
        count = select(func.count()).select_from(ProductReview)
        if status is not None:
            base = base.where(ProductReview.status == status)
            count = count.where(ProductReview.status == status)
        total = db.scalar(count) or 0
        rows = db.execute(
            base.order_by(ProductReview.created_at.desc(), ProductReview.id)
            .offset(page_offset(page, size))
            .limit(size)
        ).all()
        return [(r[0], r[1], r[2]) for r in rows], total
