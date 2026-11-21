"""Catalogue test helpers."""

import uuid

from sqlalchemy import update

from app.db.session import get_db
from app.main import app
from app.models import Product


def force_status(product_id: str | uuid.UUID, status: str = "active") -> None:
    """Set a product's status directly in the test database, bypassing the publication guard
    (2026-10-26). For tests about something else that need an active product without images:
    the state the guard leaves alone for products that were already active."""
    db = next(app.dependency_overrides[get_db]())
    db.execute(
        update(Product).where(Product.id == uuid.UUID(str(product_id))).values(status=status)
    )
    db.commit()
