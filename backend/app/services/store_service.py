"""Stores and seller applications (ADR-014 phase 1, approved 2026-11-21).

Who may apply: a signed-in, active customer whose account email is verified. Staff accounts
cannot (staff_cannot_sell): sellers are store owners, never staff. One store per user for life
(stores.owner_user_id is unique): a second application is 409 store_exists, and a rejected
applicant edits and resubmits the same row. Store names are unique regardless of letter case
(409 store_name_taken). The store is always the caller's own, found from the session: no seller
request names a store, an owner, a status, a slug or a commission.

Lifecycle (STORE_TRANSITIONS for administrators, the application routes for the applicant):

    (new) -> pending              applicant submits          history row, email
    pending -> pending            applicant edits            audited only
    rejected -> pending           applicant resubmits        history row, email
    pending -> approved|rejected  administrator              history row, email
    approved -> suspended         administrator              history row, email
    suspended -> approved         administrator (reinstate)  history row, email

Every change runs in one transaction with the store row locked (FOR UPDATE), so two
administrators deciding at once are serialised and the second gets 409
invalid_store_transition. The current reason is kept on the store only while it is rejected or
suspended; the history keeps every reason. approved_at is the first approval and is kept through
suspension and reinstatement. Each submission and decision is audited and recorded in the
notification outbox for the owner's verified account email (not the store's contact email),
with the history row as its subject.

Commission: effective_commission_bps is the one place the rate is worked out: the store's
override, else the platform setting (default 1000 = 10%). Whole basis points only.
"""

import uuid
from collections.abc import Mapping
from typing import Literal, cast

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound
from app.core.request_context import RequestContext
from app.core.slugs import first_free_slug, slugify
from app.db.transaction import atomic
from app.integrations.media import MediaStorage, get_media_storage
from app.models import Product
from app.models.common import utc_now
from app.models.identity import User
from app.models.marketplace import STORE_SLUG_MAX_LENGTH, Store, StoreStatusHistory
from app.models.media import MediaObject
from app.repositories.catalog import public_product_ids
from app.repositories.store_repository import StoreRepository
from app.schemas.images import PublicImage
from app.schemas.pagination import page_offset
from app.schemas.stores import (
    PublicStoreResponse,
    SellerStoreResponse,
    StaffPerson,
    StaffStoreDetail,
    StaffStoreOwner,
    StaffStoreSummary,
    StoreApplicationRequest,
    StoreHistoryEntry,
    StoreProfileUpdate,
    StoreStatusRequest,
)
from app.services.audit_service import AuditService
from app.services.image_processing import ProcessedImage
from app.services.media_registry import (
    activate,
    discard_staged,
    public_image,
    retire,
    stage_image,
)
from app.services.notification_service import EmailEvent, record_email_event
from app.services.settings_service import default_commission_bps

# Administrator decisions. The applicant's own moves (new or rejected -> pending) are not here:
# they go through the application routes.
STORE_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "pending": frozenset({"approved", "rejected"}),
    "approved": frozenset({"suspended"}),
    "rejected": frozenset(),
    "suspended": frozenset({"approved"}),
}
DECISION_EVENTS: Mapping[tuple[str, str], EmailEvent] = {
    ("pending", "approved"): "store_approved",
    ("pending", "rejected"): "store_rejected",
    ("approved", "suspended"): "store_suspended",
    ("suspended", "approved"): "store_reinstated",
}

STORE_NOT_FOUND = "Store not found."
NO_APPLICATION = "You have not applied to sell yet."
STORE_EXISTS = "You already have a store or a seller application."
NAME_TAKEN = "Another store already uses this name."
SLUG_CONFLICT = "Another store was created with the same address at the same moment; try again."
STAFF_CANNOT_SELL = "Staff accounts cannot apply to become sellers."
VERIFY_EMAIL = "Add and verify an email address on your account before applying to sell."
APPLICATION_CLOSED = "This application has been decided and can no longer be changed here."
INVALID_TRANSITION = "This store status change is not allowed."
NOT_APPROVED = "Your store is not approved."


class InvalidStoreTransition(Conflict):
    def __init__(self, current: str, requested: str) -> None:
        super().__init__(
            INVALID_TRANSITION,
            code="invalid_store_transition",
            details={"current_status": current, "requested_status": requested},
        )


StoreImageField = Literal["logo", "cover"]


