"""Transactional messages (module 17 outbox; docs/deployment/email.md).

Events, each recorded by the business change it reports:
- order placed ('received', checkout) to the customer, and 'staff_new_order' to every address
  in STAFF_ORDER_ALERT_EMAILS;
- payment received ('payment_succeeded': a mobile-money success, or cash on delivery recorded);
- an order moving to 'confirmed', 'dispatched', 'delivered' or 'cancelled' (staff status
  changes, the expiry job's payment_timeout cancellation, and a late payment's cancellation);
- 'welcome' (registration), 'quote_received' (a quote request with an email) and
  'review_thanks' (a submitted review), 'support_reply' (a staff reply to a support
  message) and 'service_received' (a service request with an email; ADR-013), by email.
Customer order messages follow §7 Q22: SMS when the order has a phone, otherwise email; with
NOTIFICATION_PROVIDER=smtp, which can only send email, they go to the order's email address, and
an order without one gets none. Nothing is recorded while NOTIFICATION_PROVIDER is 'none'.

Content: nothing but the event and the record it is about (subject_type, subject_id) is stored.
The message is rendered when it is claimed for sending (app.services.email_templates): HTML with
a plain-text alternative for email, one line for SMS, with links from SITE_URL. With
EMAIL_ALLOWED_RECIPIENTS set, email to any other address is recorded as refused
('recipient_not_allowed') and never handed to the provider.

After commit only (transactional outbox): record_order_event inserts the notification_logs row
inside the order's own transaction, under a savepoint. A rolled-back order change therefore
leaves no row and sends nothing, and a committed one cannot lose its row when the process stops
right after the commit. A failed insert rolls back only its savepoint and is logged: it never
fails or undoes the order change. Nothing is sent inside that transaction.

Delivery (deliver), one notification at a time: a short transaction claims the next due row
with FOR UPDATE SKIP LOCKED, counts the provider attempt about to be made and sets a lease
(claimed_until); the provider is called at once, outside any transaction, while a helper thread
renews the lease in short transactions for as long as the call runs; then a second short
transaction records the result, only if the row still carries this claim (attempts unchanged:
the fencing check). A row is claimed only when it is about to be sent, so it never waits behind
other provider calls with its lease running, and a slow call keeps its lease. Concurrent workers
never claim the same row. A worker that stops (its renewals stop with it) is replaced once its
lease ends. If a result cannot be recorded the batch stops, so later rows keep their attempts.
Callers: a background task after the HTTP response (HttpNotifier.schedule) and
scripts/retry_notifications.py on a schedule (cron).

Retries (bounded): at most 3 attempts. After a failed attempt the next is due 5 minutes, then 30
minutes later; after the third the row is failed for good. A provider error marked permanent
ends the retries at once. Only a sanitised code is stored in last_error (never provider text,
message text or credentials); logs carry IDs and codes only, never the recipient.

Outcomes: a DeliveryError other than a timeout is a confirmed failure (the provider refused the
message). 'timeout', 'invalid_provider_response', 'unexpected_error:<type>' and
'outcome_unknown' (an attempt whose lease ended with no recorded result: the worker stopped, or
its result could not be stored) are unknown outcomes: the provider may have accepted the message.
A timeout is never taken to mean "not delivered".

Delivery guarantee: at most 3 provider calls per message, never two at once while the worker
making a call can reach the database to renew its lease. attempts counts calls initiated: it is
incremented in the claim, immediately before the call, so a process stopping in between counts
one call that was not made (labelled outcome_unknown) and never misses one that was. After an
unknown outcome the next attempt sends the same idempotency key, which only a provider with
idempotent delivery (NotificationProvider.idempotent_delivery) uses to drop the duplicate.
Without it a customer can receive a message twice; a database transaction alone cannot prevent
that. Providers must still time out (DeliveryTimeout): a call that never returns keeps its row
claimed (in_progress) and its worker busy.
"""

