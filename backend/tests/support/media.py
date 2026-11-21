"""Image rows for tests, registered in the media registry like real uploads (ADR-009)."""

import hashlib
import uuid

from app.models import MediaObject, ProductImage


def media_pair(
    key: str, owner_type: str, owner_id: uuid.UUID, width: int = 800, height: int = 600
) -> tuple[MediaObject, MediaObject]:
    """(public source, original) objects for one image key, both active. No file is written."""
    digest = hashlib.sha256(key.encode()).hexdigest()
    common = {
        "storage_key": key,
        "state": "active",
        "sha256": digest,
        "bytes": 1000,
        "content_type": "image/jpeg",
        "owner_type": owner_type,
        "owner_id": owner_id,
    }
    public = MediaObject(
        visibility="public", kind="public_source", width=width, height=height, **common
    )
    original = MediaObject(visibility="private", kind="original", **common)
    return public, original


def image_row(
    product_id: uuid.UUID | None,
    sort_order: int = 0,
    *,
    key: str | None = None,
    variant_id: uuid.UUID | None = None,
    width: int = 800,
    height: int = 600,
    alt_text: str | None = None,
) -> ProductImage:
    """A product image with its media objects (added to the session with it). product_id may be
    None when the image is attached through a relationship before the product is flushed."""
    owner_id = product_id or uuid.uuid4()
    key = key or f"products/{owner_id}/{uuid.uuid4().hex}-{'a' * 12}.jpg"
    public, original = media_pair(key, "products", owner_id, width, height)
    return ProductImage(
        product_id=product_id,
        variant_id=variant_id,
        public_media=public,
        original_media=original,
        sort_order=sort_order,
        alt_text=alt_text,
    )
