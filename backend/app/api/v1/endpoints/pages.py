"""Policy pages (module 19, approved 2026-10-29). Rules are in app.services.pages.

GET /pages/{slug}?lang=en|rw is public: one published language version, cached for 60 seconds; a
missing or unpublished translation is 404, never another language. The staff routes need
'content:manage' (administrator, management).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.v1.responses import ERR, FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import require_permission
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models.content import Page
from app.models.identity import User
from app.schemas.pages import (
    PageLocale,
    PageSlug,
    PageUpdateRequest,
    PublicPage,
    StaffPage,
    StaffPagesResponse,
    StaffPageVersion,
)
from app.services.pages import PageService

public_router = APIRouter(prefix="/pages", tags=["Storefront Content"])
staff_router = APIRouter(prefix="/staff/pages", tags=["Staff Content"])

PUBLIC_CACHE = "public, max-age=60"
Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
ContentManager = Annotated[User, Depends(require_permission(Permission.CONTENT_MANAGE))]
Lang = Annotated[PageLocale, Query(alias="lang", description="Language version: en or rw")]
GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
PAGE_404: ResponseMap = {404: {**ERR, "description": "page_not_found"}}


def _version(page: Page | None) -> StaffPageVersion | None:
    if page is None:
        return None
    return StaffPageVersion(
        title=page.title,
        body=page.body,
        is_published=page.is_published,
        updated_at=page.updated_at,
        updated_by_user_id=page.updated_by_user_id,
    )


def _staff(slug: str, versions: dict[str, Page]) -> StaffPage:
    return StaffPage(
        slug=slug,  # type: ignore[arg-type]
        en=_version(versions.get("en")),
        rw=_version(versions.get("rw")),
    )


@public_router.get(
    "/{slug}",
    response_model=PublicPage,
    summary="A policy page",
    description=(
        "Public. One published language version of a policy page (about-us, "
        "delivery-information, returns-and-refunds, warranty, privacy-policy, "
        "terms-and-conditions). The body is Markdown: render it without raw HTML. A missing or "
        "unpublished translation is 404 page_not_found, not another language. Cached for 60 "
        "seconds."
    ),
    responses={**PAGE_404, **VALIDATION_422},
)
def read_page(slug: str, response: Response, db: Db, lang: Lang = "en") -> PublicPage:
    page = PageService.public(db, slug, lang)
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return PublicPage(
        slug=page.slug,  # type: ignore[arg-type]
        locale=page.locale,  # type: ignore[arg-type]
        title=page.title,
        body=page.body,
        updated_at=page.updated_at,
    )


@staff_router.get(
    "",
    response_model=StaffPagesResponse,
    summary="List policy pages",
    description=(
        "Requires 'content:manage' (administrator, management). Every policy page in menu "
        "order with its English and Kinyarwanda versions (null when not written), drafts "
        "included."
    ),
    responses=GUARDED,
)
def list_pages(_: ContentManager, db: Db) -> StaffPagesResponse:
    pages = PageService.staff_all(db)
    return StaffPagesResponse(items=[_staff(slug, versions) for slug, versions in pages.items()])


@staff_router.put(
    "/{slug}",
    response_model=StaffPage,
    summary="Write one language version of a page",
    description=(
        "Requires 'content:manage' (administrator, management). Creates or replaces the `lang` "
        "version: title (plain text, at most 120), body (Markdown, at most 50,000 characters) "
        "and whether it is published. Returns the page with both versions. Audited as "
        "'content.page_update' (title, publication and body length before and after); a write "
        "that changes nothing is not audited."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def write_page(
    slug: PageSlug,
    req: PageUpdateRequest,
    actor: ContentManager,
    db: Db,
    ctx: Ctx,
    lang: Lang,
) -> StaffPage:
    PageService.put(db, actor, slug, lang, req, ctx)
    return _staff(slug, PageService.staff_all(db)[slug])
