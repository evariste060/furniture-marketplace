"""Store lookups (ADR-014). Repositories only read and flush; services own the transaction."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.marketplace import Store


class StoreRepository:
    @staticmethod
    def get_by_owner(
        db: Session, owner_user_id: uuid.UUID, *, for_update: bool = False
    ) -> Store | None:
        query = select(Store).where(Store.owner_user_id == owner_user_id)
        if for_update:
            query = query.with_for_update()
        return db.scalar(query)

    @staticmethod
    def get(db: Session, store_id: uuid.UUID, *, for_update: bool = False) -> Store | None:
        query = select(Store).where(Store.id == store_id)
        if for_update:
            query = query.with_for_update()
        return db.scalar(query)

    @staticmethod
    def name_taken(db: Session, name: str, *, excluding: uuid.UUID | None = None) -> bool:
        """Whether another store already uses this name, ignoring letter case."""
        query = select(Store.id).where(func.lower(Store.name) == name.lower())
        if excluding is not None:
            query = query.where(Store.id != excluding)
        return db.scalar(query.limit(1)) is not None

    @staticmethod
    def slug_taken(db: Session, slug: str, *, excluding: uuid.UUID | None = None) -> bool:
        query = select(Store.id).where(Store.slug == slug)
        if excluding is not None:
            query = query.where(Store.id != excluding)
        return db.scalar(query.limit(1)) is not None
