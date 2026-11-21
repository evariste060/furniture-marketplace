"""Technical services (ADR-013, SC-02, approved 2026-11-17).

Public: the active services, in staff's order, with their items, in English or Kinyarwanda
(a missing Kinyarwanda text falls back to English); a hidden service answers 404.

Requests (leads): anyone can request an active service. A request that fills the hidden
`website` field (a bot) is answered like a stored one but nothing is stored or counted. Every
other attempt counts against a fixed-window limit per phone number (its keyed pseudonym, never the
number) and per client network (SERVICE_REQUEST_* settings); beyond it the request answers 429,
and an unreachable limit store refuses (503). The request gets a random reference
(SR-YYMMDD-XXXXXX, Kigali date) and, when an email is given, an acknowledgement email.

Staff with 'services:manage' (administrator, sales) create, edit, hide, reorder and delete
services and their items, and follow requests up (status, assignee, internal notes). A service
with requests cannot be deleted (409 service_has_requests); hide it instead. Every change is
audited ('services.*'); a change that changes nothing writes nothing.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import (
    Conflict,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
    field_error,
)
from app.core.kigali_time import KIGALI
from app.core.rate_limit import LoginRateLimiter, RateLimitStoreUnavailable, client_network
from app.core.request_context import RequestContext
from app.core.roles import Permission, has_permission
from app.core.security import pseudonymize_identifier
from app.core.slugs import first_free_slug, slugify
from app.db.transaction import atomic
from app.integrations.media import MediaStorage
from app.models.common import utc_now
from app.models.identity import User
from app.models.services import (
    SERVICE_ITEMS_MAX,
    SERVICE_SLUG_MAX_LENGTH,
    ServiceCategory,
    ServiceItem,
    ServiceRequest,
)
from app.schemas.pagination import page_offset
from app.schemas.services import (
    ServiceCreateRequest,
    ServiceItemCreateRequest,
    ServiceItemOrderRequest,
    ServiceItemUpdateRequest,
    ServiceOrderRequest,
    ServiceRequestCreate,
    ServiceRequestUpdate,
    ServiceUpdateRequest,
)
from app.services.audit_service import AuditService
from app.services.image_processing import ProcessedImage
from app.services.media_registry import activate, discard_staged, retire, stage_image
from app.services.notification_service import record_email_event

logger = logging.getLogger("app.services_module")

REFERENCE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O, 1/I: read aloud by phone
REFERENCE_SUFFIX = 6
PREFERRED_DATE_MAX_DAYS = 366
NOT_FOUND = "Service not found."
ITEM_NOT_FOUND = "Service item not found."
REQUEST_NOT_FOUND = "Service request not found."
SLUG_TAKEN = "Another service already uses this slug."
NO_SLUG_FROM_NAME = "The name needs letters or digits for its web address; set a slug."
HAS_REQUESTS = "This service has requests, so it cannot be deleted. Hide it instead."
ORDER_MISMATCH = "Send every service exactly once."
ITEM_ORDER_MISMATCH = "Send every item of the service exactly once."
TOO_MANY_ITEMS = f"A service has at most {SERVICE_ITEMS_MAX} items."
DATE_RULE = "Choose a date from today up to one year ahead."
ASSIGNEE_RULE = "Choose an active staff member who can manage services."
LIMITED = "Too many service requests; try again later or contact us on WhatsApp."
UNAVAILABLE = "Service requests cannot be sent right now; try again shortly."


# ---- helpers -----------------------------------------------------------------------------------
def localized(en: str, rw: str | None, locale: str) -> str:
    """The Kinyarwanda text when asked for and written, otherwise the English one."""
    return rw if locale == "rw" and rw else en


def _audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str,
    actor: User,
    ctx: RequestContext,
    details: dict[str, Any],
) -> None:
    AuditService.log_event(
        db=db,
        action=action,
        status="success",
        actor=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        context=ctx,
        details=details,
    )


def _new_reference(db: Session, now: datetime) -> str:
    for _ in range(10):
        suffix = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(REFERENCE_SUFFIX))
        reference = f"SR-{now.astimezone(KIGALI):%y%m%d}-{suffix}"
        taken = db.scalar(select(ServiceRequest.id).where(ServiceRequest.reference == reference))
        if taken is None:
            return reference
    raise RuntimeError("could not allocate a service request reference")  # pragma: no cover


def _decoy_reference(now: datetime) -> str:
    suffix = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(REFERENCE_SUFFIX))
    return f"SR-{now.astimezone(KIGALI):%y%m%d}-{suffix}"


def _check_preferred_date(value: date | None, now: datetime) -> None:
    if value is None:
        return
    today = now.astimezone(KIGALI).date()
    if not today <= value <= today + timedelta(days=PREFERRED_DATE_MAX_DAYS):
        raise field_error(("body", "preferred_date"), DATE_RULE)


def _forget_items(db: Session, service_id: uuid.UUID) -> None:
    """Drop a loaded service's cached item list after its items change, so the next read in the
    same session sees them (items are written by their service id, not through the list)."""
    service = db.identity_map.get(Session.identity_key(ServiceCategory, service_id))
    if service is not None:
        db.expire(service, ["items"])


def _locked_service(db: Session, service_id: uuid.UUID) -> ServiceCategory:
    service = db.scalar(
        select(ServiceCategory).where(ServiceCategory.id == service_id).with_for_update()
    )
    if service is None:
        raise NotFound(NOT_FOUND, code="service_not_found")
    return service


def _slug_taken(db: Session, slug: str, exclude_id: uuid.UUID | None) -> bool:
    query = select(ServiceCategory.id).where(ServiceCategory.slug == slug)
    if exclude_id is not None:
        query = query.where(ServiceCategory.id != exclude_id)
    return db.scalar(query) is not None


def _is_slug_violation(exc: IntegrityError) -> bool:
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
    return "slug" in constraint


def request_counts(db: Session) -> dict[uuid.UUID, int]:
    return {
        service_id: count
        for service_id, count in db.execute(
            select(ServiceRequest.service_category_id, func.count(ServiceRequest.id)).group_by(
                ServiceRequest.service_category_id
            )
        ).all()
    }


@dataclass(frozen=True)
class RequestFilters:
    status: str | None = None
    service_id: uuid.UUID | None = None
    date_from: date | None = None  # Kigali dates, inclusive
    date_to: date | None = None
    assigned_to_user_id: uuid.UUID | None = None


def _kigali_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=KIGALI)


# ---- public ------------------------------------------------------------------------------------
class PublicServices:
    @staticmethod
    def active(db: Session) -> list[ServiceCategory]:
        return list(
            db.scalars(
                select(ServiceCategory)
                .where(ServiceCategory.is_active)
                .order_by(ServiceCategory.sort_order, ServiceCategory.name_en)
            )
        )

    @staticmethod
    def by_slug(db: Session, slug: str) -> ServiceCategory:
        service = db.scalar(
            select(ServiceCategory).where(ServiceCategory.slug == slug, ServiceCategory.is_active)
        )
        if service is None:
            raise NotFound(NOT_FOUND, code="service_not_found")
        return service

    @staticmethod
    def request(
        db: Session,
        slug: str,
        req: ServiceRequestCreate,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
    ) -> str:
        """Store the request and return its reference."""
        now = utc_now()
        service = PublicServices.by_slug(db, slug)
        if req.website:
            # The hidden field is filled: a bot. Look successful, store and count nothing.
            logger.info("Service request dropped by the honeypot")
            return _decoy_reference(now)
        _check_preferred_date(req.preferred_date, now)
        key = get_settings().audit_hmac_key.get_secret_value()
        phone_ref = pseudonymize_identifier(req.phone, key)
        network = client_network(ctx.ip_address)
        try:
            decision = limiter.check(phone_ref, network)
            if decision.allowed:
                limiter.record_failure(phone_ref, network)  # every attempt counts
        except RateLimitStoreUnavailable:
            logger.error("Service request refused: the rate-limit store is unavailable")
            raise ServiceUnavailable(UNAVAILABLE, code="service_request_unavailable") from None
        if not decision.allowed:
            logger.warning("Service request limit reached (%s)", decision.scope)
            raise TooManyRequests(
                LIMITED, code="rate_limited", headers={"Retry-After": str(decision.retry_after)}
            )
        with atomic(db):
            request = ServiceRequest(
                reference=_new_reference(db, now),
                service_category_id=service.id,
                full_name=req.full_name,
                phone=req.phone,
                email=req.email,
                location=req.location,
                client_type=req.client_type,
                message=req.message,
                preferred_date=req.preferred_date,
                locale=req.locale,
                status="new",
            )
            db.add(request)
            db.flush()
            record_email_event(db, "service_received", request.id, request.email)
        return request.reference


# ---- staff: services ---------------------------------------------------------------------------
SERVICE_FIELDS = (
    "slug",
    "name_en",
    "name_rw",
    "short_description_en",
    "short_description_rw",
    "intro_en",
    "intro_rw",
    "icon",
    "is_active",
)


class ServiceAdmin:
    @staticmethod
    def all(db: Session) -> list[ServiceCategory]:
        return list(
            db.scalars(
                select(ServiceCategory).order_by(
                    ServiceCategory.sort_order, ServiceCategory.name_en
                )
            )
        )

    @staticmethod
    def get(db: Session, service_id: uuid.UUID) -> ServiceCategory:
        service = db.get(ServiceCategory, service_id)
        if service is None:
            raise NotFound(NOT_FOUND, code="service_not_found")
        return service

    @staticmethod
    def create(
        db: Session, actor: User, req: ServiceCreateRequest, ctx: RequestContext
    ) -> ServiceCategory:
        try:
            with atomic(db):
                if req.slug is not None:
                    if _slug_taken(db, req.slug, None):
                        raise Conflict(SLUG_TAKEN, code="slug_taken")
                    slug = req.slug
                else:
                    base = slugify(req.name_en, SERVICE_SLUG_MAX_LENGTH)
                    if not base:
                        raise field_error(("body", "name_en"), NO_SLUG_FROM_NAME)
                    slug = first_free_slug(
                        base, lambda s: _slug_taken(db, s, None), SERVICE_SLUG_MAX_LENGTH
                    )
                last = db.scalar(select(func.max(ServiceCategory.sort_order))) or 0
                service = ServiceCategory(
                    slug=slug,
                    name_en=req.name_en,
                    name_rw=req.name_rw,
                    short_description_en=req.short_description_en,
                    short_description_rw=req.short_description_rw,
                    intro_en=req.intro_en,
                    intro_rw=req.intro_rw,
                    icon=req.icon,
                    is_active=req.is_active,
                    sort_order=last + 1,
                )
                db.add(service)
                db.flush()
                _audit(
                    db,
                    "services.service_create",
                    "service",
                    service.id,
                    actor,
                    ctx,
                    {"slug": slug, "name_en": service.name_en, "is_active": service.is_active},
                )
        except IntegrityError as exc:
            if not _is_slug_violation(exc):
                raise
            raise Conflict(SLUG_TAKEN, code="slug_taken") from None
        db.refresh(service)
        return service

    @staticmethod
    def update(
        db: Session,
        actor: User,
        service_id: uuid.UUID,
        req: ServiceUpdateRequest,
        ctx: RequestContext,
    ) -> ServiceCategory:
        try:
            with atomic(db):
                service = _locked_service(db, service_id)
                changes: dict[str, dict[str, Any]] = {}
                for field in SERVICE_FIELDS:
                    if field not in req.model_fields_set:
                        continue
                    value = getattr(req, field)
                    if value == getattr(service, field):
                        continue
                    if field == "slug" and _slug_taken(db, value, service.id):
                        raise Conflict(SLUG_TAKEN, code="slug_taken")
                    changes[field] = {"from": getattr(service, field), "to": value}
                    setattr(service, field, value)
                if not changes:
                    return service
                db.flush()
                # Long texts are recorded as changed, not copied into the audit trail.
                summary = {
                    k: (v if not k.startswith("intro") else {"changed": True})
                    for k, v in changes.items()
                }
                _audit(db, "services.service_update", "service", service.id, actor, ctx, summary)
        except IntegrityError as exc:
            if not _is_slug_violation(exc):
                raise
            raise Conflict(SLUG_TAKEN, code="slug_taken") from None
        db.refresh(service)
        return service

    @staticmethod
    def delete(db: Session, actor: User, service_id: uuid.UUID, ctx: RequestContext) -> None:
        with atomic(db):
            service = _locked_service(db, service_id)
            requests = (
                db.scalar(
                    select(func.count(ServiceRequest.id)).where(
                        ServiceRequest.service_category_id == service.id
                    )
                )
                or 0
            )
            if requests:
                raise Conflict(
                    HAS_REQUESTS, code="service_has_requests", details={"requests": requests}
                )
            media = (service.image_media_id, service.image_original_media_id)
            details = {"slug": service.slug, "name_en": service.name_en}
            db.delete(service)
            db.flush()
            retire(db, media)  # the cleanup worker deletes the image files
            _audit(db, "services.service_delete", "service", service_id, actor, ctx, details)

    @staticmethod
    def reorder(db: Session, actor: User, req: ServiceOrderRequest, ctx: RequestContext) -> None:
        """sort_order 1, 2, 3, ... in the order sent; every service exactly once."""
        with atomic(db):
            services = {s.id: s for s in db.scalars(select(ServiceCategory).with_for_update())}
            if len(req.service_ids) != len(set(req.service_ids)) or set(services) != set(
                req.service_ids
            ):
                raise Conflict(ORDER_MISMATCH, code="service_order_mismatch")
            changes = []
            for position, service_id in enumerate(req.service_ids, start=1):
                service = services[service_id]
                if service.sort_order != position:
                    changes.append({"id": service_id, "from": service.sort_order, "to": position})
                    service.sort_order = position
            if not changes:
                return
            db.flush()
            _audit(
                db, "services.service_reorder", "service", "all", actor, ctx, {"changes": changes}
            )

    # ---- items ----
    @staticmethod
    def add_item(
        db: Session,
        actor: User,
        service_id: uuid.UUID,
        req: ServiceItemCreateRequest,
        ctx: RequestContext,
    ) -> ServiceItem:
        with atomic(db):
            service = _locked_service(db, service_id)
            count = (
                db.scalar(
                    select(func.count(ServiceItem.id)).where(
                        ServiceItem.service_category_id == service.id
                    )
                )
                or 0
            )
            if count >= SERVICE_ITEMS_MAX:
                raise field_error(("body", "title_en"), TOO_MANY_ITEMS)
            last = (
                db.scalar(
                    select(func.max(ServiceItem.sort_order)).where(
                        ServiceItem.service_category_id == service.id
                    )
                )
                or 0
            )
            item = ServiceItem(
                service_category_id=service.id,
                title_en=req.title_en,
                title_rw=req.title_rw,
                sort_order=last + 1,
            )
            db.add(item)
            db.flush()
            _audit(
                db,
                "services.item_create",
                "service",
                service.id,
                actor,
                ctx,
                {"item_id": str(item.id), "title_en": item.title_en},
            )
            _forget_items(db, service.id)
        db.refresh(item)
        return item

    @staticmethod
    def _locked_item(db: Session, service_id: uuid.UUID, item_id: uuid.UUID) -> ServiceItem:
        _locked_service(db, service_id)
        item = db.scalar(
            select(ServiceItem)
            .where(ServiceItem.id == item_id, ServiceItem.service_category_id == service_id)
            .with_for_update()
        )
        if item is None:
            raise NotFound(ITEM_NOT_FOUND, code="service_item_not_found")
        return item

    @staticmethod
    def update_item(
        db: Session,
        actor: User,
        service_id: uuid.UUID,
        item_id: uuid.UUID,
        req: ServiceItemUpdateRequest,
        ctx: RequestContext,
    ) -> ServiceItem:
        with atomic(db):
            item = ServiceAdmin._locked_item(db, service_id, item_id)
            changes = {}
            for field in ("title_en", "title_rw"):
                if field in req.model_fields_set and getattr(req, field) != getattr(item, field):
                    changes[field] = {"from": getattr(item, field), "to": getattr(req, field)}
                    setattr(item, field, getattr(req, field))
            if not changes:
                return item
            db.flush()
            _audit(
                db,
                "services.item_update",
                "service",
                service_id,
                actor,
                ctx,
                {"item_id": str(item.id), "changes": changes},
            )
        db.refresh(item)
        return item

    @staticmethod
    def delete_item(
        db: Session, actor: User, service_id: uuid.UUID, item_id: uuid.UUID, ctx: RequestContext
    ) -> None:
        with atomic(db):
            item = ServiceAdmin._locked_item(db, service_id, item_id)
            details = {"item_id": str(item.id), "title_en": item.title_en}
            db.delete(item)
            db.flush()
            _audit(db, "services.item_delete", "service", service_id, actor, ctx, details)
            _forget_items(db, service_id)

    @staticmethod
    def reorder_items(
        db: Session,
        actor: User,
        service_id: uuid.UUID,
        req: ServiceItemOrderRequest,
        ctx: RequestContext,
    ) -> None:
        with atomic(db):
            _locked_service(db, service_id)
            items = {
                i.id: i
                for i in db.scalars(
                    select(ServiceItem)
                    .where(ServiceItem.service_category_id == service_id)
                    .with_for_update()
                )
            }
            if len(req.item_ids) != len(set(req.item_ids)) or set(items) != set(req.item_ids):
                raise Conflict(ITEM_ORDER_MISMATCH, code="service_item_order_mismatch")
            changes = []
            for position, item_id in enumerate(req.item_ids, start=1):
                if items[item_id].sort_order != position:
                    changes.append(
                        {"id": str(item_id), "from": items[item_id].sort_order, "to": position}
                    )
                    items[item_id].sort_order = position
            if not changes:
                return
            db.flush()
            _audit(
                db,
                "services.item_reorder",
                "service",
                service_id,
                actor,
                ctx,
                {"changes": changes},
            )
            _forget_items(db, service_id)

    # ---- image ----
    @staticmethod
    def set_image(
        db: Session,
        storage: MediaStorage,
        actor: User,
        service_id: uuid.UUID,
        processed: ProcessedImage,
        upload_bytes: int,
        ctx: RequestContext,
    ) -> ServiceCategory:
        """Stage the new image (files), then point the service at it and retire the replaced
        image. The replaced files stay until the cleanup worker removes them."""
        with atomic(db):  # 404 before anything is stored
            _locked_service(db, service_id)
        staged = stage_image(db, storage, "services", service_id, processed)
        try:
            with atomic(db):
                service = _locked_service(db, service_id)
                previous = service.image_media
                replaced = (service.image_media_id, service.image_original_media_id)
                service.image_media_id = staged.public_id
                service.image_original_media_id = staged.original_id
                activate(db, staged)
                retire(db, replaced)
                db.flush()
                _audit(
                    db,
                    "services.service_image_upload",
                    "service",
                    service.id,
                    actor,
                    ctx,
                    {
                        "image_ref": staged.key,
                        "sha256": staged.sha256,
                        "replaced_image_ref": previous.storage_key if previous else None,
                        "width": staged.width,
                        "height": staged.height,
                        "content_type": staged.content_type,
                        "upload_bytes": upload_bytes,
                    },
                )
        except BaseException:
            discard_staged(db, storage, staged)
            raise
        db.refresh(service)
        return service

    @staticmethod
    def remove_image(
        db: Session, actor: User, service_id: uuid.UUID, ctx: RequestContext
    ) -> ServiceCategory:
        with atomic(db):
            service = _locked_service(db, service_id)
            previous = service.image_media
            if previous is None:
                return service
            retired = (service.image_media_id, service.image_original_media_id)
            service.image_media_id = None
            service.image_original_media_id = None
            db.flush()
            retire(db, retired)
            _audit(
                db,
                "services.service_image_delete",
                "service",
                service.id,
                actor,
                ctx,
                {"image_ref": previous.storage_key},
            )
        db.refresh(service)
        return service


# ---- staff: requests ---------------------------------------------------------------------------
class ServiceRequestAdmin:
    @staticmethod
    def page(
        db: Session, filters: RequestFilters, page: int, size: int
    ) -> tuple[list[ServiceRequest], int]:
        where = []
        if filters.status:
            where.append(ServiceRequest.status == filters.status)
        if filters.service_id:
            where.append(ServiceRequest.service_category_id == filters.service_id)
        if filters.assigned_to_user_id:
            where.append(ServiceRequest.assigned_to_user_id == filters.assigned_to_user_id)
        if filters.date_from:
            where.append(ServiceRequest.created_at >= _kigali_start(filters.date_from))
        if filters.date_to:
            where.append(
                ServiceRequest.created_at < _kigali_start(filters.date_to + timedelta(days=1))
            )
        total = db.scalar(select(func.count(ServiceRequest.id)).where(*where)) or 0
        rows = db.scalars(
            select(ServiceRequest)
            .where(*where)
            .order_by(ServiceRequest.created_at.desc(), ServiceRequest.id.desc())
            .offset(page_offset(page, size))
            .limit(size)
        )
        return list(rows), total

    @staticmethod
    def get(db: Session, request_id: uuid.UUID) -> ServiceRequest:
        request = db.get(ServiceRequest, request_id)
        if request is None:
            raise NotFound(REQUEST_NOT_FOUND, code="service_request_not_found")
        return request

    @staticmethod
    def assignees(db: Session) -> list[User]:
        """Active staff who can follow requests up, by name."""
        staff = db.scalars(select(User).where(User.is_staff, User.is_active))
        able = [u for u in staff if has_permission(u, Permission.SERVICES_MANAGE.value)]
        return sorted(able, key=lambda u: (u.full_name or u.email or "").lower())

    @staticmethod
    def update(
        db: Session,
        actor: User,
        request_id: uuid.UUID,
        req: ServiceRequestUpdate,
        ctx: RequestContext,
    ) -> ServiceRequest:
        with atomic(db):
            request = db.scalar(
                select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update()
            )
            if request is None:
                raise NotFound(REQUEST_NOT_FOUND, code="service_request_not_found")
            changes: dict[str, Any] = {}
            sent = req.model_fields_set
            if "status" in sent and req.status != request.status:
                assert req.status is not None
                changes["status"] = {"from": request.status, "to": req.status}
                request.status = req.status
                request.status_changed_at = None if req.status == "new" else utc_now()
            if (
                "assigned_to_user_id" in sent
                and req.assigned_to_user_id != request.assigned_to_user_id
            ):
                if req.assigned_to_user_id is not None:
                    assignee = db.get(User, req.assigned_to_user_id)
                    if (
                        assignee is None
                        or not assignee.is_active
                        or not has_permission(assignee, Permission.SERVICES_MANAGE.value)
                    ):
                        raise field_error(("body", "assigned_to_user_id"), ASSIGNEE_RULE)
                changes["assigned_to_user_id"] = {
                    "from": str(request.assigned_to_user_id)
                    if request.assigned_to_user_id
                    else None,
                    "to": str(req.assigned_to_user_id) if req.assigned_to_user_id else None,
                }
                request.assigned_to_user_id = req.assigned_to_user_id
            if "internal_notes" in sent and req.internal_notes != request.internal_notes:
                # The notes are recorded as changed; their text stays out of the audit trail.
                changes["internal_notes"] = {"changed": True}
                request.internal_notes = req.internal_notes
            if not changes:
                return request
            db.flush()
            _audit(
                db,
                "services.request_update",
                "service_request",
                request.id,
                actor,
                ctx,
                {"reference": request.reference, "changes": changes},
            )
        db.refresh(request)
        return request