import logging
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import TracebackType
from typing import Any, Literal
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.errors import Conflict, NotFound
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.integrations.notifications import (
    Channel,
    DeliveryError,
    NotificationProvider,
    OutboundMessage,
    email_allowed,
)
from app.models.catalog import Product
from app.models.commerce import (
    MAX_NOTIFICATION_ATTEMPTS,
    ORDER_STATUS_EVENTS,
    NotificationLog,
    Order,
    PaymentAttempt,
)
from app.models.content import QuoteRequest
from app.models.engagement import ProductReview
from app.models.identity import User
from app.models.services import ServiceRequest
from app.models.support import SupportMessage
from app.schemas.notifications import NotificationItem
from app.schemas.pagination import Page, page_offset
from app.services import email_templates as tpl
from app.services.audit_service import AuditService
from app.services.promotion_service import database_now
from app.services.support_access import guest_path

logger = logging.getLogger("app.notifications")

Event = Literal["confirmed", "dispatched", "delivered", "cancelled"]
CustomerOrderEvent = Literal[
    "received", "payment_succeeded", "confirmed", "dispatched", "delivered", "cancelled"
]
EmailEvent = Literal[
    "welcome", "quote_received", "review_thanks", "support_reply", "service_received"
]
SubjectType = Literal["order", "user", "quote", "review", "support", "service"]
CUSTOMER_ORDER_EVENTS = ("received", "payment_succeeded", *ORDER_STATUS_EVENTS)
EMAIL_SUBJECTS: dict[str, SubjectType] = {
    "welcome": "user",
    "quote_received": "quote",
    "review_thanks": "review",
    "support_reply": "support",  # subject: the staff reply (one email per reply)
    "service_received": "service",  # subject: the service request (ADR-013)
}
SessionFactory = Callable[[], Session]

# After failed attempt 1 and 2 (no retry after attempt 3).
RETRY_DELAYS = (timedelta(minutes=5), timedelta(minutes=30))
# How long a claim lasts without renewal, and how often the sending worker renews it while the
# provider call runs (several renewals may fail before the lease ends).
CLAIM_LEASE = timedelta(minutes=2)
LEASE_RENEWAL = timedelta(seconds=30)
SESSION_INFO_KEY = "notification_ids"
MAX_ERROR_LENGTH = 200
OUTCOME_UNKNOWN = "outcome_unknown"
NOT_ALLOWED = "recipient_not_allowed"  # EMAIL_ALLOWED_RECIPIENTS excludes the address
SUBJECT_MISSING = "subject_missing"  # the record the message is about no longer exists
UNCERTAIN_ERRORS = frozenset(
    {"timeout", "connection_lost", "invalid_provider_response", OUTCOME_UNKNOWN}
)
CANONICAL_PHONE = re.compile(r"^\+2507[0-9]{8}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")

NOT_FOUND = "Notification not found."
ALREADY_SENT = "This notification has already been sent."
IN_PROGRESS = "This notification is being sent now; try again in a few minutes."
EXHAUSTED = f"This notification has used all {MAX_NOTIFICATION_ATTEMPTS} delivery attempts."


def recipient_for(order: Order) -> tuple[Channel, str] | None:
    """§7 Q22: SMS to the order's phone when it is a canonical Rwandan mobile number, otherwise
    email to the order's email; None when the order has neither. The smtp provider sends only
    email, so with it the order's email is the only recipient."""
    email_only = get_settings().notification_provider == "smtp"
    if not email_only and order.recipient_phone and CANONICAL_PHONE.match(order.recipient_phone):
        return "sms", order.recipient_phone
    email = (order.customer_email_snapshot or "").strip()
    if email and len(email) <= 320 and EMAIL.match(email):
        return "email", email
    return None


def message_for(event: str, order_number: str) -> tuple[str, str]:
    """(subject, SMS text) of an order status message."""
    subject = tpl.STATUS_COPY[event][0].format(number=order_number)
    return subject, tpl.order_status_sms(event, order_number)


def notifications_enabled() -> bool:
    return get_settings().notification_provider != "none"


def _usable_email(value: str | None) -> str | None:
    email = (value or "").strip()
    return email if email and len(email) <= 320 and EMAIL.match(email) else None


