"""Seller applications, the seller's own store, and seller management (ADR-014 phase 1).
Rules are in app.services.store_service.

/seller/application: any signed-in customer with a verified email (not staff).
/seller/store: require_approved_seller; the store is always the caller's own, from the database.
/staff/sellers: 'sellers:read' and 'sellers:manage', administrator only in V1.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.notifier import Notifier
from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import (
    AUTHENTICATED,
    ERR,
    FORBIDDEN_403,
    UNAUTHORIZED_401,
    VALIDATION_422,
    ResponseMap,
)
from app.core.dependencies import (
    SellerContext,
    get_current_user,
    require_approved_seller,
    require_permission,
)
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.schemas.stores import (
    SellerStoreResponse,
    StaffStoreDetail,
    StaffStoreSummary,
    StoreApplicationRequest,
    StoreCommissionRequest,
    StoreProfileUpdate,
    StoreStatus,
    StoreStatusRequest,
)
from app.services.store_service import (
    StoreService,
    seller_response,
    staff_detail,
    staff_summary,
)

seller_router = APIRouter(prefix="/seller", tags=["Seller"])
staff_router = APIRouter(prefix="/staff/sellers", tags=["Staff Sellers"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Seller = Annotated[SellerContext, Depends(require_approved_seller)]
SellerReader = Annotated[User, Depends(require_permission(Permission.SELLERS_READ))]
SellerManager = Annotated[User, Depends(require_permission(Permission.SELLERS_MANAGE))]
GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
NOT_APPROVED_403: ResponseMap = {
    403: {**ERR, "description": "account_inactive, or seller_not_approved (no approved store)"}
}
APPLY_403: ResponseMap = {
    403: {**ERR, "description": "staff_cannot_sell, email_verification_required or inactive"}
}
STORE_404: ResponseMap = {404: {**ERR, "description": "store_not_found"}}


# ---- the applicant -----------------------------------------------------------------------
@seller_router.post(
    "/application",
    response_model=SellerStoreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Apply to become a seller",
    description=(
        "Signed-in customers with a verified email. Creates the caller's store as 'pending'. One "
        "store per account: 409 store_exists. Store names are unique regardless of letter case: "
        "409 store_name_taken. The owner, status, slug and commission cannot be sent (422). "
        "Emails an acknowledgement to the account's verified email."
    ),
    responses={
        **UNAUTHORIZED_401,
        **APPLY_403,
        409: {**ERR, "description": "store_exists, store_name_taken or store_slug_conflict"},
        **VALIDATION_422,
    },
)
def submit_application(
    req: StoreApplicationRequest,
    user: CurrentUser,
    db: Db,
    ctx: Ctx,
    background: BackgroundTasks,
    notifier: Notifier,
) -> SellerStoreResponse:
    store = StoreService.apply(db, user, req, ctx)
    notifier.schedule(background, db)
    return seller_response(db, store)


@seller_router.get(
    "/application",
    response_model=SellerStoreResponse,
    summary="Read my seller application",
    description=(
        "The caller's own store in any status, with the reason while it is rejected or "
        "suspended. 404 store_not_found when the caller has not applied."
    ),
    responses={**AUTHENTICATED, **STORE_404},
)
def read_application(user: CurrentUser, db: Db) -> SellerStoreResponse:
    return seller_response(db, StoreService.own(db, user))


@seller_router.put(
    "/application",
    response_model=SellerStoreResponse,
    summary="Edit or resubmit my seller application",
    description=(
        "Sends every field again. A pending application is edited; a rejected one is resubmitted "
        "and becomes pending (acknowledged by email). Approved and suspended stores cannot use "
        "this route: 409 store_application_closed."
    ),
    responses={
        **UNAUTHORIZED_401,
        **APPLY_403,
        **STORE_404,
        409: {**ERR, "description": "store_application_closed or store_name_taken"},
        **VALIDATION_422,
    },
)
def update_application(
    req: StoreApplicationRequest,
    user: CurrentUser,
    db: Db,
    ctx: Ctx,
    background: BackgroundTasks,
    notifier: Notifier,
) -> SellerStoreResponse:
    store = StoreService.update_application(db, user, req, ctx)
    notifier.schedule(background, db)
    return seller_response(db, store)


# ---- the approved seller -----------------------------------------------------------------
@seller_router.get(
    "/store",
    response_model=SellerStoreResponse,
    summary="Read my store",
    description="Approved sellers only (403 seller_not_approved otherwise).",
    responses={**UNAUTHORIZED_401, **NOT_APPROVED_403},
)
def read_store(seller: Seller, db: Db) -> SellerStoreResponse:
    return seller_response(db, seller.store)


@seller_router.patch(
    "/store",
    response_model=SellerStoreResponse,
    summary="Update my store",
    description=(
        "Approved sellers only. Partial update of the name, description, contact details and "
        "location; the store's address (slug), status and commission cannot be changed here. "
        "Audited as 'store.profile_update'."
    ),
    responses={
        **UNAUTHORIZED_401,
        **NOT_APPROVED_403,
        409: {**ERR, "description": "store_name_taken"},
        **VALIDATION_422,
    },
)
def update_store(req: StoreProfileUpdate, seller: Seller, db: Db, ctx: Ctx) -> SellerStoreResponse:
    store = StoreService.update_profile(db, seller.user, seller.store.id, req, ctx)
    return seller_response(db, store)


# ---- administrators ----------------------------------------------------------------------
@staff_router.get(
    "",
    response_model=Page[StaffStoreSummary],
    summary="List stores and seller applications",
    description=(
        "Requires 'sellers:read' (administrator). Newest submission first. `status` filters; "
        "`q` matches the store name or address, or the owner's name or email."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def list_sellers(
    _: SellerReader,
    db: Db,
    status_filter: Annotated[StoreStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
) -> Page[StaffStoreSummary]:
    rows, total = StoreService.staff_page(db, status_filter, (q or "").strip() or None, page, size)
    return Page[StaffStoreSummary](
        items=[staff_summary(r) for r in rows], total=total, page=page, size=size
    )


@staff_router.get(
    "/{store_id}",
    response_model=StaffStoreDetail,
    summary="Read a store and its history",
    description="Requires 'sellers:read' (administrator).",
    responses={**GUARDED, **STORE_404, **VALIDATION_422},
)
def read_seller(store_id: uuid.UUID, _: SellerReader, db: Db) -> StaffStoreDetail:
    return staff_detail(db, StoreService.staff_get(db, store_id))


@staff_router.patch(
    "/{store_id}/status",
    response_model=StaffStoreDetail,
    summary="Approve, reject, suspend or reinstate a store",
    description=(
        "Requires 'sellers:manage' (administrator). pending -> approved or rejected; approved -> "
        "suspended; suspended -> approved (reinstated). A reason (10-500 characters) is required "
        "to reject or suspend and is shown to the seller. Anything else is 409 "
        "invalid_store_transition. Audited as 'store.status_change' and emailed to the owner."
    ),
    responses={
        **GUARDED,
        **STORE_404,
        409: {**ERR, "description": "invalid_store_transition"},
        **VALIDATION_422,
    },
)
def change_seller_status(
    store_id: uuid.UUID,
    req: StoreStatusRequest,
    actor: SellerManager,
    db: Db,
    ctx: Ctx,
    background: BackgroundTasks,
    notifier: Notifier,
) -> StaffStoreDetail:
    store = StoreService.change_status(db, actor, store_id, req, ctx)
    notifier.schedule(background, db)
    return staff_detail(db, store)


@staff_router.patch(
    "/{store_id}/commission",
    response_model=StaffStoreDetail,
    summary="Set a store's commission override",
    description=(
        "Requires 'sellers:manage' (administrator). Whole basis points 0-10000 (1000 = 10%), or "
        "null to inherit the platform default (setting marketplace.default_commission_bps). "
        "Audited as 'store.commission_change'; setting the current value changes nothing."
    ),
    responses={**GUARDED, **STORE_404, **VALIDATION_422},
)
def change_seller_commission(
    store_id: uuid.UUID, req: StoreCommissionRequest, actor: SellerManager, db: Db, ctx: Ctx
) -> StaffStoreDetail:
    store = StoreService.set_commission(db, actor, store_id, req.commission_rate_bps, ctx)
    return staff_detail(db, store)
