"""Policy pages (module 19, approved 2026-10-29).

Six pages (PAGE_SLUGS), each in English and Kinyarwanda. The public read serves one published
language version; a missing or unpublished translation is 404 page_not_found, never another
language (the storefront decides what to show Kinyarwanda readers instead). Staff with
'content:manage' read both versions of every page, drafts included, and write one version at a
time (PUT): created on first write, replaced after. Each change is audited as
'content.page_update' with the title, publication and body length before and after (the body
itself is not copied into the audit trail). Writes are serialised by a transaction-scoped
advisory lock, so two first writes of the same version cannot race.
"""

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.models.content import PAGE_SLUGS, Page
from app.models.identity import User
from app.schemas.pages import PageUpdateRequest
from app.services.audit_service import AuditService

# pg_advisory_xact_lock(bigint) key; 7_302_116_001-005 are taken (staff, catalogue, products,
# settings).
PAGE_CHANGE_LOCK_KEY = 7_302_116_006
PAGE_NOT_FOUND = "This page is not available in this language."


def _version(db: Session, slug: str, locale: str, *, lock: bool = False) -> Page | None:
    statement = select(Page).where(Page.slug == slug, Page.locale == locale)
    if lock:
        statement = statement.with_for_update()
    return db.scalar(statement)


def _snapshot(page: Page | None) -> dict[str, object] | None:
    if page is None:
        return None
    return {"title": page.title, "is_published": page.is_published, "body_length": len(page.body)}


class PageService:
    @staticmethod
    def public(db: Session, slug: str, locale: str) -> Page:
        page = _version(db, slug, locale) if slug in PAGE_SLUGS else None
        if page is None or not page.is_published:
            raise NotFound(PAGE_NOT_FOUND, code="page_not_found")
        return page

    @staticmethod
    def staff_all(db: Session) -> dict[str, dict[str, Page]]:
        """{slug: {locale: page}} for every slug in menu order; missing versions are absent."""
        pages: dict[str, dict[str, Page]] = {slug: {} for slug in PAGE_SLUGS}
        for page in db.scalars(select(Page).where(Page.slug.in_(PAGE_SLUGS))):
            pages[page.slug][page.locale] = page
        return pages

    @staticmethod
    def put(
        db: Session,
        actor: User,
        slug: str,
        locale: str,
        req: PageUpdateRequest,
        ctx: RequestContext,
    ) -> Page:
        with atomic(db):
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PAGE_CHANGE_LOCK_KEY})
            page = _version(db, slug, locale, lock=True)
            before = _snapshot(page)
            if page is None:
                page = Page(slug=slug, locale=locale)
                db.add(page)
            elif (page.title, page.body, page.is_published) == (
                req.title,
                req.body,
                req.is_published,
            ):
                return page  # nothing changed: not audited
            page.title = req.title
            page.body = req.body
            page.is_published = req.is_published
            page.updated_by_user_id = actor.id
            db.flush()
            AuditService.log_event(
                db=db,
                action="content.page_update",
                status="success",
                actor=actor,
                entity_type="page",
                entity_id=f"{slug}:{locale}",
                context=ctx,
                details={"from": before, "to": _snapshot(page)},
            )
        db.refresh(page)
        return page