def _enqueue(
    db: Session,
    *,
    event: str,
    channel: Channel,
    recipient: str,
    subject_type: SubjectType,
    subject_id: UUID,
    dedupe_key: str,
) -> None:
    """Insert one message in the caller's transaction, under a savepoint. Never raises: a
    message problem must not fail or undo the business change. A repeated dedupe_key (a replayed
    request, a second recording of one event) adds nothing. An email the allowlist excludes is
    recorded as refused at once, so it is visible and never sent."""
    allowed = channel != "email" or email_allowed(recipient)
    values: dict[str, Any] = {
        "order_id": subject_id if subject_type == "order" else None,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "dedupe_key": dedupe_key,
        "event": event,
        "channel": channel,
        "recipient": recipient,
        "attempts": 0,
    }
    if allowed:
        values |= {"status": "pending", "next_attempt_at": func.statement_timestamp()}
    else:
        values |= {"status": "failed", "next_attempt_at": None, "last_error": NOT_ALLOWED}
    try:
        with db.begin_nested():
            created = db.scalar(
                insert(NotificationLog)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
                .returning(NotificationLog.id)
            )
    except SQLAlchemyError as exc:
        logger.error(
            "Notification not recorded for %s %s (%s): %s",
            subject_type,
            subject_id,
            event,
            type(exc).__name__,
        )
        return
    if created is not None and allowed:
        db.info.setdefault(SESSION_INFO_KEY, []).append(created)
    elif created is not None:
        logger.info("Notification %s (%s) not sent: recipient not allowed", created, event)


def record_order_event(db: Session, order: Order, event: CustomerOrderEvent) -> None:
    """Record a customer message about the order in the caller's (order) transaction. Never
    raises: a notification problem must not fail or undo the order change."""
    if event not in CUSTOMER_ORDER_EVENTS or not notifications_enabled():
        return
    target = recipient_for(order)
    if target is None:
        logger.warning("No notification for order %s (%s): no usable recipient", order.id, event)
        return
    channel, recipient = target
    _enqueue(
        db,
        event=event,
        channel=channel,
        recipient=recipient,
        subject_type="order",
        subject_id=order.id,
        dedupe_key=f"order:{order.id}:{event}:{channel}",
    )


def record_order_placed(db: Session, order: Order) -> None:
    """Checkout: the customer's order confirmation and the staff alert, one per address in
    STAFF_ORDER_ALERT_EMAILS. Never raises."""
    record_order_event(db, order, "received")
    if not notifications_enabled():
        return
    for address in get_settings().staff_order_alert_recipients:
        _enqueue(
            db,
            event="staff_new_order",
            channel="email",
            recipient=address,
            subject_type="order",
            subject_id=order.id,
            dedupe_key=f"order:{order.id}:staff_new_order:email:{address}",
        )


def record_email_event(
    db: Session, event: EmailEvent, subject_id: UUID, recipient: str | None
) -> None:
    """A message about a user, quote request or review, by email only (nothing is sent without
    a usable address). Never raises."""
    email = _usable_email(recipient)
    if email is None or not notifications_enabled():
        return
    subject_type = EMAIL_SUBJECTS[event]
    _enqueue(
        db,
        event=event,
        channel="email",
        recipient=email,
        subject_type=subject_type,
        subject_id=subject_id,
        dedupe_key=f"{subject_type}:{subject_id}:{event}",
    )


def take_recorded_ids(db: Session) -> list[UUID]:
    """The IDs recorded on this session since the last call. A rolled-back ID matches no row, so
    delivering it does nothing."""
    ids: list[UUID] = db.info.pop(SESSION_INFO_KEY, [])
    return ids


# ---- delivery --------------------------------------------------------------------------------
@dataclass(frozen=True)
class Claim:
    id: UUID
    attempt: int
    channel: Channel
    recipient: str
    event: str
    message: tpl.Rendered | None  # None: the subject no longer exists (sent as subject_missing)


