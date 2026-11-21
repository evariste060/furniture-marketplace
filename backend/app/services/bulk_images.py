"""Bulk product image upload (approved 2026-10-26, checkpoint 1b topics 4–6; 'catalog:manage').

File names say where each photo goes: "<product slug>.<ext>" is position 1 and
"<product slug>__<n>.<ext>" position n (1–99); the stem is lowercased before matching, the
extension is jpg, jpeg, png or webp. Position n is the product image with sort_order n - 1.

The request (start_bulk_upload):
- at most MAX_FILES files and MAX_REQUEST_BYTES in total (the size middleware); a file above
  5 MB rejects the whole request (413) before anything is stored, and so do more than 20 files
  (422); 507 when the incoming area holds more than MAX_INCOMING_BYTES or the disk has less
  than MIN_FREE_BYTES free;
- every name is resolved at once: invalid_filename, unknown_slug, and duplicate_position (two
  files for one product position: neither is applied) fail immediately, with no file stored;
- the other files are copied in chunks to private storage under incoming/<job>/<item>,
  registered in the media registry (they expire after INCOMING_TTL), and queued as items of a
  bulk_image_upload job (ADR-010). The response is the job (202).

The worker (process_item), per item, in (job, index) order and one product position at a time:
- decode and check the file (Pillow, as single uploads); invalid_image fails the item;
- if the image at that position has the same original (SHA-256), the item is 'unchanged';
- otherwise the new image is staged (media registry), then one transaction takes the product
  change lock, replaces the image at that position (same image row, new files; the old files
  are retired) or adds it, retires the incoming file, and writes one audit record per item:
  catalog.image_bulk_replace or catalog.image_bulk_add, with the job's creator as actor,
  request_id job:<id>, and the old and new media IDs and SHA-256s.
When the job finishes, catalog.image_bulk_complete records its counts.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, BinaryIO

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import InsufficientStorage, PayloadTooLarge, field_error
from app.db.transaction import atomic
from app.integrations.media import MediaStorage, get_media_storage, incoming_key
from app.models import MediaObject, Product, ProductImage
from app.models.identity import User
from app.models.jobs import Job, JobItem
from app.services import jobs
from app.services.audit_service import AuditService
from app.services.catalog import product_image_data
from app.services.catalog_admin import _lock
from app.services.image_processing import MAX_UPLOAD_BYTES, InvalidImage, process_image_limited
from app.services.media_registry import activate, discard_staged, retire, stage_image
from app.services.product_admin import PRODUCT_CHANGE_LOCK_KEY, ensure_publishable

JOB_TYPE = "bulk_image_upload"
MAX_FILES = 20
MAX_REQUEST_BYTES = 100 * 1024 * 1024
MAX_INCOMING_BYTES = 2 * 1024 * 1024 * 1024
MIN_FREE_BYTES = 1024 * 1024 * 1024
INCOMING_TTL = timedelta(days=7)
MAX_POSITION = 99
FILE_NAME = re.compile(
    r"^(?P<stem>.+?)(?:__(?P<n>[1-9]\d?))?\.(?P<ext>jpe?g|png|webp)$", re.IGNORECASE
)
CHUNK_BYTES = 1024 * 1024

TOO_MANY_FILES = f"Send at most {MAX_FILES} files per request; upload the rest in another batch."
FILE_TOO_LARGE = "These files are larger than 5 MB: {names}."
NO_ROOM = "The upload area is full; wait for running bulk uploads to finish, then try again."


@dataclass
class Upload:
    filename: str
    stream: BinaryIO
    size: int | None  # as reported by the multipart parser; checked again while copying


@dataclass(frozen=True)
class Placement:
    slug: str
    position: int


def parse_file_name(filename: str) -> Placement | None:
    """<slug>.<ext> is position 1, <slug>__<n>.<ext> position n; None if it does not match."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]  # some browsers send a path
    match = FILE_NAME.fullmatch(name)
    if match is None:
        return None
    return Placement(match["stem"].lower(), int(match["n"] or 1))


def expected_file_name(slug: str, position: int, extension: str = "jpg") -> str:
    """The file name that puts a photo at `position` (1-based) of the product `slug`."""
    return f"{slug}.{extension}" if position == 1 else f"{slug}__{position}.{extension}"


class _CountingReader:
    """Reads a stream in chunks, hashing and counting; stops above MAX_UPLOAD_BYTES."""

    def __init__(self, stream: BinaryIO, filename: str) -> None:
        self.stream = stream
        self.filename = filename
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self.stream.read(CHUNK_BYTES if size is None or size < 0 else size)
        self.size += len(chunk)
        if self.size > MAX_UPLOAD_BYTES:
            raise PayloadTooLarge(FILE_TOO_LARGE.format(names=self.filename))
        self.digest.update(chunk)
        return chunk


