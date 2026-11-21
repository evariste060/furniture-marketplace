"""Thumbnails for cart and order lines (frontend phase 4, 2026-10-27).

A line shows its variant's first image, else its product's first product-level image, else
none. The image is read live (order lines' image_snapshot column is not used): it is for
display only, and a removed image simply disappears.
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.integrations.media import get_media_storage
from app.models import Product, ProductImage, ProductVariant
from app.schemas.images import PublicImage
from app.services.media_registry import public_image


def line_images(
    db: Session, variant_ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, PublicImage]:
    """The thumbnail of each variant that has one."""
    ids = {variant_id for variant_id in variant_ids if variant_id is not None}
    if not ids:
        return {}
    rows = db.execute(
        select(ProductVariant.id, ProductImage, Product.name)
        .join(Product, Product.id == ProductVariant.product_id)
        .join(
            ProductImage,
            (ProductImage.product_id == ProductVariant.product_id)
            & or_(ProductImage.variant_id == ProductVariant.id, ProductImage.variant_id.is_(None)),
        )
        .where(ProductVariant.id.in_(ids))
        # The variant's own images first, then the product's; each in display order.
        .order_by(
            ProductVariant.id,
            ProductImage.variant_id.is_(None),
            ProductImage.sort_order,
            ProductImage.id,
        )
    ).all()
    storage = get_media_storage()
    images: dict[uuid.UUID, PublicImage] = {}
    for variant_id, image, product_name in rows:
        if variant_id not in images:
            images[variant_id] = PublicImage(
                **public_image(storage, image.public_media, image.alt_text or product_name, 0)
            )
    return images
