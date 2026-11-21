"""Who a catalogue change or read is made for (ADR-014 phase 2, decision 5).

Every product, variant, image and stock function that can be reached by a seller takes a
CatalogScope, with no default, so no call can forget it:

- CatalogScope.platform(): platform staff (the Marketplace Administrator, SC-05), every store.
- CatalogScope.store(store_id): one seller's own store. The id comes from
  require_approved_seller (the caller's store, read from the database on every request), never
  from a request body or path. A product of another store is "not found" (404), exactly like a
  product that does not exist, so another store's catalogue is never revealed.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import true

from app.models import Product


@dataclass(frozen=True)
class CatalogScope:
    store_id: uuid.UUID | None

    @classmethod
    def platform(cls) -> "CatalogScope":
        return cls(None)

    @classmethod
    def store(cls, store_id: uuid.UUID) -> "CatalogScope":
        return cls(store_id)

    @property
    def is_platform(self) -> bool:
        return self.store_id is None

    def products(self) -> Any:
        """The SQL condition limiting products to this scope."""
        return true() if self.store_id is None else Product.store_id == self.store_id

    def owns(self, product: Product) -> bool:
        return self.store_id is None or product.store_id == self.store_id
