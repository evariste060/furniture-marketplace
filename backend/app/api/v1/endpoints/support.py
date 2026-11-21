"""Customer support messages (approved 2026-11-11). Rules are in app.services.support.

POST /support-messages is public (a signed-in customer's message is linked to their account) and
rate limited. /customers/me/support-threads is for customer accounts. The staff routes need
'support:read' (administrator, sales, management) to read and 'support:reply' (administrator,
sales) to reply or change the status.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.payments import optional_user
from app.api.v1.notifier import Notifier
from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import (
    AUTHENTICATED,
    ERR,
    FORBIDDEN_403,
    INACTIVE_403,
    UNAUTHORIZED_401,
    VALIDATION_422,
    ResponseMap,
)
from app.core.dependencies import get_current_user, require_permission
from app.core.errors import Forbidden
from app.core.rate_limit import LoginRateLimiter, get_support_message_rate_limiter
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.models.support import SupportThread
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.schemas.support import (
    StaffSupportMessageItem,
    StaffSupportThreadDetail,
    StaffSupportThreadSummary,
    SupportCreated,
    SupportMessageCreate,
    SupportMessageItem,
    SupportReply,
    SupportStatus,
    SupportStatusRequest,
    SupportThreadDetail,
    SupportThreadSummary,
)
from app.services.support import SupportService, is_customer, summary_fields
from app.services.support_access import KEY_LENGTH, access_key

public_router = APIRouter(prefix="/support-messages", tags=["Support"])
customer_router = APIRouter(prefix="/customers/me/support-threads", tags=["Support"])
staff_router = APIRouter(prefix="/staff/support-threads", tags=["Support"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
Limiter = Annotated[LoginRateLimiter, Depends(get_support_message_rate_limiter)]
SupportReader = Annotated[User, Depends(require_permission(Permission.SUPPORT_READ))]
SupportReplier = Annotated[User, Depends(require_permission(Permission.SUPPORT_REPLY))]
GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
NOT_FOUND: ResponseMap = {404: {**ERR, "description": "support_thread_not_found"}}
LIMITED: ResponseMap = {
    429: {
        **ERR,
        "description": "rate_limited",
        "headers": {
            "Retry-After": {"description": "Seconds to wait", "schema": {"type": "integer"}}
        },
    },
    503: {**ERR, "description": "support_unavailable"},
}


def current_customer(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Customers only: staff accounts have no support conversations of their own."""
    if not is_customer(user):
        raise Forbidden("Messages are for customer accounts only.", code="customer_only")
    return user


Customer = Annotated[User, Depends(current_customer)]


def _summary(thread: SupportThread) -> SupportThreadSummary:
    return SupportThreadSummary(
        id=thread.id,
        reference=thread.reference,
        topic=thread.topic,  # type: ignore[arg-type]
        subject=thread.subject,
        order_number=thread.order_number,
        status=thread.status,  # type: ignore[arg-type]
        last_message_at=thread.last_message_at,
        created_at=thread.created_at,
        **summary_fields(thread),  # type: ignore[arg-type]
    )


def _detail(thread: SupportThread) -> SupportThreadDetail:
    return SupportThreadDetail(
        **_summary(thread).model_dump(),
        messages=[
            SupportMessageItem(id=m.id, author=m.author, body=m.body, created_at=m.created_at)  # type: ignore[arg-type]
            for m in thread.messages
        ],
    )


def _staff_summary(thread: SupportThread) -> StaffSupportThreadSummary:
    return StaffSupportThreadSummary(
        **_summary(thread).model_dump(),
        name=thread.name,
        phone=thread.phone,
        email=thread.email,
        has_account=thread.customer_user_id is not None,
    )


def _staff_detail(db: Session, thread: SupportThread) -> StaffSupportThreadDetail:
    names = SupportService.staff_names(db, thread)
    return StaffSupportThreadDetail(
        **_staff_summary(thread).model_dump(),
        locale=thread.locale,  # type: ignore[arg-type]
        messages=[
            StaffSupportMessageItem(
                id=m.id,
                author=m.author,  # type: ignore[arg-type]
                body=m.body,
                created_at=m.created_at,
                staff_name=names.get(m.staff_user_id) if m.staff_user_id else None,
            )
            for m in thread.messages
        ],
    )


# ---- public -----------------------------------------------------------------------------------
@public_router.post(
    "",
    response_model=SupportCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message to customer support",
    description=(
        "Public. Topic, name, subject and message (2-2,000 characters) are required, with a "
        "Rwandan mobile number or an email address (or both); an order number is optional. "
        "Sent with a customer's bearer token, the conversation is linked to their account "
        "(My messages); an invalid token answers 401 and an inactive account 403. Every message "
        "counts against a limit per sender and per network (429 with Retry-After); an "
        "unavailable limit store answers 503. Returns the reference and the private link key."
    ),
    responses={**UNAUTHORIZED_401, **INACTIVE_403, **VALIDATION_422, **LIMITED},
)
def send_support_message(
    req: SupportMessageCreate,
    db: Db,
    ctx: Ctx,
    limiter: Limiter,
    user: Annotated[User | None, Depends(optional_user)],
) -> SupportCreated:
    thread = SupportService.create(db, req, user, limiter, ctx)
    return SupportCreated(reference=thread.reference, access_key=access_key(thread.id))


AccessKey = Annotated[str, Path(min_length=KEY_LENGTH, max_length=KEY_LENGTH)]