# ---- rendering (inside the claim's transaction) ---------------------------------------------
def _link(label: str, path: str, *, locale: str = "en") -> tpl.Link | None:
    base = get_settings().public_site_url
    if base is None:
        return None
    prefix = "" if locale == "en" else f"/{locale}"
    return tpl.Link(label, f"{base}{prefix}{path}")


def _address_lines(snapshot: dict[str, Any]) -> list[str]:
    def joined(*keys: str) -> str:
        values = (str(snapshot.get(k) or "").strip() for k in keys)
        return ", ".join(v for v in values if v)

    lines = [
        joined("recipient_name"),
        joined("street_address"),
        joined("village", "cell", "sector"),
        joined("district", "province"),
    ]
    if str(snapshot.get("delivery_instructions") or "").strip():
        lines.append(f"Instructions: {str(snapshot['delivery_instructions']).strip()}")
    return [line for line in lines if line]


def _variant(snapshot: dict[str, Any] | None) -> str | None:
    name = str((snapshot or {}).get("name") or "").strip()
    return name if name and name.lower() != "default" else None


def _payment_method(db: Session, order: Order) -> str | None:
    return db.scalar(
        select(PaymentAttempt.method)
        .where(PaymentAttempt.order_id == order.id)
        .order_by(PaymentAttempt.created_at.desc(), PaymentAttempt.id)
        .limit(1)
    )