def _check_capacity(db: Session, storage: MediaStorage, incoming: int) -> None:
    held = db.scalar(
        select(func.coalesce(func.sum(MediaObject.bytes), 0)).where(
            MediaObject.kind == "incoming", MediaObject.state.in_(("pending", "active"))
        )
    )
    if int(held or 0) + incoming > MAX_INCOMING_BYTES:
        raise InsufficientStorage(NO_ROOM)
    free = storage.free_bytes()
    if free is not None and free - incoming < MIN_FREE_BYTES:
        raise InsufficientStorage(NO_ROOM)


def _failed_item(filename: str, code: str, message: str, **public: Any) -> jobs.NewItem:
    return jobs.NewItem(
        payload={"public": {"filename": filename, **public}},
        state="failed",
        error=f"{code}: {message}",
        result={"final": True, "outcome": code},
    )


def start_bulk_upload(
    db: Session, storage: MediaStorage, actor: User, uploads: list[Upload]
) -> Job:
    if len(uploads) > MAX_FILES:
        raise field_error(("body", "files"), TOO_MANY_FILES)
    if not uploads:
        raise field_error(("body", "files"), "Send at least one file.")
    oversized = [u.filename for u in uploads if u.size is not None and u.size > MAX_UPLOAD_BYTES]
    if oversized:
        raise PayloadTooLarge(
            FILE_TOO_LARGE.format(names=", ".join(oversized)), details={"files": oversized}
        )
    _check_capacity(db, storage, sum(u.size or 0 for u in uploads))

    placements = [parse_file_name(u.filename) for u in uploads]
    slugs = {p.slug for p in placements if p is not None}
    products = {
        product.slug: product
        for product in db.scalars(select(Product).where(Product.slug.in_(slugs)))
    }
    targets = Counter(
        (products[p.slug].id, p.position)
        for p in placements
        if p is not None and p.slug in products
    )

    job_id = uuid.uuid4()
    items: list[jobs.NewItem] = []
    queued: list[tuple[int, Upload, MediaObject]] = []
    for upload, placement in zip(uploads, placements, strict=True):
        if placement is None:
            items.append(
                _failed_item(
                    upload.filename,
                    "invalid_filename",
                    "Name the file <product-slug>.jpg or <product-slug>__<n>.jpg "
                    "(jpg, jpeg, png or webp).",
                )
            )
            continue
        product = products.get(placement.slug)
        public: dict[str, Any] = {
            "filename": upload.filename,
            "slug": placement.slug,
            "position": placement.position,
        }
        if product is None:
            items.append(
                _failed_item(
                    upload.filename,
                    "unknown_slug",
                    f"No product has the slug '{placement.slug}'.",
                    slug=placement.slug,
                    position=placement.position,
                )
            )
            continue
        public["product_name"] = product.name
        if targets[(product.id, placement.position)] > 1:
            items.append(
                _failed_item(
                    upload.filename,
                    "duplicate_position",
                    f"Another file in this upload is also for position {placement.position} of "
                    f"'{placement.slug}'; neither was applied.",
                    **{k: v for k, v in public.items() if k != "filename"},
                )
            )
            continue
        item_id = uuid.uuid4()
        media = MediaObject(
            storage_key=incoming_key(job_id, item_id),
            visibility="private",
            kind="incoming",
            state="pending",
            sha256="0" * 64,  # set once the file is copied
            bytes=0,
            content_type="application/octet-stream",
            owner_type="jobs",
            owner_id=job_id,
        )
        items.append(
            jobs.NewItem(
                payload={
                    "public": public,
                    "product_id": str(product.id),
                    "position": placement.position,
                    "item_id": str(item_id),
                },
                target=f"product:{product.id}:position:{placement.position}",
            )
        )
        queued.append((len(items) - 1, upload, media))

    # TX-A: register the incoming files, then copy them in chunks.
    with atomic(db):
        now: datetime = db.scalar(select(func.now()))  # type: ignore[assignment]
        expires = now + INCOMING_TTL
        for _, _, media in queued:
            media.delete_after = expires
            db.add(media)
        db.flush()
    written: list[MediaObject] = []
    try:
        for index, upload, media in queued:
            reader = _CountingReader(upload.stream, upload.filename)
            storage.put(
                media.storage_key,
                reader,  # type: ignore[arg-type]
                visibility="private",
                content_type="application/octet-stream",
            )
            written.append(media)
            media.sha256 = reader.digest.hexdigest()
            media.bytes = reader.size
            items[index].payload["incoming_media_id"] = str(media.id)
            items[index].payload["public"]["bytes"] = reader.size
        # TX-B: the job, its items, and the incoming files in use.
        with atomic(db):
            for media in written:
                media.state = "active"
            db.flush()
            job = jobs.create_job(db, JOB_TYPE, actor, items, job_id=job_id)
    except BaseException:
        _discard_incoming(db, storage, [media for _, _, media in queued])
        raise
    db.refresh(job)
    return job


