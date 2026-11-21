"""Staff product image management (module 7; 'catalog:manage').

Rules:
- An upload must decode as JPEG, PNG or WebP and be at most 5 MB (app.services.image_processing);
  the file name and declared content type are ignored. Larger uploads get 413 file_too_large,
  anything else invalid 422. It is stored twice under one new key (ADR-009): the exact original
  (private) and a sanitised public source in the same format.
- variant_id must be a variant of the same product (422 otherwise; an inactive variant is
  allowed). PATCH variant_id: null makes the image product-level.
- A new image goes after the product's highest sort_order; PATCH may set any value >= 0 that no
  other product image of the product has (409 sort_order_taken; one product image per position
  since 2026-10-26, so a bulk upload file name "<slug>__<n>" names one image). The public
  catalogue orders by (sort_order, id).
- Publication guard (app.services.product_admin.ensure_publishable): the last product image of
  an active product cannot be deleted or moved to a variant (409 last_product_image).
- Reorder (PUT .../images/order) lists every product-level image of the product once; they get
  positions 0..n-1 in that order (so file names "<slug>__<n>" follow the new order). Variant
  images keep theirs. Two passes (above every current position, then the final ones) keep the
  unique position index satisfied row by row.
- Every change commits with its audit record; a request that changes nothing is not audited.

Files and the database (media registry, app.services.media_registry):
- Upload: the image is decoded before any transaction (in a limited processing slot). Its two
  files are registered as pending (committed), written, and only then linked to the new row in
  a second transaction that activates them. If that fails, the files and registry rows are
  discarded best-effort; anything left is swept by the cleanup worker.
- Delete: the row is removed and its files retired in one transaction; the cleanup worker
  (python -m app.worker) deletes the files afterwards.

Concurrency: every image change takes the product-change advisory lock (shared with products
and variants), so concurrent uploads cannot pick the same next sort_order.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, PayloadTooLarge, field_error
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.integrations.media import MediaStorage
from app.models import Product, ProductImage, ProductVariant
from app.models.identity import User
from app.schemas.image_admin import SORT_ORDER_MAX, ImageOrderRequest, ImageUpdateRequest
from app.services.catalog_admin import _audit, _changes, _lock
from app.services.image_processing import (
    MAX_UPLOAD_BYTES,
    InvalidImage,
    ProcessedImage,
    process_image_limited,
)
from app.services.media_registry import activate, discard_staged, retire, stage_image
from app.services.product_admin import PRODUCT_CHANGE_LOCK_KEY, ensure_publishable

logger = logging.getLogger("app.media")

IMAGE_NOT_FOUND = "Image not found."
PRODUCT_NOT_FOUND = "Product not found."
FILE_TOO_LARGE = "The image is larger than 5 MB."
VARIANT_MISMATCH = "The variant does not belong to this product."
POSITION_TAKEN = "Another image of this product already has this sort_order."
POSITION_INDEX = "uq_product_images_product_position"
ORDER_MISMATCH = "List every product image of this product exactly once."


def _check_variant(db: Session, product_id: uuid.UUID, variant_id: uuid.UUID) -> None:
    owner = db.scalar(select(ProductVariant.product_id).where(ProductVariant.id == variant_id))
    if owner != product_id:  # also covers an unknown variant, with the same message
        raise field_error(("body", "variant_id"), VARIANT_MISMATCH)


def _check_product(db: Session, product_id: uuid.UUID, variant_id: uuid.UUID | None) -> Product:
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if product is None:
        raise NotFound(PRODUCT_NOT_FOUND, code="product_not_found")
    if variant_id is not None:
        _check_variant(db, product.id, variant_id)
    return product


def _guard_removal(db: Session, image: ProductImage) -> None:
    """An active product keeps at least one product image (the publication guard)."""
    status = db.scalar(select(Product.status).where(Product.id == image.product_id))
    if status == "active":
        ensure_publishable(db, image.product_id, excluding_image_id=image.id)


def _locked_image(db: Session, image_id: uuid.UUID) -> ProductImage:
    image = db.scalar(select(ProductImage).where(ProductImage.id == image_id).with_for_update())
    if image is None:
        raise NotFound(IMAGE_NOT_FOUND, code="image_not_found")
    return image


def read_upload(stream: Any) -> bytes:
    """Read at most MAX_UPLOAD_BYTES + 1 bytes, so an oversized file is never read whole."""
    data = stream.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise PayloadTooLarge(FILE_TOO_LARGE)
    return bytes(data)


def processed_upload(raw: bytes) -> ProcessedImage:
    """Decode and check an upload (one processing slot); 422 on the `file` field if invalid."""
    try:
        return process_image_limited(raw)
    except InvalidImage as exc:
        raise field_error(("body", "file"), str(exc)) from None


class ImageAdminService:
    @staticmethod
    def upload(
        db: Session,
        storage: MediaStorage,
        actor: User,
        product_id: uuid.UUID,
        raw: bytes,
        variant_id: uuid.UUID | None,
        alt_text: str | None,
        ctx: RequestContext,
    ) -> ProductImage:
        processed = processed_upload(raw)
        with atomic(db):  # 404 and variant checks before anything is stored
            _check_product(db, product_id, variant_id)
        staged = stage_image(db, storage, "products", product_id, processed)
        try:
            with atomic(db):
                _lock(db, PRODUCT_CHANGE_LOCK_KEY)
                product = _check_product(db, product_id, variant_id)
                highest = db.scalar(
                    select(func.max(ProductImage.sort_order)).where(
                        ProductImage.product_id == product.id
                    )
                )
                sort_order = 0 if highest is None else highest + 1
                if sort_order > SORT_ORDER_MAX:
                    raise Conflict("No higher sort_order is available.", code="sort_order_full")
                image = ProductImage(
                    product_id=product.id,
                    variant_id=variant_id,
                    public_media_id=staged.public_id,
                    original_media_id=staged.original_id,
                    alt_text=alt_text,
                    sort_order=sort_order,
                )
                db.add(image)
                activate(db, staged)
                db.flush()
                _audit(
                    db,
                    "catalog.image_upload",
                    "product_image",
                    image.id,
                    actor,
                    ctx,
                    {
                        "product_id": product.id,
                        "variant_id": variant_id,
                        "image_ref": staged.key,
                        "sha256": staged.sha256,
                        "width": staged.width,
                        "height": staged.height,
                        "content_type": staged.content_type,
                        "upload_bytes": len(raw),
                        "sort_order": sort_order,
                    },
                )
        except BaseException:
            discard_staged(db, storage, staged)
            raise
        db.refresh(image)
        return image

    @staticmethod
    def update(
        db: Session,
        actor: User,
        image_id: uuid.UUID,
        req: ImageUpdateRequest,
        ctx: RequestContext,
    ) -> ProductImage:
        fields = req.model_fields_set
        try:
            with atomic(db):
                _lock(db, PRODUCT_CHANGE_LOCK_KEY)
                image = _locked_image(db, image_id)
                if "variant_id" in fields and req.variant_id is not None:
                    _check_variant(db, image.product_id, req.variant_id)
                    if image.variant_id is None:  # it stops being a product image
                        _guard_removal(db, image)
                changes = _changes(image, {f: getattr(req, f) for f in fields})
                if not changes:
                    return image  # nothing changed: no write, no audit
                db.flush()
                _audit(
                    db,
                    "catalog.image_update",
                    "product_image",
                    image.id,
                    actor,
                    ctx,
                    {"product_id": image.product_id, "changes": changes},
                )
        except IntegrityError as exc:
            if POSITION_INDEX not in str(exc.orig):
                raise
            raise Conflict(POSITION_TAKEN, code="sort_order_taken") from None
        return image

    @staticmethod
    def delete(
        db: Session,
        actor: User,
        image_id: uuid.UUID,
        ctx: RequestContext,
    ) -> None:
        with atomic(db):
            _lock(db, PRODUCT_CHANGE_LOCK_KEY)
            image = _locked_image(db, image_id)
            if image.variant_id is None:
                _guard_removal(db, image)
            media = (image.public_media_id, image.original_media_id)
            details = {"product_id": image.product_id, "image_ref": image.storage_key}
            db.execute(delete(ProductImage).where(ProductImage.id == image.id))
            retire(db, media)  # the cleanup worker deletes the files
            _audit(db, "catalog.image_delete", "product_image", image_id, actor, ctx, details)

    @staticmethod
    def reorder(
        db: Session,
        actor: User,
        product_id: uuid.UUID,
        req: ImageOrderRequest,
        ctx: RequestContext,
    ) -> list[ProductImage]:
        """Put the product's product-level images in the requested order (positions 0..n-1)."""
        with atomic(db):
            _lock(db, PRODUCT_CHANGE_LOCK_KEY)
            _check_product(db, product_id, None)
            images = list(
                db.scalars(
                    select(ProductImage)
                    .where(ProductImage.product_id == product_id, ProductImage.variant_id.is_(None))
                    .order_by(ProductImage.sort_order, ProductImage.id)
                    .with_for_update()
                )
            )
            by_id = {image.id: image for image in images}
            if set(req.image_ids) != set(by_id):
                raise field_error(("body", "image_ids"), ORDER_MISMATCH)
            wanted = [by_id[image_id] for image_id in req.image_ids]
            if all(image.sort_order == i for i, image in enumerate(wanted)):
                return wanted  # already in this order: no write, no audit
            above = max(max(image.sort_order for image in images), len(images) - 1) + 1
            if above + len(images) > SORT_ORDER_MAX:
                raise Conflict("No higher sort_order is available.", code="sort_order_full")
            before = [str(image.id) for image in images]
            for i, image in enumerate(wanted):  # pass 1: above every current position
                image.sort_order = above + i
            db.flush()
            for i, image in enumerate(wanted):  # pass 2: the final positions, now all free
                image.sort_order = i
            db.flush()
            _audit(
                db,
                "catalog.image_reorder",
                "product",
                product_id,
                actor,
                ctx,
                {"from": before, "to": [str(image_id) for image_id in req.image_ids]},
            )
        return wanted