def _summary(db: Session, order: Order) -> tpl.OrderSummary:
    return tpl.OrderSummary(
        number=order.order_number,
        customer_name=order.recipient_name,
        lines=[
            tpl.OrderLine(
                name=item.product_name_snapshot,
                variant=_variant(item.variant_snapshot),
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item in sorted(order.items, key=lambda i: (i.created_at, i.id))
        ],
        subtotal=order.subtotal,
        discount_total=order.discount_total,
        delivery_fee=order.delivery_fee,
        tax_total=order.tax_total,
        total=order.total,
        payment_method=_payment_method(db, order),
        discount_label=order.discount_code_snapshot or order.discount_name_snapshot,
        delivery_zone=order.delivery_zone_snapshot,
        address_lines=_address_lines(order.delivery_address_snapshot or {}),
        phone=order.recipient_phone,
        email=order.customer_email_snapshot,
        note=order.customer_note,
    )


def _order_link(order: Order) -> tpl.Link | None:
    """Signed-in customers: their order page. Guests: order tracking, with the number filled."""
    if order.user_id is not None:
        return _link("View your order", f"/account/orders/{order.order_number}")
    return _link("Track your order", f"/track?order={order.order_number}")


def _render_order(db: Session, event: str, order: Order) -> tpl.Rendered:
    summary = _summary(db, order)
    if event == "received":
        return tpl.order_received(summary, _order_link(order))
    if event == "staff_new_order":
        base = get_settings().public_site_url
        admin = tpl.Link("Open in admin", f"{base}/admin/orders/{order.id}") if base else None
        return tpl.staff_new_order(summary, admin)
    if event == "payment_succeeded":
        paid = db.execute(
            select(PaymentAttempt.amount, PaymentAttempt.method)
            .where(PaymentAttempt.order_id == order.id, PaymentAttempt.status == "succeeded")
            .order_by(PaymentAttempt.succeeded_at.desc().nulls_last(), PaymentAttempt.id)
            .limit(1)
        ).first()
        amount, method = (paid.amount, paid.method) if paid else (order.total, None)
        return tpl.payment_succeeded(summary, amount, method, _order_link(order))
    return tpl.order_status(event, summary, _order_link(order))


def _safe_render(db: Session, row: NotificationLog) -> tpl.Rendered | None:
    try:
        with db.begin_nested():
            return _render(db, row)
    except Exception as exc:  # a broken subject must not stop the batch; recorded as final
        logger.error("Notification %s not rendered: %s", row.id, type(exc).__name__)
        return None


def _render(db: Session, row: NotificationLog) -> tpl.Rendered | None:
    """The message for a claimed row, from the current state of its subject."""
    if row.subject_type == "order":
        order = db.get(Order, row.subject_id)
        return _render_order(db, row.event, order) if order is not None else None
    if row.subject_type == "user":
        user = db.get(User, row.subject_id)
        if user is None:
            return None
        name = (user.full_name or "").strip() or "there"
        return tpl.welcome(name, _link("Start shopping", "/products"))
    if row.subject_type == "quote":
        quote = db.get(QuoteRequest, row.subject_id)
        if quote is None:
            return None
        lines = [
            (str(line.get("product", "")), int(line.get("quantity", 0))) for line in quote.lines
        ]
        link = _link("Browse products", "/products", locale=quote.locale or "en")
        return tpl.quote_received(quote.reference, quote.contact_name, quote.company, lines, link)
    if row.subject_type == "service":
        request = db.get(ServiceRequest, row.subject_id)
        if request is None:
            return None
        link = _link(
            "See our services", f"/services/{request.service.slug}", locale=request.locale or "en"
        )
        return tpl.service_received(
            request.reference, request.full_name, request.service.name_en, link
        )
    if row.subject_type == "review":
        found = db.execute(
            select(ProductReview.author_name, Product.name, Product.slug)
            .join(Product, Product.id == ProductReview.product_id)
            .where(ProductReview.id == row.subject_id)
        ).first()
        if found is None:
            return None
        author, product, slug = found
        return tpl.review_thanks(author, product, _link("View the product", f"/product/{slug}"))
    if row.subject_type == "support":
        reply = db.get(SupportMessage, row.subject_id)
        if reply is None:
            return None
        thread = reply.thread
        locale = thread.locale or "en"
        path = (
            f"/account/messages/{thread.reference}"
            if thread.customer_user_id is not None
            else guest_path(thread.reference, thread.id)
        )
        link = _link("View the reply", path, locale=locale)
        return tpl.support_reply(
            thread.reference,
            thread.name,
            thread.subject,
            reply.body,
            link,
            has_account=thread.customer_user_id is not None,
        )
    return None


@dataclass
class DeliveryResult:
    sent: int = 0
    retry_scheduled: int = 0
    failed: int = 0
    lost_claims: int = 0

    @property
    def claimed(self) -> int:
        return self.sent + self.retry_scheduled + self.failed + self.lost_claims


def _due(now: datetime) -> Any:
    return and_(
        NotificationLog.status.in_(("pending", "failed")),
        NotificationLog.next_attempt_at.is_not(None),
        NotificationLog.next_attempt_at <= now,
        NotificationLog.attempts < MAX_NOTIFICATION_ATTEMPTS,
        or_(NotificationLog.claimed_until.is_(None), NotificationLog.claimed_until <= now),
    )


def _claim_next(db: Session, ids: Sequence[UUID] | None) -> Claim | None:
    """Claim the next due row for a provider call made immediately afterwards: count the attempt
    and start the lease. A failure here rolls back and counts nothing."""
    with atomic(db):
        now = database_now(db)
        query = (
            select(NotificationLog)
            .where(_due(now))
            .order_by(NotificationLog.next_attempt_at, NotificationLog.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if ids is not None:
            query = query.where(NotificationLog.id.in_(ids))
        row = db.scalar(query)
        if row is None:
            return None
        if row.claimed_until is not None:
            # The previous attempt's lease ended with no recorded result: it may have been sent.
            row.last_error = OUTCOME_UNKNOWN
            logger.warning("Notification %s: attempt %s outcome unknown", row.id, row.attempts)
        row.attempts += 1
        row.claimed_until = now + CLAIM_LEASE
        return Claim(
            row.id,
            row.attempts,
            row.channel,  # type: ignore[arg-type]
            row.recipient,
            row.event,
            _safe_render(db, row),
        )


def _renew(db: Session, claim: Claim) -> bool:
    """Extend the claim's lease if the row still carries it. False: the claim was lost."""
    with atomic(db):
        now = database_now(db)
        renewed = db.execute(
            update(NotificationLog)
            .where(
                NotificationLog.id == claim.id,
                NotificationLog.attempts == claim.attempt,
                NotificationLog.claimed_until.is_not(None),
                NotificationLog.status != "sent",
            )
            .values(claimed_until=now + CLAIM_LEASE)
            .execution_options(synchronize_session=False)
        )
    return bool(getattr(renewed, "rowcount", 0))


class _LeaseKeeper:
    """Renews a claim's lease every LEASE_RENEWAL while its provider call runs, each time in its
    own short transaction, so a slow call is never overtaken by a second worker. A failed
    renewal is logged and tried again at the next interval; a lost claim stops the renewals."""

    def __init__(self, session_factory: SessionFactory, claim: Claim) -> None:
        self._session_factory = session_factory
        self._claim = claim
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"notification-lease-{claim.id}", daemon=True
        )

    def __enter__(self) -> "_LeaseKeeper":
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        claim = self._claim
        while not self._stop.wait(LEASE_RENEWAL.total_seconds()):
            try:
                with self._session_factory() as db:
                    if not _renew(db, claim):
                        logger.warning(
                            "Notification %s: attempt %s lost its claim", claim.id, claim.attempt
                        )
                        return
            except Exception as exc:
                logger.warning(
                    "Notification %s: lease not renewed (%s)", claim.id, type(exc).__name__
                )


def outcome_unknown(error: str | None) -> bool:
    """True when a stored error code means the provider may have accepted the message."""
    return error is not None and (
        error in UNCERTAIN_ERRORS or error.startswith("unexpected_error:")
    )


def sanitise_error(exc: BaseException) -> tuple[str, bool]:
    """(stored code, retryable). Provider text never leaves this function."""
    if isinstance(exc, DeliveryError):
        return exc.code, exc.retryable
    if isinstance(exc, TimeoutError):
        return "timeout", True
    name = re.sub(r"[^A-Za-z0-9_]", "", type(exc).__name__)[:60] or "Exception"
    return f"unexpected_error:{name}"[:MAX_ERROR_LENGTH], True


def _send(provider: NotificationProvider, claim: Claim) -> tuple[str | None, str | None, bool]:
    """(provider message ID, error code, retryable). Never raises."""
    if claim.message is None:
        return None, SUBJECT_MISSING, False
    if claim.channel == "email" and not email_allowed(claim.recipient):
        return None, NOT_ALLOWED, False  # the allowlist changed since it was recorded
    sms = claim.channel == "sms"
    message = OutboundMessage(
        channel=claim.channel,
        recipient=claim.recipient,
        subject=claim.message.subject,
        text=claim.message.sms if sms else claim.message.text,
        idempotency_key=f"notification:{claim.id}",
        html=None if sms else claim.message.html,
    )
    try:
        message_id = provider.send(message)
    except Exception as exc:  # isolated: no provider failure reaches the caller
        code, retryable = sanitise_error(exc)
        return None, code, retryable
    if not isinstance(message_id, str) or not message_id.strip():
        return None, "invalid_provider_response", True
    return message_id.strip()[:128], None, False


def _record(
    db: Session, claim: Claim, message_id: str | None, error: str | None, retryable: bool
) -> str:
    """Store one attempt's result if the row still carries this claim. Returns the outcome."""
    with atomic(db):
        row = db.scalar(
            select(NotificationLog)
            .where(
                NotificationLog.id == claim.id,
                NotificationLog.attempts == claim.attempt,
                NotificationLog.claimed_until.is_not(None),
                NotificationLog.status != "sent",
            )
            .with_for_update()
        )
        if row is None:
            # The lease ended and another worker took the row (or recovery closed it).
            logger.warning("Notification %s: attempt %s lost its claim", claim.id, claim.attempt)
            return "lost_claims"
        now = database_now(db)
        row.claimed_until = None
        if message_id is not None:
            row.status = "sent"
            row.sent_at = now
            row.provider_message_id = message_id
            row.next_attempt_at = None
            row.last_error = None
            return "sent"
        row.status = "failed"
        row.last_error = error
        if retryable and row.attempts < MAX_NOTIFICATION_ATTEMPTS:
            row.next_attempt_at = now + RETRY_DELAYS[row.attempts - 1]
            return "retry_scheduled"
        row.next_attempt_at = None
        return "failed"


def deliver(
    session_factory: SessionFactory,
    provider: NotificationProvider,
    *,
    ids: Sequence[UUID] | None = None,
    limit: int = 100,
) -> DeliveryResult:
    """Send up to `limit` due notifications (only `ids` when given), claiming each just before
    its provider call. Safe to run concurrently. A database error stops the batch and is raised:
    rows not yet claimed keep their attempts, and a row whose result was not stored is due again
    when its lease ends (outcome unknown)."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    result = DeliveryResult()
    if ids is not None and not ids:
        return result
    for _ in range(limit):
        with session_factory() as db:
            claim = _claim_next(db, ids)
        if claim is None:
            break
        with _LeaseKeeper(session_factory, claim):
            message_id, error, retryable = _send(provider, claim)
        try:
            with session_factory() as db:
                outcome = _record(db, claim, message_id, error, retryable)
        except Exception as exc:
            logger.error(
                "Notification %s attempt %s: result not recorded (%s); due again with an unknown "
                "outcome when its lease ends",
                claim.id,
                claim.attempt,
                type(exc).__name__,
            )
            raise
        setattr(result, outcome, getattr(result, outcome) + 1)
        if outcome == "sent":
            logger.info("Notification %s sent (attempt %s)", claim.id, claim.attempt)
        elif outcome != "lost_claims":
            logger.warning(
                "Notification %s attempt %s failed: %s (%s; %s)",
                claim.id,
                claim.attempt,
                error,
                "outcome unknown" if outcome_unknown(error) else "refused by the provider",
                "retry scheduled" if outcome == "retry_scheduled" else "final",
            )
    return result


def close_abandoned(db: Session) -> int:
    """A worker that stopped after its third claim leaves a row nobody may retry: mark it failed
    (outcome unknown: the provider may have delivered it). Rows with attempts left need nothing:
    they are due again once their lease ends."""
    with atomic(db):
        now = database_now(db)
        rows = db.scalars(
            select(NotificationLog)
            .where(
                NotificationLog.status.in_(("pending", "failed")),
                NotificationLog.attempts >= MAX_NOTIFICATION_ATTEMPTS,
                NotificationLog.claimed_until.is_not(None),
                NotificationLog.claimed_until <= now,
            )
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            row.status = "failed"
            row.last_error = OUTCOME_UNKNOWN
            row.next_attempt_at = None
            row.claimed_until = None
            logger.warning("Notification %s: last attempt abandoned, outcome unknown", row.id)
    return len(rows)


def deliver_quietly(
    session_factory: SessionFactory, provider: NotificationProvider, ids: Sequence[UUID]
) -> None:
    """Background-task entry point: never raises (the response has already been sent)."""
    try:
        deliver(session_factory, provider, ids=ids, limit=max(len(ids), 1))
    except Exception as exc:
        logger.error(
            "Notification delivery stopped: %s (the retry job will resume it)", type(exc).__name__
        )


@dataclass(frozen=True)
class HttpNotifier:
    """Per-request handle (FastAPI dependency): schedules delivery of the notifications this
    request recorded, after its response, on a fresh session bound to the request's engine."""

    engine: Engine | None
    provider: NotificationProvider | None

    def schedule(self, background: BackgroundTasks, db: Session) -> None:
        ids = take_recorded_ids(db)
        if not ids or self.provider is None or self.engine is None:
            return  # recorded rows stay due; the retry job sends them
        factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        background.add_task(deliver_quietly, factory, self.provider, ids)


# ---- staff -------------------------------------------------------------------------------------
def _mask(channel: str, recipient: str) -> str:
    if channel == "sms":
        return f"{recipient[:4]}{'*' * max(len(recipient) - 7, 0)}{recipient[-3:]}"
    local, _, domain = recipient.partition("@")
    return f"{local[:1]}***@{domain}"


def _item(row: NotificationLog, order_number: str | None, now: datetime) -> NotificationItem:
    return NotificationItem(
        id=row.id,
        order_id=row.order_id,
        order_number=order_number,
        subject_type=row.subject_type,  # type: ignore[arg-type]
        event=row.event,  # type: ignore[arg-type]
        channel=row.channel,  # type: ignore[arg-type]
        recipient=_mask(row.channel, row.recipient),
        status=row.status,  # type: ignore[arg-type]
        attempts=row.attempts,
        max_attempts=MAX_NOTIFICATION_ATTEMPTS,
        in_progress=row.claimed_until is not None and row.claimed_until > now,
        last_error=row.last_error,
        provider_message_id=row.provider_message_id,
        next_attempt_at=row.next_attempt_at,
        sent_at=row.sent_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def staff_list(
    db: Session,
    *,
    status: str | None,
    channel: str | None,
    event: str | None,
    order_id: UUID | None,
    page: int,
    size: int,
) -> Page[NotificationItem]:
    conditions = []
    if status is not None:
        conditions.append(NotificationLog.status == status)
    if channel is not None:
        conditions.append(NotificationLog.channel == channel)
    if event is not None:
        conditions.append(NotificationLog.event == event)
    if order_id is not None:
        conditions.append(NotificationLog.order_id == order_id)
    total = db.scalar(select(func.count(NotificationLog.id)).where(*conditions)) or 0
    rows = db.execute(
        select(NotificationLog, Order.order_number)
        .outerjoin(Order, Order.id == NotificationLog.order_id)
        .where(*conditions)
        .order_by(NotificationLog.created_at.desc(), NotificationLog.id)
        .offset(page_offset(page, size))
        .limit(size)
    ).all()
    now = database_now(db)
    return Page(
        items=[_item(row, number, now) for row, number in rows], total=total, page=page, size=size
    )


class _Ineligible(Exception):
    def __init__(self, code: str, message: str, row: NotificationLog) -> None:
        self.code = code
        self.message = message
        self.status = row.status
        self.attempts = row.attempts


def request_retry(
    db: Session, notification_id: UUID, actor: User, ctx: RequestContext
) -> NotificationItem:
    """notifications:manage: make a pending or failed notification with attempts left due now.
    It does not add attempts (at most 3 in all). Audited as 'notification.retry'."""
    try:
        with atomic(db):
            row = db.scalar(
                select(NotificationLog)
                .where(NotificationLog.id == notification_id)
                .with_for_update()
            )
            if row is None:
                raise NotFound(NOT_FOUND, code="notification_not_found")
            now = database_now(db)
            if row.status == "sent":
                raise _Ineligible("notification_already_sent", ALREADY_SENT, row)
            if row.claimed_until is not None and row.claimed_until > now:
                raise _Ineligible("notification_in_progress", IN_PROGRESS, row)
            if row.attempts >= MAX_NOTIFICATION_ATTEMPTS:
                raise _Ineligible("notification_attempts_exhausted", EXHAUSTED, row)
            row.next_attempt_at = now
            AuditService.log_event(
                db,
                action="notification.retry",
                status="success",
                actor=actor,
                entity_type="notification",
                entity_id=row.id,
                context=ctx,
                details={
                    "order_id": str(row.order_id) if row.order_id else None,
                    "subject_type": row.subject_type,
                    "event": row.event,
                    "channel": row.channel,
                    "notification_status": row.status,
                    "attempts": row.attempts,
                },
            )
            db.flush()
            db.info.setdefault(SESSION_INFO_KEY, []).append(row.id)
            order_number = db.scalar(select(Order.order_number).where(Order.id == row.order_id))
            item = _item(row, order_number, now)
    except _Ineligible as exc:
        AuditService.record_standalone(
            db,
            action="notification.retry",
            status="conflict",
            actor=actor,
            entity_type="notification",
            entity_id=notification_id,
            context=ctx,
            details={
                "reason": exc.code,
                "notification_status": exc.status,
                "attempts": exc.attempts,
            },
        )
        raise Conflict(exc.message, code=exc.code) from None
    return item