def _discard_incoming(db: Session, storage: MediaStorage, media: list[MediaObject]) -> None:
    db.rollback()
    for item in media:
        try:
            storage.delete(item.storage_key, visibility="private")
        except Exception:  # noqa: BLE001 - left pending; the worker sweeps it
            return
    try:
        with atomic(db):
            ids = [m.id for m in media]
            if ids:
                db.execute(
                    delete(MediaObject).where(
                        MediaObject.id.in_(ids), MediaObject.state == "pending"
                    )
                )
    except Exception:  # noqa: BLE001
        return


# ---- the worker --------------------------------------------------------------------------------
def _retire_incoming(db: Session, media_id: uuid.UUID | None) -> None:
    with atomic(db):
        retire(db, [media_id])


def _image_at(
    db: Session, product_id: uuid.UUID, position: int, *, lock: bool
) -> ProductImage | None:
    query = select(ProductImage).where(
        ProductImage.product_id == product_id,
        ProductImage.variant_id.is_(None),
        ProductImage.sort_order == position - 1,
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def process_item(db: Session, job: Job, item: JobItem) -> dict[str, Any]:
    storage = get_media_storage()
    payload = item.payload
    public = dict(payload.get("public", {}))
    incoming_id = uuid.UUID(payload["incoming_media_id"])
    product_id = uuid.UUID(payload["product_id"])
    position = int(payload["position"])
    incoming = db.get(MediaObject, incoming_id)
    if incoming is None or incoming.state != "active":
        raise jobs.ItemFailed(
            "file_missing",
            "The uploaded file is no longer available (older than 7 days); upload it again.",
            {"final": True, "outcome": "file_missing", **public},
        )
    raw = storage.get(incoming.storage_key, visibility="private")
    try:
        processed = process_image_limited(raw)
    except InvalidImage as exc:
        _retire_incoming(db, incoming_id)
        raise jobs.ItemFailed(
            "invalid_image", str(exc), {"final": True, "outcome": "invalid_image", **public}
        ) from None
    sha = hashlib.sha256(raw).hexdigest()
    current = _image_at(db, product_id, position, lock=False)
    if current is not None and current.original_media.sha256 == sha:
        _retire_incoming(db, incoming_id)
        return {"outcome": "unchanged", "image_id": str(current.id), **public}
    db.rollback()

    staged = stage_image(db, storage, "products", product_id, processed)
    actor = db.get(User, job.created_by_user_id)
    try:
        with atomic(db):
            _lock(db, PRODUCT_CHANGE_LOCK_KEY)
            product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
            if product is None:
                raise jobs.ItemFailed(
                    "unknown_slug", "The product no longer exists.", {"final": True, **public}
                )
            existing = _image_at(db, product_id, position, lock=True)
            details: dict[str, Any] = {
                "job_id": job.id,
                "product_id": product_id,
                "slug": product.slug,
                "position": position,
                "new_media_id": staged.original_id,
                "new_sha256": staged.sha256,
            }
            if existing is not None:
                details["old_media_id"] = existing.original_media_id
                details["old_sha256"] = existing.original_media.sha256
                replaced: tuple[uuid.UUID | None, ...] = (
                    existing.public_media_id,
                    existing.original_media_id,
                )
                existing.public_media_id = staged.public_id
                existing.original_media_id = staged.original_id
                image = existing
                action, outcome = "catalog.image_bulk_replace", "replaced"
            else:
                image = ProductImage(
                    product_id=product_id,
                    public_media_id=staged.public_id,
                    original_media_id=staged.original_id,
                    sort_order=position - 1,
                )
                db.add(image)
                replaced = (None, None)
                action, outcome = "catalog.image_bulk_add", "added"
            activate(db, staged)
            db.flush()
            retire(db, [*replaced, incoming_id])
            if product.status == "active":
                ensure_publishable(db, product_id)  # the publication guard holds after the change
            AuditService.log_event(
                db=db,
                action=action,
                status="success",
                actor=actor,
                entity_type="product_image",
                entity_id=image.id,
                details=details,
                request_id=jobs.job_context(job),
            )
    except BaseException:
        discard_staged(db, storage, staged)
        raise
    db.refresh(image)
    url = product_image_data(storage, image, product)["url"]
    return {"outcome": outcome, "image_id": str(image.id), "url": url, **public}


def on_finished(db: Session, job: Job) -> None:
    outcomes = Counter(
        (item.result or {}).get("outcome", item.state)
        for item in db.scalars(select(JobItem).where(JobItem.job_id == job.id))
    )
    AuditService.log_event(
        db=db,
        action="catalog.image_bulk_complete",
        status="success" if job.failed_items == 0 else "partial",
        actor=db.get(User, job.created_by_user_id),
        entity_type="job",
        entity_id=job.id,
        details={
            "job_id": job.id,
            "total": job.total_items,
            "succeeded": job.succeeded_items,
            "failed": job.failed_items,
            "added": outcomes.get("added", 0),
            "replaced": outcomes.get("replaced", 0),
            "unchanged": outcomes.get("unchanged", 0),
        },
        request_id=jobs.job_context(job),
    )


jobs.HANDLERS[JOB_TYPE] = jobs.JobHandler(process_item, on_finished)