def allowed_transition(current: str, requested: str) -> bool:
    return requested in STORE_TRANSITIONS.get(current, frozenset())


def effective_commission_bps(db: Session, store: Store) -> int:
    """The commission rate that applies to the store, in whole basis points."""
    if store.commission_rate_bps is not None:
        return store.commission_rate_bps
    return default_commission_bps(db)


def verified_email(user: User) -> str | None:
    """The account email when it is verified, else None."""
    return user.email if user.email and user.email_verified_at is not None else None


def _check_applicant(user: User) -> None:
    if user.is_staff:
        raise Forbidden(STAFF_CANNOT_SELL, code="staff_cannot_sell")
    if verified_email(user) is None:
        raise Forbidden(VERIFY_EMAIL, code="email_verification_required")


def _unique_conflict(
    exc: IntegrityError, db: Session, name: str | None, excluding: uuid.UUID | None
) -> Conflict | None:
    """Map a unique violation from a concurrent insert or update (after the rollback). Two
    applications with the same name also share a slug and may collide on it first, so a slug
    collision is reported as the name being taken whenever it now is."""
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
    if constraint == "uq_stores_owner_user_id":
        return Conflict(STORE_EXISTS, code="store_exists")
    if constraint == "uq_stores_name_lower":
        return Conflict(NAME_TAKEN, code="store_name_taken")
    if constraint == "uq_stores_slug":
        if name is not None and StoreRepository.name_taken(db, name, excluding=excluding):
            return Conflict(NAME_TAKEN, code="store_name_taken")
        return Conflict(SLUG_CONFLICT, code="store_slug_conflict")
    return None


def _free_slug(db: Session, name: str, excluding: uuid.UUID | None) -> str:
    base = slugify(name, STORE_SLUG_MAX_LENGTH) or "store"
    return first_free_slug(
        base,
        lambda candidate: StoreRepository.slug_taken(db, candidate, excluding=excluding),
        STORE_SLUG_MAX_LENGTH,
    )


def _check_name(db: Session, name: str, excluding: uuid.UUID | None) -> None:
    if StoreRepository.name_taken(db, name, excluding=excluding):
        raise Conflict(NAME_TAKEN, code="store_name_taken")


def _record(
    db: Session, store: Store, actor: User, reason: str | None, event: EmailEvent
) -> StoreStatusHistory:
    """The history row of a submission or decision, and its email to the owner."""
    entry = StoreStatusHistory(
        store_id=store.id,
        status=store.status,
        reason=reason,
        store_name=store.name,
        actor_user_id=actor.id,
    )
    db.add(entry)
    db.flush()
    record_email_event(db, event, entry.id, verified_email(store.owner))
    return entry


def _apply_fields(store: Store, values: Mapping[str, object]) -> list[str]:
    changed = []
    for field, value in values.items():
        if getattr(store, field) != value:
            setattr(store, field, value)
            changed.append(field)
    return changed


def _audit(
    db: Session,
    action: str,
    store: Store,
    actor: User,
    ctx: RequestContext,
    details: dict | None = None,
) -> None:
    AuditService.log_event(
        db=db,
        action=action,
        status="success",
        actor=actor,
        entity_type="store",
        entity_id=store.id,
        context=ctx,
        details={"store_slug": store.slug, **(details or {})},
    )


