"""Homepage banners (approved 2026-10-26, checkpoint 1b topic 9).

GET /banners is public: the banners shown now, by position (the storefront shows the first one;
with none it shows its default hero), cached for 60 seconds. The staff routes need
'content:manage' (administrator). Rules are in app.services.banners.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.image_admin import TOO_LARGE_413, UPLOAD_422
from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import (
    ERR,
    FORBIDDEN_403,
    UNAUTHORIZED_401,
    VALIDATION_422,
    ResponseMap,
)
from app.core.dependencies import require_permission
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.integrations.media import MediaStorage, get_media_storage
from app.models.content import Banner
from app.models.identity import User
from app.schemas.banners import (
    BannerCreateRequest,
    BannerUpdateRequest,
    LocalizedText,
    PublicBanner,
    StaffBannerResponse,
)
from app.schemas.images import PublicImage
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.services import banners as banner_service
from app.services.banners import BannerService
from app.services.image_admin import processed_upload, read_upload
from app.services.media_registry import public_image

public_router = APIRouter(prefix="/banners", tags=["Storefront Content"])
staff_router = APIRouter(prefix="/staff/banners", tags=["Staff Content"])

PUBLIC_CACHE = "public, max-age=60"
GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
BANNER_404: ResponseMap = {404: {**ERR, "description": "banner_not_found"}}
BANNER_409: ResponseMap = {
    409: {
        **ERR,
        "description": "banner_needs_image: activation needs an image, and an active banner "
        "keeps it; banner_invalid: the result would break a rule (window or CTA label)",
    }
}
ContentManager = Annotated[User, Depends(require_permission(Permission.CONTENT_MANAGE))]
Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
Storage = Annotated[MediaStorage, Depends(get_media_storage)]
PERMISSION_NOTE = "Requires 'content:manage' (administrator)."


def _image(storage: MediaStorage, banner: Banner) -> PublicImage | None:
    if banner.image_media is None:
        return None
    return PublicImage.model_validate(public_image(storage, banner.image_media, banner.title_en, 0))


def _pair(en: str | None, rw: str | None) -> LocalizedText | None:
    return None if en is None and rw is None else LocalizedText(en=en, rw=rw)


def _public(banner: Banner, storage: MediaStorage) -> PublicBanner:
    image = _image(storage, banner)
    assert image is not None  # an active banner always has an image (database check)
    return PublicBanner(
        id=banner.id,
        title=LocalizedText(en=banner.title_en, rw=banner.title_rw),
        overline=_pair(banner.overline_en, banner.overline_rw),
        subtitle=_pair(banner.subtitle_en, banner.subtitle_rw),
        cta_label=_pair(banner.cta_label_en, banner.cta_label_rw),
        cta_url=banner.cta_url,
        image=image,
        starts_at=banner.starts_at,
        ends_at=banner.ends_at,
    )


def _staff(banner: Banner, storage: MediaStorage, shown: bool) -> StaffBannerResponse:
    response = StaffBannerResponse.model_validate(banner)
    response.image = _image(storage, banner)
    response.shown_now = shown
    return response


@public_router.get(
    "",
    response_model=Page[PublicBanner],
    summary="Homepage banners shown now",
    description=(
        "Public. Active banners whose window holds now (starts_at <= now < ends_at; null is "
        "open-ended), by position. The storefront shows the first one. Text is plain text in "
        "English and Kinyarwanda; `cta_url` is an on-site path. Cached for 60 seconds."
    ),
    responses=VALIDATION_422,
)
def list_banners(
    response: Response,
    db: Db,
    storage: Storage,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
) -> Page[PublicBanner]:
    rows, total = banner_service.list_public(db, page, size)
    response.headers["Cache-Control"] = PUBLIC_CACHE
    items = [_public(banner, storage) for banner in rows]
    return Page[PublicBanner](items=items, total=total, page=page, size=size)


@staff_router.get(
    "",
    response_model=Page[StaffBannerResponse],
    summary="Every banner, scheduled and inactive included",
    description=f"{PERMISSION_NOTE} By position. `shown_now` tells which are live.",
    responses={**GUARDED, **VALIDATION_422},
)
def list_staff_banners(
    current_user: ContentManager,
    db: Db,
    storage: Storage,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
) -> Page[StaffBannerResponse]:
    rows, total = banner_service.list_staff(db, page, size)
    items = [_staff(banner, storage, shown) for banner, shown in rows]
    return Page[StaffBannerResponse](items=items, total=total, page=page, size=size)


@staff_router.post(
    "",
    response_model=StaffBannerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a banner (inactive)",
    description=(
        f"{PERMISSION_NOTE} Created inactive; upload its image, then PATCH is_active: true. "
        "Audited as 'content.banner_create' with its values."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def create_banner(
    req: BannerCreateRequest, current_user: ContentManager, db: Db, ctx: Ctx, storage: Storage
) -> StaffBannerResponse:
    banner = BannerService.create(db, current_user, req, ctx)
    return _staff(banner, storage, False)


@staff_router.patch(
    "/{banner_id}",
    response_model=StaffBannerResponse,
    summary="Update or activate a banner",
    description=(
        f"{PERMISSION_NOTE} Partial update; nullable fields accept null to clear them. "
        "Activation needs an image. Audited as 'content.banner_update' with old and new values."
    ),
    responses={**GUARDED, **BANNER_404, **BANNER_409, **VALIDATION_422},
)
def update_banner(
    banner_id: uuid.UUID,
    req: BannerUpdateRequest,
    current_user: ContentManager,
    db: Db,
    ctx: Ctx,
    storage: Storage,
) -> StaffBannerResponse:
    banner = BannerService.update(db, current_user, banner_id, req, ctx)
    return _staff(banner, storage, banner_service.is_shown_now(db, banner.id))


@staff_router.delete(
    "/{banner_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a banner",
    description=(
        f"{PERMISSION_NOTE} Its image files are retired (the worker deletes them). Audited as "
        "'content.banner_delete' with its values."
    ),
    responses={**GUARDED, **BANNER_404, **VALIDATION_422},
)
def delete_banner(banner_id: uuid.UUID, current_user: ContentManager, db: Db, ctx: Ctx):
    BannerService.delete(db, current_user, banner_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@staff_router.post(
    "/{banner_id}/image",
    response_model=StaffBannerResponse,
    summary="Upload or replace a banner image",
    description=(
        f"{PERMISSION_NOTE} multipart/form-data with `file` (JPEG, PNG or WebP, at most 5 MB), "
        "same rules as product images. Audited as 'content.banner_image_upload'."
    ),
    responses={**GUARDED, **BANNER_404, **TOO_LARGE_413, **UPLOAD_422},
)
def upload_banner_image(
    banner_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, at most 5 MB")],
    current_user: ContentManager,
    db: Db,
    ctx: Ctx,
    storage: Storage,
) -> StaffBannerResponse:
    raw = read_upload(file.file)
    banner = BannerService.set_image(
        db, storage, current_user, banner_id, processed_upload(raw), len(raw), ctx
    )
    return _staff(banner, storage, banner_service.is_shown_now(db, banner.id))


@staff_router.delete(
    "/{banner_id}/image",
    response_model=StaffBannerResponse,
    summary="Remove a banner image",
    description=(
        f"{PERMISSION_NOTE} Only for an inactive banner (409 banner_needs_image otherwise). "
        "Audited as 'content.banner_image_delete'."
    ),
    responses={**GUARDED, **BANNER_404, **BANNER_409, **VALIDATION_422},
)
def delete_banner_image(
    banner_id: uuid.UUID, current_user: ContentManager, db: Db, ctx: Ctx, storage: Storage
) -> StaffBannerResponse:
    banner = BannerService.remove_image(db, current_user, banner_id, ctx)
    return _staff(banner, storage, banner_service.is_shown_now(db, banner.id))
