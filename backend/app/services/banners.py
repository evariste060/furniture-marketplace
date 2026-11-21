"""Homepage banners (approved 2026-10-26, checkpoint 1b topic 9; 'content:manage').

Rules:
- A banner is created inactive; it can be activated only with an image (409
  banner_needs_image), and the image of an active banner cannot be removed (409).
- The public list (GET /banners) has the active banners whose window holds now, evaluated in
  SQL with now(): (starts_at IS NULL OR starts_at <= now()) AND (ends_at IS NULL OR
  now() < ends_at), ordered by position, then creation. The storefront shows the first.
- Images use the media registry like category images (owner "banners"); a replaced or removed
  image, or a deleted banner's image, is retired and deleted by the worker.
- Every change is audited with before and after values: content.banner_create,
  content.banner_update, content.banner_delete, content.banner_image_upload,
  content.banner_image_delete. A request that changes nothing is not audited.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.integrations.media import MediaStorage
from app.models.content import Banner
from app.models.identity import User
from app.schemas.banners import (
    BannerCreateRequest,
    BannerUpdateRequest,
    cta_problem,
    window_problem,
)
from app.services.audit_service import AuditService
from app.services.image_processing import ProcessedImage
from app.services.media_registry import activate, discard_staged, retire, stage_image

BANNER_NOT_FOUND = "Banner not found."
NEEDS_IMAGE = "A banner needs an image before it can be active; upload one first."
ACTIVE_IMAGE = "Deactivate the banner before removing its image."
TEXT_FIELDS = (
    "title_en",
    "title_rw",
    "overline_en",
    "overline_rw",
    "subtitle_en",
    "subtitle_rw",
    "cta_label_en",
    "cta_label_rw",
    "cta_url",
)
FIELDS = (*TEXT_FIELDS, "position", "is_active", "starts_at", "ends_at")


def shown_now():
    """SQL condition: the banner is active and its window holds now()."""
    now = func.now()
    return and_(
        Banner.is_active.is_(True),
        or_(Banner.starts_at.is_(None), Banner.starts_at <= now),
        or_(Banner.ends_at.is_(None), now < Banner.ends_at),
    )


def list_public(db: Session, page: int, size: int) -> tuple[list[Banner], int]:
    condition = shown_now()
    total = db.scalar(select(func.count(Banner.id)).where(condition)) or 0
    rows = db.scalars(
        select(Banner)
        .where(condition)
        .order_by(Banner.position, Banner.created_at, Banner.id)
        .offset((page - 1) * size)
        .limit(size)
    )
    return list(rows), total


def list_staff(db: Session, page: int, size: int) -> tuple[list[tuple[Banner, bool]], int]:
    total = db.scalar(select(func.count(Banner.id))) or 0
    rows = db.execute(
        select(Banner, shown_now())
        .order_by(Banner.position, Banner.created_at, Banner.id)
        .offset((page - 1) * size)
        .limit(size)
    )
    return [(cast(Banner, banner), bool(shown)) for banner, shown in rows], total


def is_shown_now(db: Session, banner_id: uuid.UUID) -> bool:
    return bool(db.scalar(select(shown_now()).where(Banner.id == banner_id)))


def _locked(db: Session, banner_id: uuid.UUID) -> Banner:
    banner = db.scalar(select(Banner).where(Banner.id == banner_id).with_for_update())
    if banner is None:
        raise NotFound(BANNER_NOT_FOUND, code="banner_not_found")
    return banner


def _snapshot(banner: Banner) -> dict[str, Any]:
    return {field: getattr(banner, field) for field in FIELDS}


def _audit(
    db: Session,
    action: str,
    banner_id: uuid.UUID,
    actor: User,
    ctx: RequestContext,
    details: dict[str, Any],
) -> None:
    AuditService.log_event(
        db=db,
        action=action,
        status="success",
        actor=actor,
        entity_type="banner",
        entity_id=banner_id,
        context=ctx,
        details=details,
    )


class BannerService:
    @staticmethod
    def create(db: Session, actor: User, req: BannerCreateRequest, ctx: RequestContext) -> Banner:
        with atomic(db):
            banner = Banner(**req.model_dump(), is_active=False)
            db.add(banner)
            db.flush()
            _audit(db, "content.banner_create", banner.id, actor, ctx, {"after": _snapshot(banner)})
        return banner

    @staticmethod
    def update(
        db: Session,
        actor: User,
        banner_id: uuid.UUID,
        req: BannerUpdateRequest,
        ctx: RequestContext,
    ) -> Banner:
        with atomic(db):
            banner = _locked(db, banner_id)
            before = _snapshot(banner)
            for field in req.model_fields_set:
                setattr(banner, field, getattr(req, field))
            problem = window_problem(banner.starts_at, banner.ends_at) or cta_problem(
                banner.cta_url, banner.cta_label_en, banner.cta_label_rw
            )
            if problem:
                raise Conflict(problem, code="banner_invalid")
            if banner.is_active and banner.image_media_id is None:
                raise Conflict(NEEDS_IMAGE, code="banner_needs_image")
            after = _snapshot(banner)
            changed = {
                f: {"from": before[f], "to": after[f]} for f in FIELDS if before[f] != after[f]
            }
            if not changed:
                return banner  # nothing changed: no write, no audit
            db.flush()
            _audit(db, "content.banner_update", banner.id, actor, ctx, {"changes": changed})
        return banner

    @staticmethod
    def delete(db: Session, actor: User, banner_id: uuid.UUID, ctx: RequestContext) -> None:
        with atomic(db):
            banner = _locked(db, banner_id)
            before = _snapshot(banner)
            media = (banner.image_media_id, banner.image_original_media_id)
            db.delete(banner)
            db.flush()
            retire(db, media)  # the worker deletes the image files
            _audit(db, "content.banner_delete", banner_id, actor, ctx, {"before": before})

    @staticmethod
    def set_image(
        db: Session,
        storage: MediaStorage,
        actor: User,
        banner_id: uuid.UUID,
        processed: ProcessedImage,
        upload_bytes: int,
        ctx: RequestContext,
    ) -> Banner:
        with atomic(db):  # 404 before anything is stored
            _locked(db, banner_id)
        staged = stage_image(db, storage, "banners", banner_id, processed)
        try:
            with atomic(db):
                banner = _locked(db, banner_id)
                previous = banner.image_media
                replaced = (banner.image_media_id, banner.image_original_media_id)
                banner.image_media_id = staged.public_id
                banner.image_original_media_id = staged.original_id
                activate(db, staged)
                retire(db, replaced)
                db.flush()
                _audit(
                    db,
                    "content.banner_image_upload",
                    banner.id,
                    actor,
                    ctx,
                    {
                        "image_ref": staged.key,
                        "sha256": staged.sha256,
                        "replaced_image_ref": previous.storage_key if previous else None,
                        "width": staged.width,
                        "height": staged.height,
                        "upload_bytes": upload_bytes,
                    },
                )
        except BaseException:
            discard_staged(db, storage, staged)
            raise
        db.refresh(banner)
        return banner

    @staticmethod
    def remove_image(db: Session, actor: User, banner_id: uuid.UUID, ctx: RequestContext) -> Banner:
        with atomic(db):
            banner = _locked(db, banner_id)
            previous = banner.image_media
            if previous is None:
                return banner
            if banner.is_active:
                raise Conflict(ACTIVE_IMAGE, code="banner_needs_image")
            retired = (banner.image_media_id, banner.image_original_media_id)
            banner.image_media_id = None
            banner.image_original_media_id = None
            db.flush()
            retire(db, retired)
            _audit(
                db,
                "content.banner_image_delete",
                banner.id,
                actor,
                ctx,
                {"image_ref": previous.storage_key},
            )
        db.refresh(banner)
        return banner