class StoreService:
    # ---- the applicant ---------------------------------------------------------------------
    @staticmethod
    def apply(db: Session, user: User, req: StoreApplicationRequest, ctx: RequestContext) -> Store:
        _check_applicant(user)
        try:
            with atomic(db):
                if StoreRepository.get_by_owner(db, user.id) is not None:
                    raise Conflict(STORE_EXISTS, code="store_exists")
                _check_name(db, req.name, None)
                store = Store(
                    owner_user_id=user.id,
                    slug=_free_slug(db, req.name, None),
                    status="pending",
                    submitted_at=utc_now(),
                    **req.model_dump(),
                )
                db.add(store)
                db.flush()
                _record(db, store, user, None, "store_application_received")
                _audit(db, "store.application_submit", store, user, ctx)
        except IntegrityError as exc:  # a concurrent application: the database decides
            conflict = _unique_conflict(exc, db, req.name, None)
            if conflict is None:
                raise
            raise conflict from None
        db.refresh(store)
        return store

    @staticmethod
    def own(db: Session, user: User) -> Store:
        store = StoreRepository.get_by_owner(db, user.id)
        if store is None:
            raise NotFound(NO_APPLICATION, code="store_not_found")
        return store

    @staticmethod
    def update_application(
        db: Session, user: User, req: StoreApplicationRequest, ctx: RequestContext
    ) -> Store:
        """Edit a pending application, or resubmit a rejected one (back to pending)."""
        _check_applicant(user)
        try:
            with atomic(db):
                store = StoreRepository.get_by_owner(db, user.id, for_update=True)
                if store is None:
                    raise NotFound(NO_APPLICATION, code="store_not_found")
                if store.status not in ("pending", "rejected"):
                    raise Conflict(APPLICATION_CLOSED, code="store_application_closed")
                _check_name(db, req.name, store.id)
                values = req.model_dump()
                if store.name != req.name and store.approved_at is None:
                    # Never public yet: the address follows the name.
                    values["slug"] = _free_slug(db, req.name, store.id)
                changed = _apply_fields(store, values)
                if store.status == "rejected":
                    store.status = "pending"
                    store.status_reason = None
                    store.submitted_at = utc_now()
                    db.flush()
                    _record(db, store, user, None, "store_application_received")
                    _audit(db, "store.application_resubmit", store, user, ctx, {"changed": changed})
                elif changed:
                    db.flush()
                    _audit(db, "store.application_update", store, user, ctx, {"changed": changed})
        except IntegrityError as exc:
            conflict = _unique_conflict(exc, db, req.name, store.id if store else None)
            if conflict is None:
                raise
            raise conflict from None
        db.refresh(store)
        return store

    # ---- the approved seller ---------------------------------------------------------------
    @staticmethod
    def update_profile(
        db: Session, user: User, store_id: uuid.UUID, req: StoreProfileUpdate, ctx: RequestContext
    ) -> Store:
        """An approved seller's own store. The status is checked again under the row lock, so a
        suspension that lands during the request wins. The slug never changes here."""
        try:
            with atomic(db):
                store = StoreRepository.get(db, store_id, for_update=True)
                if store is None or store.owner_user_id != user.id:
                    raise NotFound(STORE_NOT_FOUND, code="store_not_found")
                if store.status != "approved":
                    raise Forbidden(NOT_APPROVED, code="seller_not_approved")
                values = {f: getattr(req, f) for f in req.model_fields_set}
                if "name" in values:
                    _check_name(db, values["name"], store.id)  # type: ignore[arg-type]
                changed = _apply_fields(store, values)
                if changed:
                    db.flush()
                    _audit(db, "store.profile_update", store, user, ctx, {"changed": changed})
        except IntegrityError as exc:
            conflict = _unique_conflict(exc, db, req.name, store.id if store else None)
            if conflict is None:
                raise
            raise conflict from None
        db.refresh(store)
        return store

    @staticmethod
    def set_image(
        db: Session,
        storage: MediaStorage,
        user: User,
        store_id: uuid.UUID,
        field: StoreImageField,
        processed: ProcessedImage,
        upload_bytes: int,
        ctx: RequestContext,
    ) -> Store:
        """Upload or replace the seller's own logo or cover (ADR-014 phase 2), as category images
        do: stage the files (TX-A), then point the store at them and retire the replaced ones
        (TX-B; the cleanup worker deletes the files). Audited as store.logo_upload or
        store.cover_upload."""
        with atomic(db):  # refused before anything is stored
            _own_approved(db, user, store_id)
        staged = stage_image(db, storage, "stores", store_id, processed)
        try:
            with atomic(db):
                store = _own_approved(db, user, store_id)
                previous = getattr(store, f"{field}_media")
                replaced = (
                    getattr(store, f"{field}_media_id"),
                    getattr(store, f"{field}_original_media_id"),
                )
                setattr(store, f"{field}_media_id", staged.public_id)
                setattr(store, f"{field}_original_media_id", staged.original_id)
                activate(db, staged)
                retire(db, replaced)
                db.flush()
                _audit(
                    db,
                    f"store.{field}_upload",
                    store,
                    user,
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
        db.refresh(store)
        return store

    @staticmethod
    def remove_image(
        db: Session, user: User, store_id: uuid.UUID, field: StoreImageField, ctx: RequestContext
    ) -> Store:
        """Clear the seller's own logo or cover and retire its files. Nothing to remove: no
        write, no audit. Audited as store.logo_delete or store.cover_delete."""
        with atomic(db):
            store = _own_approved(db, user, store_id)
            previous = getattr(store, f"{field}_media")
            if previous is None:
                return store
            retired = (
                getattr(store, f"{field}_media_id"),
                getattr(store, f"{field}_original_media_id"),
            )
            setattr(store, f"{field}_media_id", None)
            setattr(store, f"{field}_original_media_id", None)
            db.flush()
            retire(db, retired)
            _audit(
                db, f"store.{field}_delete", store, user, ctx, {"image_ref": previous.storage_key}
            )
        db.refresh(store)
        return store

    # ---- the public storefront (ADR-014 decision 7) ---------------------------------------
    @staticmethod
    def public_page(db: Session, page: int, size: int) -> tuple[list[tuple[Store, int]], int]:
        """Approved stores by name, each with the number of its public products."""
        total = db.scalar(select(func.count(Store.id)).where(Store.status == "approved")) or 0
        stores = list(
            db.scalars(
                select(Store)
                .where(Store.status == "approved")
                .order_by(func.lower(Store.name), Store.id)
                .offset(page_offset(page, size))
                .limit(size)
            )
        )
        counts = public_product_counts(db, [store.id for store in stores])
        return [(store, counts.get(store.id, 0)) for store in stores], total

    @staticmethod
    def public_get(db: Session, slug: str) -> tuple[Store, int]:
        """An approved store by slug. Any other store, or none, is the same 404."""
        store = db.scalar(select(Store).where(Store.slug == slug, Store.status == "approved"))
        if store is None:
            raise NotFound(STORE_NOT_FOUND, code="store_not_found")
        return store, public_product_counts(db, [store.id]).get(store.id, 0)

    # ---- administrators --------------------------------------------------------------------
    @staticmethod
    def staff_page(
        db: Session, status: str | None, q: str | None, page: int, size: int
    ) -> tuple[list[Store], int]:
        query = select(Store).join(User, User.id == Store.owner_user_id)
        if status is not None:
            query = query.where(Store.status == status)
        if q:
            pattern = (
                "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            )
            query = query.where(
                or_(
                    func.lower(Store.name).like(pattern, escape="\\"),
                    Store.slug.like(pattern, escape="\\"),
                    func.lower(User.email).like(pattern, escape="\\"),
                    func.lower(User.full_name).like(pattern, escape="\\"),
                )
            )
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.scalars(
            query.order_by(Store.submitted_at.desc(), Store.id.desc())
            .offset(page_offset(page, size))
            .limit(size)
        )
        return list(rows), total

    @staticmethod
    def staff_get(db: Session, store_id: uuid.UUID) -> Store:
        store = StoreRepository.get(db, store_id)
        if store is None:
            raise NotFound(STORE_NOT_FOUND, code="store_not_found")
        return store

    @staticmethod
    def change_status(
        db: Session, actor: User, store_id: uuid.UUID, req: StoreStatusRequest, ctx: RequestContext
    ) -> Store:
        with atomic(db):
            store = StoreRepository.get(db, store_id, for_update=True)
            if store is None:
                raise NotFound(STORE_NOT_FOUND, code="store_not_found")
            previous = store.status
            if not allowed_transition(previous, req.status):
                raise InvalidStoreTransition(previous, req.status)
            now = utc_now()
            store.status = req.status
            store.status_reason = req.reason if req.status in ("rejected", "suspended") else None
            store.reviewed_at = now
            store.reviewed_by_user_id = actor.id
            if req.status == "approved" and store.approved_at is None:
                store.approved_at = now
            db.flush()
            _record(db, store, actor, req.reason, DECISION_EVENTS[(previous, req.status)])
            _audit(
                db,
                "store.status_change",
                store,
                actor,
                ctx,
                {"from": previous, "to": req.status, "reason": req.reason},
            )
        db.refresh(store)
        return store

    @staticmethod
    def set_commission(
        db: Session, actor: User, store_id: uuid.UUID, rate: int | None, ctx: RequestContext
    ) -> Store:
        """A store's own commission (whole basis points), or None to inherit the platform
        default. Setting the current value changes nothing and is not audited."""
        with atomic(db):
            store = StoreRepository.get(db, store_id, for_update=True)
            if store is None:
                raise NotFound(STORE_NOT_FOUND, code="store_not_found")
            if store.commission_rate_bps != rate:
                before = store.commission_rate_bps
                store.commission_rate_bps = rate
                db.flush()
                _audit(
                    db,
                    "store.commission_change",
                    store,
                    actor,
                    ctx,
                    {"from_bps": before, "to_bps": rate},
                )
        db.refresh(store)
        return store


def _own_approved(db: Session, user: User, store_id: uuid.UUID) -> Store:
    """The caller's own store, locked, checked approved again under the lock."""
    store = StoreRepository.get(db, store_id, for_update=True)
    if store is None or store.owner_user_id != user.id:
        raise NotFound(STORE_NOT_FOUND, code="store_not_found")
    if store.status != "approved":
        raise Forbidden(NOT_APPROVED, code="seller_not_approved")
    return store


def public_product_counts(db: Session, store_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """The number of public products of each store, by the public catalogue rule. One grouped
    query (not a correlated subquery: the rule joins stores itself, and correlating that join
    with an outer store row would drop it)."""
    if not store_ids:
        return {}
    public = (
        public_product_ids()
        .add_columns(Product.store_id)
        .where(Product.store_id.in_(store_ids))
        .subquery()
    )
    rows = db.execute(select(public.c.store_id, func.count()).group_by(public.c.store_id)).all()
    return {cast(uuid.UUID, store_id): cast(int, count) for store_id, count in rows}


def public_store_response(store: Store, product_count: int) -> PublicStoreResponse:
    storage = get_media_storage()
    return PublicStoreResponse(
        id=store.id,
        name=store.name,
        slug=store.slug,
        description=store.description,
        district=store.district,
        logo=_image(storage, store.logo_media, store.name),
        cover=_image(storage, store.cover_media, store.name),
        product_count=product_count,
        approved_at=store.approved_at,
    )


# ---- responses -----------------------------------------------------------------------------
def _image(storage: MediaStorage, media: MediaObject | None, alt: str) -> PublicImage | None:
    if media is None:
        return None
    return PublicImage.model_validate(public_image(storage, media, alt, 0))


def _person(user: User | None) -> StaffPerson | None:
    return StaffPerson(id=user.id, full_name=user.full_name) if user is not None else None


def seller_response(db: Session, store: Store) -> SellerStoreResponse:
    storage = get_media_storage()
    return SellerStoreResponse(
        id=store.id,
        name=store.name,
        slug=store.slug,
        description=store.description,
        contact_email=store.contact_email,
        contact_phone=store.contact_phone,
        district=store.district,
        sector=store.sector,
        street_address=store.street_address,
        logo=_image(storage, store.logo_media, store.name),
        cover=_image(storage, store.cover_media, store.name),
        status=store.status,  # type: ignore[arg-type]
        status_reason=store.status_reason,
        submitted_at=store.submitted_at,
        reviewed_at=store.reviewed_at,
        approved_at=store.approved_at,
        effective_commission_rate_bps=effective_commission_bps(db, store),
    )


def _summary_fields(store: Store) -> dict:
    owner = store.owner
    return {
        "id": store.id,
        "name": store.name,
        "slug": store.slug,
        "status": store.status,
        "district": store.district,
        "submitted_at": store.submitted_at,
        "reviewed_at": store.reviewed_at,
        "owner": StaffStoreOwner(
            id=owner.id, full_name=owner.full_name, email=owner.email, phone=owner.phone
        ),
    }


def staff_summary(store: Store) -> StaffStoreSummary:
    return StaffStoreSummary(**_summary_fields(store))


def staff_detail(db: Session, store: Store) -> StaffStoreDetail:
    storage = get_media_storage()
    return StaffStoreDetail(
        **_summary_fields(store),
        description=store.description,
        contact_email=store.contact_email,
        contact_phone=store.contact_phone,
        sector=store.sector,
        street_address=store.street_address,
        logo=_image(storage, store.logo_media, store.name),
        cover=_image(storage, store.cover_media, store.name),
        status_reason=store.status_reason,
        approved_at=store.approved_at,
        reviewed_by=_person(store.reviewed_by),
        commission_rate_bps=store.commission_rate_bps,
        effective_commission_rate_bps=effective_commission_bps(db, store),
        history=[
            StoreHistoryEntry(
                status=entry.status,  # type: ignore[arg-type]
                reason=entry.reason,
                store_name=entry.store_name,
                actor=_person(entry.actor),
                created_at=entry.created_at,
            )
            for entry in store.history
        ],
    )
