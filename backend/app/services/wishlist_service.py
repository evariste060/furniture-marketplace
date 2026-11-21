"""Customer wishlist (module 21, scope change SC-01 approved by the project owner 2026-10-27).

- Signed-in customers only (the router refuses staff accounts).
- Adding is idempotent: a saved product stays saved, nothing changes. Only a product sold right
  now (the public catalogue rule) can be added; anything else is 404 product_not_found.
- At most WISHLIST_LIMIT products (409 wishlist_full). The count is checked while holding the
  customer's row lock, so parallel adds cannot pass the limit.
- Removing is idempotent too. Products no longer sold stay in the list until removed.
- Not audited: a wishlist change has no business or security effect.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.db.transaction import atomic
from app.models import User
from app.models.engagement import WISHLIST_LIMIT
from app.repositories import catalog as catalog_repository
from app.repositories.user_repository import UserRepository
from app.repositories.wishlist_repository import WishlistRepository
from app.services import catalog as catalog_service

PRODUCT_NOT_FOUND = "Product not found."
WISHLIST_FULL = (
    f"Your wishlist is full ({WISHLIST_LIMIT} products). Remove a product to save another."
)


class WishlistService:
    @staticmethod
    def add(db: Session, user: User, product_id: uuid.UUID) -> int:
        with atomic(db):
            UserRepository.lock_by_id(db, user.id)
            if not WishlistRepository.contains(db, user.id, product_id):
                if not catalog_repository.public_product_exists(db, product_id):
                    raise NotFound(PRODUCT_NOT_FOUND, code="product_not_found")
                if WishlistRepository.count(db, user.id) >= WISHLIST_LIMIT:
                    raise Conflict(WISHLIST_FULL, code="wishlist_full")
                WishlistRepository.add(db, user.id, product_id)
            return WishlistRepository.count(db, user.id)

    @staticmethod
    def remove(db: Session, user: User, product_id: uuid.UUID) -> int:
        with atomic(db):
            WishlistRepository.remove(db, user.id, product_id)
            return WishlistRepository.count(db, user.id)

    @staticmethod
    def ids(db: Session, user: User) -> list[uuid.UUID]:
        return WishlistRepository.product_ids(db, user.id)

    @staticmethod
    def page(db: Session, user: User, page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        rows, total = WishlistRepository.page(db, user.id, page, size)
        public = catalog_repository.get_public_products_by_ids(db, [r.product_id for r in rows])
        summaries = {data["id"]: data for data in catalog_service.product_response_data(db, public)}
        storage = catalog_service.get_media_storage()
        items = []
        for row in rows:
            product = row.product
            first = min(product.images, key=lambda i: (i.sort_order, str(i.id)), default=None)
            items.append(
                {
                    "product_id": row.product_id,
                    "added_at": row.created_at,
                    "available": row.product_id in summaries,
                    "name": product.name,
                    "slug": product.slug,
                    "image": catalog_service.product_image_data(storage, first, product)
                    if first is not None
                    else None,
                    "product": summaries.get(row.product_id),
                }
            )
        return items, total
