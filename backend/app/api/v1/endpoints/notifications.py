import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.notifier import Notifier
from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import ERR, FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import require_permission
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.schemas.notifications import (
    NotificationChannel,
    NotificationEvent,
    NotificationItem,
    NotificationStatus,
)
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.services import notification_service

router = APIRouter(prefix="/staff/notifications", tags=["Staff Notifications"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
Manager = Annotated[User, Depends(require_permission(Permission.NOTIFICATIONS_MANAGE))]

AUTH_ERRORS: ResponseMap = {401: UNAUTHORIZED_401[401], 403: FORBIDDEN_403[403]}


@router.get(
    "",
    response_model=Page[NotificationItem],
    summary="Notification log",
    description=(
        "Requires 'notifications:manage' (administrator). Every outbox message, newest first: "
        "order placed (customer and staff alert), payment received, order confirmed, "
        "dispatched, delivered and cancelled (SMS or email), and the welcome, quote request and "
        "review emails. Recipients are masked, no message text is shown, and `last_error` is a "
        "sanitised code. With the mock provider (§7 Q22) a 'sent' notification reached nobody."
    ),
    responses={**AUTH_ERRORS, **VALIDATION_422},
)
def list_notifications(
    _: Manager,
    db: Db,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
    status: NotificationStatus | None = None,
    channel: NotificationChannel | None = None,
    event: NotificationEvent | None = None,
    order_id: uuid.UUID | None = None,
) -> Page[NotificationItem]:
    return notification_service.staff_list(
        db,
        status=status,
        channel=channel,
        event=event,
        order_id=order_id,
        page=page,
        size=size,
    )


@router.post(
    "/{notification_id}/retry",
    response_model=NotificationItem,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a notification now",
    description=(
        "Requires 'notifications:manage' (administrator). Makes a pending or failed notification "
        "that has attempts left due now and sends it after the response; the result appears in "
        "the log. It does not add attempts: 3 in all. Audited as 'notification.retry' (refusals "
        "too). Without a configured provider the notification stays due for the retry job."
    ),
    responses={
        **AUTH_ERRORS,
        404: {**ERR, "description": "notification_not_found"},
        409: {
            **ERR,
            "description": "notification_already_sent, notification_attempts_exhausted, or "
            "notification_in_progress (a worker is sending it now)",
        },
        **VALIDATION_422,
    },
)
def retry_notification(
    notification_id: uuid.UUID,
    current_user: Manager,
    db: Db,
    ctx: Ctx,
    background: BackgroundTasks,
    notifier: Notifier,
) -> NotificationItem:
    item = notification_service.request_retry(db, notification_id, current_user, ctx)
    notifier.schedule(background, db)
    return item