@public_router.get(
    "/{reference}/{key}",
    response_model=SupportThreadDetail,
    summary="Read a support conversation by its private link",
    description=(
        "Public, for senders without an account. The key comes with the reference when the "
        "message is sent and in the reply email. A wrong reference or key answers 404."
    ),
    responses=NOT_FOUND,
)
def read_by_link(reference: str, key: AccessKey, db: Db) -> SupportThreadDetail:
    return _detail(SupportService.guest_thread(db, reference, key))


@public_router.post(
    "/{reference}/{key}/messages",
    response_model=SupportThreadDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Reply in a support conversation by its private link",
    description=(
        "Public, for senders without an account. Reopens the conversation (status open). Counts "
        "against the support message limit (429 with Retry-After)."
    ),
    responses={**NOT_FOUND, **VALIDATION_422, **LIMITED},
)
def reply_by_link(
    reference: str, key: AccessKey, req: SupportReply, db: Db, ctx: Ctx, limiter: Limiter
) -> SupportThreadDetail:
    return _detail(SupportService.guest_reply(db, reference, key, req.body, limiter, ctx))


# ---- customers --------------------------------------------------------------------------------
CUSTOMER_ONLY: ResponseMap = {
    **AUTHENTICATED,
    403: {**ERR, "description": "customer_only: staff accounts have no messages; or inactive"},
}


@customer_router.get(
    "",
    response_model=Page[SupportThreadSummary],
    summary="List my support conversations",
    description="Customer accounts only. Most recent activity first.",
    responses={**CUSTOMER_ONLY, **VALIDATION_422},
)
def list_my_threads(
    user: Customer, db: Db, page: PageNumber = 1, size: PageSize = DEFAULT_PAGE_SIZE
) -> Page[SupportThreadSummary]:
    rows, total = SupportService.customer_page(db, user, page, size)
    return Page[SupportThreadSummary](
        items=[_summary(r) for r in rows], total=total, page=page, size=size
    )


@customer_router.get(
    "/{reference}",
    response_model=SupportThreadDetail,
    summary="Read one of my support conversations",
    description="Customer accounts only. Another customer's conversation answers 404.",
    responses={**CUSTOMER_ONLY, **NOT_FOUND},
)
def get_my_thread(reference: str, user: Customer, db: Db) -> SupportThreadDetail:
    return _detail(SupportService.customer_thread(db, user, reference))


@customer_router.post(
    "/{reference}/messages",
    response_model=SupportThreadDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Reply in one of my support conversations",
    description=(
        "Customer accounts only. Reopens the conversation (status open). Counts against the "
        "support message limit (429 with Retry-After)."
    ),
    responses={**CUSTOMER_ONLY, **NOT_FOUND, **VALIDATION_422, **LIMITED},
)
def reply_to_my_thread(
    reference: str, req: SupportReply, user: Customer, db: Db, ctx: Ctx, limiter: Limiter
) -> SupportThreadDetail:
    return _detail(SupportService.customer_reply(db, user, reference, req.body, limiter, ctx))


# ---- staff ------------------------------------------------------------------------------------
@staff_router.get(
    "",
    response_model=Page[StaffSupportThreadSummary],
    summary="List support conversations",
    description=(
        "Requires 'support:read' (administrator, sales, management). Most recent activity "
        "first. `status` filters; `q` searches reference, name, subject, email, phone and order "
        "number."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def list_support_threads(
    _: SupportReader,
    db: Db,
    status_filter: Annotated[SupportStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
) -> Page[StaffSupportThreadSummary]:
    rows, total = SupportService.staff_page(db, status_filter, q, page, size)
    return Page[StaffSupportThreadSummary](
        items=[_staff_summary(r) for r in rows], total=total, page=page, size=size
    )


@staff_router.get(
    "/{thread_id}",
    response_model=StaffSupportThreadDetail,
    summary="Read a support conversation",
    description="Requires 'support:read' (administrator, sales, management).",
    responses={**GUARDED, **NOT_FOUND},
)
def get_support_thread(thread_id: uuid.UUID, _: SupportReader, db: Db) -> StaffSupportThreadDetail:
    return _staff_detail(db, SupportService.staff_thread(db, thread_id))


@staff_router.post(
    "/{thread_id}/messages",
    response_model=StaffSupportThreadDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Reply to a support conversation",
    description=(
        "Requires 'support:reply' (administrator, sales). Sets the status to answered and "
        "emails the reply to the sender's address when they gave one. Audited as "
        "'support.reply'."
    ),
    responses={**GUARDED, **NOT_FOUND, **VALIDATION_422},
)
def reply_to_support_thread(
    thread_id: uuid.UUID,
    req: SupportReply,
    actor: SupportReplier,
    db: Db,
    ctx: Ctx,
    background: BackgroundTasks,
    notifier: Notifier,
) -> StaffSupportThreadDetail:
    thread = SupportService.staff_reply(db, actor, thread_id, req.body, ctx)
    notifier.schedule(background, db)  # the reply email
    return _staff_detail(db, thread)


@staff_router.patch(
    "/{thread_id}",
    response_model=StaffSupportThreadDetail,
    summary="Change a support conversation's status",
    description=(
        "Requires 'support:reply' (administrator, sales). open, answered or closed. Audited as "
        "'support.status_change'; setting the current status changes nothing and is not audited."
    ),
    responses={**GUARDED, **NOT_FOUND, **VALIDATION_422},
)
def change_support_status(
    thread_id: uuid.UUID, req: SupportStatusRequest, actor: SupportReplier, db: Db, ctx: Ctx
) -> StaffSupportThreadDetail:
    return _staff_detail(db, SupportService.set_status(db, actor, thread_id, req.status, ctx))
