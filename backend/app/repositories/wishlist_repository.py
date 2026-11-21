"""Wishlist rows (module 21). Methods stage changes in the caller's transaction."""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from app.models import Product, ProductImage, WishlistItem
from app.schemas.pagination import page_offset


class WishlistRepository:
    @staticmethod
    def count(db: Session, user_id: uuid.UUID) -> int:
        return db.scalar(select(func.count()).where(WishlistItem.user_id == user_id)) or 0

    @staticmethod
    def contains(db: Session, user_id: uuid.UUID, product_id: uuid.UUID) -> bool:
        return (
            db.scalar(
                select(WishlistItem.id).where(
                    WishlistItem.user_id == user_id, WishlistItem.product_id == product_id
                )
            )
            is not None
        )

    @staticmethod
    def add(db: Session, user_id: uuid.UUID, product_id: uuid.UUID) -> None:
        """Insert once; a row that already exists is left as it is."""
        db.execute(
            insert(WishlistItem)
            .values(id=uuid.uuid4(), user_id=user_id, product_id=product_id)
            .on_conflict_do_nothing(index_elements=["user_id", "product_id"])
        )

    @staticmethod
    def remove(db: Session, user_id: uuid.UUID, product_id: uuid.UUID) -> None:
        db.execute(
            delete(WishlistItem).where(
                WishlistItem.user_id == user_id, WishlistItem.product_id == product_id
            )
        )

    @staticmethod
    def product_ids(db: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
        """Every saved product ID, newest first."""
        return list(
            db.scalars(
                select(WishlistItem.product_id)
                .where(WishlistItem.user_id == user_id)
                .order_by(WishlistItem.created_at.desc(), WishlistItem.id.desc())
            )
        )

    @staticmethod
    def page(
        db: Session, user_id: uuid.UUID, page: int, size: int
    ) -> tuple[list[WishlistItem], int]:
        """One page of saved items, newest first, each with its product and product images
        (any status: a product no longer sold is still shown by name)."""
        total = WishlistRepository.count(db, user_id)
        rows = list(
            db.scalars(
                select(WishlistItem)
                .where(WishlistItem.user_id == user_id)
                .options(
                    selectinload(WishlistItem.product).selectinload(
                        Product.images.and_(ProductImage.variant_id.is_(None))
                    )
                )
                .order_by(WishlistItem.created_at.desc(), WishlistItem.id.desc())
                .offset(page_offset(page, size))
                .limit(size)
            )
        )
        return rows, total
