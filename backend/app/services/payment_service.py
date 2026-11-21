"""Payments (module 15; plan §5 "15 — payments"; ADR-002 lifecycle and payment consistency;
§7 Q11-Q14, Q17, Q21; TC-08-TC-12).

Access (§7 Q17): a signed-in customer pays and reads only their own order; a guest gives the
order's phone, checked like the guest lookup and counted on the same failed-lookup limits
(ADR-008 S6: 5 per order number, 20 per IP, 15 minutes, fail closed). Every mismatch is the
same 404.

Initiation: the order must be unpaid, not cancelled, dispatched or delivered, and (mobile
money) its stock hold must still be active. One attempt gets one provider call: the first
transaction claims the attempt (provider set, no reference yet) under the order's lock, and a
concurrent request finds the claim and gets 409 payment_initiation_in_progress. A claim older
than CLAIM_TIMEOUT is stale, but its outcome is unknown: the first call may still be running, or
the provider may have accepted it without its reference being saved. It is retried, with the
same idempotency key, only for a provider whose adapter sets idempotent_initiation (the mock and
COD). For any other provider the request gets 409 payment_initiation_needs_recovery and the
attempt is left unchanged: it is not marked failed, because the payment may exist.

Reconciliation records: what needs a person is written as a payment_events row from the
'internal' source (no webhook can produce it), needs_reconciliation, linked to the attempt (so
the staff payment lists flag it), audited ('payment.reconciliation'), with sanitised facts only,
once per (kind, attempt, reference) through the (provider, event_key) unique index. Their
verification_status is 'received': nothing in them is authenticated provider evidence. Kinds:
- initiation_needs_recovery: a stale claim for a provider without the idempotency guarantee.
- initiation_outcome_unknown: the adapter raised ProviderOutcomeUnknown (a timeout or transport
  error after sending) or an unexpected exception (only its type is logged). For an idempotent
  provider the claim is released and the request gets 502 (a retry is the same payment);
  otherwise the claim stays and the request gets 409
  payment_initiation_needs_recovery. ProviderError, by contract, means no payment started: the
  attempt fails.
- late_reference: the provider returned a reference after the attempt left 'created' (the hold
  expired or the order was cancelled during the call). The reference is kept on the attempt, so
  a later webhook for it is linked and handled as a late payment (needs_reconciliation; nothing
  committed or revived); the attempt's and the order's states are unchanged; the request gets
  409 payment_initiation_needs_recovery.
- conflicting_reference: a second, different reference for an attempt that already has one (or
  one another attempt holds); recorded, never written over the first.
These records survive the hold's expiry; resolving them is a finance process, not built.
A provider event that arrived before the attempt's reference was saved (an 'unknown reference')
is linked to the attempt once the reference is saved, but not applied: it stays
needs_reconciliation, so a person decides (audited as kind early_event_linked).
The provider is called outside any database transaction (ADR-002): a first transaction picks
or creates the attempt (a new one after a failed or cancelled attempt; earlier attempts are
kept), the provider call follows, and a second transaction records the reference. Cash on
delivery calls nothing: its attempt stays 'pending' until delivery (TC-12).

Webhooks (TC-11): authenticity is verified before anything is stored (a forged request writes
nothing). Then, in one transaction: the event is inserted unless (provider, event_key) is
already known (a duplicate answers 200 and repeats nothing; a concurrent duplicate waits on the
unique index and then sees the first); the order's locks are taken in the common order (advisory
lock, order row, attempt row); and the event is applied:
- success: the amount and currency must equal the attempt and the order total, else nothing is
  applied and the event needs reconciliation. A matched success commits the stock holds,
  marks the attempt 'succeeded' and issues the order's invoice in the same transaction (module
  16, §7 Q19; app.services.invoice_service). If the hold already lapsed (or was released),
  nothing is committed or resurrected (and no invoice is issued): the order is cancelled for
  payment timeout as the expiry job would, and the event needs reconciliation (ADR-002 late
  payment), for finance to refund or resolve.
- failure or cancellation: the attempt becomes 'failed' / 'cancelled' unless it already
  succeeded (a success never regresses). The hold is not released: the customer may retry until
  it lapses (D-Y2).
- pending: a 'created' attempt becomes 'pending' (a delayed outcome).
An event for an unknown reference is kept and needs reconciliation. Every applied event is
audited ('payment.event'); event metadata is allow-listed and phone numbers are masked.
"""

import hashlib
import logging
import uuid
from datetime import timedelta
from typing import NoReturn

from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import (
    AppError,
    Conflict,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
    field_error,
)
from app.core.rate_limit import LoginRateLimiter, RateLimitStoreUnavailable
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.integrations.payments import (
    METHOD_PROVIDERS,
    InvalidWebhook,
    MalformedWebhook,
    OrderForPayment,
    PaymentProvider,
    ProviderError,
    ProviderEvent,
    ProviderNotConfigured,
    ProviderOutcomeUnknown,
    WebhookRequest,
    get_provider,
)
from app.models import DeliveryZone, Order, PaymentAttempt, PaymentEvent
from app.models.identity import User
from app.schemas.pagination import Page, page_offset
from app.schemas.payments import (
    PaymentStatusResponse,
    StaffPaymentEventItem,
    StaffPaymentItem,
    StaffPaymentPage,
    WebhookAck,
)
from app.services.audit_service import AuditService, identifier_ref
from app.services.checkout_service import (
    CASH_ON_DELIVERY,
    HOLDS,
    MOBILE_MONEY,
    available_methods,
)
from app.services.inventory import (
    HoldNotActive,
    TransitionOutcome,
    cancel_unpaid_order,
    change_hold_expiry,
    commit_order_reservations,
    lock_order,
)
from app.services.invoice_service import issue_for_order
from app.services.notification_service import record_order_event
from app.services.order_service import reservation_expiry
from app.services.promotion_service import database_now, release_for_order

logger = logging.getLogger("app.payments")

ORDER_NOT_FOUND = "Order not found."
LOOKUP_LIMITED = "Too many failed order lookups; try again later."
LOOKUP_UNAVAILABLE = "Payments are temporarily unavailable; try again shortly."
ALREADY_PAID = "This order is already paid."
NOT_PAYABLE = "This order can no longer be paid."
METHOD_UNAVAILABLE = "This payment method is not available."
PROVIDER_UNAVAILABLE = "Mobile-money payment is not available right now."
PROVIDER_ERROR = "The payment provider could not start the payment; try again."
NOT_COD = "Only a cash-on-delivery payment can be confirmed this way."
NOT_DELIVERED = "Cash can be recorded as collected only once the order is delivered."
PAYMENT_NOT_FOUND = "Payment not found."
IN_PROGRESS = "This payment is being started; try again in a moment."
SWITCH_IN_PROGRESS = (
    "A payment request is still open; approve or decline it on your phone, or wait for it to "
    "expire, before choosing another method."
)
SWITCH_TOO_LATE = "This payment method's time to pay has passed for this order."
NEEDS_RECOVERY = (
    "This payment's start could not be confirmed. Please contact support; do not pay again."
)
# A claim older than this is stale: its request died or is stuck in the provider call.
CLAIM_TIMEOUT = timedelta(seconds=120)
# The source of the reconciliation records the service writes itself (payment_events.provider).
# No webhook can produce it: get_provider("internal") is None, so its route answers 404.
INTERNAL_SOURCE = "internal"
STALE_CLAIM = "stale initiation claim: the provider call's outcome is unknown"
OUTCOME_UNKNOWN = "the provider gave no answer: a payment may have started"

CLOSED_ORDER_STATUSES = ("cancelled", "dispatched", "delivered")


class BadGateway(AppError):
    status_code = 502
    code = "payment_provider_error"
    message = PROVIDER_ERROR


class InvalidSignature(AppError):
    status_code = 401
    code = "invalid_signature"
    message = "The webhook could not be verified."


class MalformedEvent(AppError):
    status_code = 422  # project convention: validation errors are 422, never 400
    code = "malformed_event"
    message = "The webhook payload is not a valid event."


# ---- access ----------------------------------------------------------------------------------
def _latest_attempt(
    db: Session, order_id: uuid.UUID, *, lock: bool = False
) -> PaymentAttempt | None:
    query = (
        select(PaymentAttempt)
        .where(PaymentAttempt.order_id == order_id)
        .order_by(PaymentAttempt.created_at.desc(), PaymentAttempt.id.desc())
        .limit(1)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def _accessible_order(
    db: Session,
    order_number: str,
    user: User | None,
    phone: str | None,
    limiter: LoginRateLimiter,
    ctx: RequestContext,
) -> Order:
    """A customer's own order, or a guest's order proved by its phone (§7 Q17)."""
    number = order_number.strip().upper()
    if user is not None:
        order = db.scalar(
            select(Order).where(Order.order_number == number, Order.user_id == user.id)
        )
        if order is None:
            raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
        return order
    if phone is None:
        raise field_error(("body", "phone"), "Guests give the order's phone number.")
    ref = identifier_ref(number)
    try:
        decision = limiter.check(ref, ctx.ip_address)
    except RateLimitStoreUnavailable:
        logger.error("Guest payment access refused: the rate-limit store is unavailable")
        raise ServiceUnavailable(LOOKUP_UNAVAILABLE, code="order_lookup_unavailable") from None
    if not decision.allowed:
        raise TooManyRequests(
            LOOKUP_LIMITED, code="rate_limited", headers={"Retry-After": str(decision.retry_after)}
        )
    order = db.scalar(
        select(Order).where(Order.order_number == number, Order.recipient_phone == phone)
    )
    if order is None:
        try:
            limiter.record_failure(ref, ctx.ip_address)
        except RateLimitStoreUnavailable:
            logger.error("Failed guest payment access not counted: rate-limit store unavailable")
        raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
    return order


def _status(db: Session, order: Order, attempt: PaymentAttempt, instructions: str | None = None):
    db.refresh(order)
    db.refresh(attempt)
    return PaymentStatusResponse(
        order_number=order.order_number,
        order_status=order.status,  # type: ignore[arg-type]
        method=attempt.method,  # type: ignore[arg-type]
        status=attempt.status,  # type: ignore[arg-type]
        amount=attempt.amount,
        currency_code=attempt.currency_code,
        provider=attempt.provider,
        reference=attempt.provider_reference,
        instructions=instructions,
        reservation_expires_at=reservation_expiry(db, order.id),
    )


def _record_reconciliation(
    db: Session,
    attempt: PaymentAttempt,
    kind: str,
    summary: str,
    user: User | None,
    ctx: RequestContext | None,
    *,
    reference: str | None = None,
) -> bool:
    """A durable reconciliation record for an attempt (a payment_events row from
    INTERNAL_SOURCE, needs_reconciliation, linked to the attempt, so the staff payment lists find
    it), audited. Sanitised facts only. Recorded once per (kind, attempt, reference): a repeat
    is a no-op and returns False. The caller holds the order's lock, inside a transaction."""
    digest = hashlib.sha256(reference.encode("utf8")).hexdigest()[:16] if reference else "none"
    order_status = db.scalar(select(Order.status).where(Order.id == attempt.order_id))
    metadata = {
        "event_type": kind,
        "provider": attempt.provider,
        "reference": reference,
        "method": attempt.method,
        "amount": attempt.amount,
        "currency": attempt.currency_code,
        "attempt_status": attempt.status,
        "order_status": order_status,
    }
    now = database_now(db)
    record_id = db.scalar(
        insert(PaymentEvent)
        .values(
            id=uuid.uuid4(),
            attempt_id=attempt.id,
            provider=INTERNAL_SOURCE,
            event_key=f"initiation:{kind}:{attempt.id}:{digest}",
            # Nothing here was authenticated (an initiate() answer is not signed provider
            # evidence), so the record is 'received', never 'verified' (ADR-002).
            verification_status="received",
            processing_status="needs_reconciliation",
            received_at=now,
            processed_at=now,
            result_summary=summary,
            payload_metadata={k: v for k, v in metadata.items() if v is not None},
        )
        .on_conflict_do_nothing(index_elements=["provider", "event_key"])
        .returning(PaymentEvent.id)
    )
    if record_id is None:
        return False
    _audit(
        db,
        "payment.reconciliation",
        attempt.order_id,
        user,
        ctx,
        {"attempt_id": str(attempt.id), "kind": kind, "record_id": str(record_id)},
    )
    logger.error(
        "Payment attempt %s (order %s) needs reconciliation: %s", attempt.id, attempt.order_id, kind
    )
    return True


def _record_late_reference(
    db: Session,
    attempt: PaymentAttempt,
    provider_name: str,
    reference: str,
    user: User | None,
    ctx: RequestContext | None,
) -> None:
    """The provider returned a reference the normal update cannot take (the attempt left
    'created', or holds another reference). The reference is kept on the attempt when the
    attempt has none and no other attempt holds it, so a later webhook for it is linked (and
    treated as a late payment); the attempt's and the order's states are left as they are."""
    taken = db.scalar(
        select(PaymentAttempt.id).where(
            PaymentAttempt.provider == provider_name,
            PaymentAttempt.provider_reference == reference,
            PaymentAttempt.id != attempt.id,
        )
    )
    if attempt.provider_reference in (None, reference) and taken is None:  # a repeat: same record
        attempt.provider = provider_name
        attempt.provider_reference = reference
        db.flush()
        kind, summary = (
            "late_reference",
            f"provider reference returned after the attempt was {attempt.status}",
        )
    else:
        kind, summary = (
            "conflicting_reference",
            "provider returned a reference the attempt cannot take: it has another, "
            "or another attempt holds it",
        )
    _record_reconciliation(db, attempt, kind, summary, user, ctx, reference=reference)


def _link_early_events(
    db: Session,
    attempt: PaymentAttempt,
    provider_name: str,
    user: User | None,
    ctx: RequestContext | None,
) -> None:
    """Link provider events that arrived before this attempt's reference was saved (kept as
    'unknown reference'), so the staff payment list flags the attempt. They are linked, not
    applied: they stay needs_reconciliation. Matches on the event metadata's "reference",
    which adapters must include (the mock does). The caller holds the order's lock."""
    linked = db.scalars(
        update(PaymentEvent)
        .where(
            PaymentEvent.provider == provider_name,
            PaymentEvent.attempt_id.is_(None),
            PaymentEvent.processing_status == "needs_reconciliation",
            PaymentEvent.payload_metadata["reference"].astext == attempt.provider_reference,
        )
        .values(attempt_id=attempt.id)
        .returning(PaymentEvent.id)
    ).all()
    if linked:
        _audit(
            db,
            "payment.reconciliation",
            attempt.order_id,
            user,
            ctx,
            {
                "attempt_id": str(attempt.id),
                "kind": "early_event_linked",
                "event_ids": [str(event_id) for event_id in linked],
            },
        )
        logger.error(
            "Payment attempt %s (order %s): %d provider event(s) arrived before its reference "
            "was saved; linked for reconciliation",
            attempt.id,
            attempt.order_id,
            len(linked),
        )


def _needs_recovery(
    db: Session,
    order_id: uuid.UUID,
    attempt_id: uuid.UUID,
    kind: str,
    summary: str,
    user: User | None,
    ctx: RequestContext | None,
) -> NoReturn:
    """Record that an attempt's initiation outcome is unknown, then refuse with 409
    payment_initiation_needs_recovery. The attempt is not marked failed: the payment may
    exist. The record outlives the hold's expiry."""
    with atomic(db):
        lock_order(db, order_id)
        attempt = db.get(PaymentAttempt, attempt_id, with_for_update=True, populate_existing=True)
        if attempt is not None and attempt.provider_reference is None:
            _record_reconciliation(db, attempt, kind, summary, user, ctx)
    raise Conflict(NEEDS_RECOVERY, code="payment_initiation_needs_recovery")


def _unknown_outcome(
    db: Session,
    provider: PaymentProvider,
    order_id: uuid.UUID,
    attempt_id: uuid.UUID,
    user: User | None,
    ctx: RequestContext | None,
) -> NoReturn:
    """The provider call ended without a definite answer. With the idempotency guarantee the
    claim is released (a retry with the same key is the same payment) and the request gets
    502; otherwise the claim stays, so nothing repeats the call, a reconciliation record is
    kept and the request gets 409. The attempt is never marked failed: the payment may exist."""
    if provider.idempotent_initiation:
        with atomic(db):
            lock_order(db, order_id)
            claimed = db.get(PaymentAttempt, attempt_id, with_for_update=True)
            if claimed is not None and claimed.provider_reference is None:
                claimed.provider = None
        raise BadGateway() from None
    _needs_recovery(
        db, order_id, attempt_id, "initiation_outcome_unknown", OUTCOME_UNKNOWN, user, ctx
    )


def _audit(
    db: Session, action: str, order_id: uuid.UUID, actor: User | None, ctx, details: dict
) -> None:
    AuditService.log_event(
        db=db,
        action=action,
        status="success",
        actor=actor,
        entity_type="order",
        entity_id=order_id,
        context=ctx,
        details=details,
    )


class PaymentService:
    @staticmethod
    def status(
        db: Session,
        order_number: str,
        user: User | None,
        phone: str | None,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
    ) -> PaymentStatusResponse:
        order = _accessible_order(db, order_number, user, phone, limiter, ctx)
        attempt = _latest_attempt(db, order.id)
        if attempt is None:
            raise NotFound(PAYMENT_NOT_FOUND, code="payment_not_found")
        return _status(db, order, attempt)

    @staticmethod
    def initiate(
        db: Session,
        order_number: str,
        user: User | None,
        phone: str | None,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
    ) -> PaymentStatusResponse:
        order = _accessible_order(db, order_number, user, phone, limiter, ctx)
        db.commit()  # end the read transaction: the provider is called outside any transaction
        # 1. Pick or create the attempt, under the order's locks.
        with atomic(db):
            lock_order(db, order.id)
            locked = db.scalar(select(Order).where(Order.id == order.id).with_for_update())
            assert locked is not None
            order = locked
            attempt = _latest_attempt(db, order.id, lock=True)
            if attempt is None:
                raise NotFound(PAYMENT_NOT_FOUND, code="payment_not_found")
            if attempt.status == "succeeded":
                raise Conflict(ALREADY_PAID, code="payment_already_succeeded")
            if order.status in CLOSED_ORDER_STATUSES:
                raise Conflict(NOT_PAYABLE, code="order_not_payable")
            provider_name = METHOD_PROVIDERS.get(attempt.method)
            if provider_name is None:
                raise Conflict(METHOD_UNAVAILABLE, code="payment_method_unavailable")
            provider = get_provider(provider_name)
            assert provider is not None
            if provider_name == "cod":
                if attempt.provider is None:
                    started = provider.initiate(_for_payment(order, attempt))
                    attempt.provider, attempt.provider_reference = "cod", started.reference
                    db.flush()  # before _status refreshes the row
                return _status(db, order, attempt, "Pay in cash when the order is delivered.")
            expires = reservation_expiry(db, order.id)
            if expires is None or expires <= database_now(db):
                raise Conflict(NOT_PAYABLE, code="order_not_payable")
            if attempt.status == "pending" and attempt.provider_reference:
                return _status(db, order, attempt)  # already started: same reference
            if attempt.status in ("failed", "cancelled"):
                attempt = PaymentAttempt(
                    order_id=order.id,
                    method=attempt.method,
                    amount=order.total,
                    status="created",
                    idempotency_key=f"initiate:{order.id}:{uuid.uuid4().hex}",
                )
                db.add(attempt)
                db.flush()
            # Claim the attempt for this request's provider call: provider set, no reference
            # yet. A concurrent request waits on the order's lock, then finds the claim and is
            # refused, so one attempt gets one provider call.
            stale_claim = False
            if attempt.provider is not None and attempt.provider_reference is None:
                if attempt.updated_at > database_now(db) - CLAIM_TIMEOUT:
                    raise Conflict(IN_PROGRESS, code="payment_initiation_in_progress")
                # Stale: the first call may still be running, or may have started a payment
                # whose reference was never saved. Repeat it only when the provider guarantees
                # that the same idempotency key cannot start a second payment.
                stale_claim = not provider.idempotent_initiation
                if not stale_claim:
                    logger.warning(
                        "Retrying a stale payment initiation claim with the same idempotency "
                        "key (attempt %s, order %s)",
                        attempt.id,
                        order.id,
                    )
            if not stale_claim:
                attempt.provider = provider_name
                attempt.updated_at = func.now()  # type: ignore[assignment]  # the claim time
                db.flush()
            attempt_id, snapshot = attempt.id, _for_payment(order, attempt)
        if stale_claim:
            _needs_recovery(
                db, order.id, attempt_id, "initiation_needs_recovery", STALE_CLAIM, user, ctx
            )
        # 2. The provider call, outside the database transaction.
        try:
            started = provider.initiate(snapshot)
        except ProviderNotConfigured:
            logger.error(
                "Payment initiation refused: the %s provider is not configured", provider_name
            )
            with atomic(db):  # release the claim: nothing was started
                lock_order(db, order.id)
                claimed = db.get(PaymentAttempt, attempt_id, with_for_update=True)
                if claimed is not None and claimed.provider_reference is None:
                    claimed.provider = None
            raise ServiceUnavailable(
                PROVIDER_UNAVAILABLE, code="payment_provider_unavailable"
            ) from None
        except ProviderOutcomeUnknown:
            logger.error(
                "The %s provider gave no answer for payment attempt %s (order %s)",
                provider_name,
                attempt_id,
                order.id,
            )
            _unknown_outcome(db, provider, order.id, attempt_id, user, ctx)
        except ProviderError:
            logger.warning("The %s provider refused to start a payment", provider_name)
            with atomic(db):
                lock_order(db, order.id)
                failed = db.get(PaymentAttempt, attempt_id, with_for_update=True)
                if failed is not None and failed.status == "created":
                    failed.status = "failed"
                    _audit(
                        db,
                        "payment.initiate",
                        order.id,
                        user,
                        ctx,
                        {"attempt_id": str(attempt_id), "outcome": "provider_error"},
                    )
            raise BadGateway() from None
        except Exception as exc:
            # An adapter bug or an unwrapped transport error: whether a payment started is
            # unknown, so it is handled as an unknown outcome, never as a failure. Only the
            # exception's type is logged: its message could carry provider data.
            logger.error(
                "The %s provider raised %s for payment attempt %s (order %s); outcome unknown",
                provider_name,
                type(exc).__name__,
                attempt_id,
                order.id,
            )
            _unknown_outcome(db, provider, order.id, attempt_id, user, ctx)
        # 3. Record the reference (a concurrent initiation may have recorded its own first).
        # A reference that arrives after the attempt left 'created' (the hold expired, or the
        # order was cancelled, while the provider call ran) is never dropped: it is kept on the
        # attempt when free, and recorded for reconciliation; no state is revived.
        late = False
        with atomic(db):
            lock_order(db, order.id)
            attempt = db.get(
                PaymentAttempt, attempt_id, with_for_update=True, populate_existing=True
            )
            assert attempt is not None
            if attempt.status == "created" and attempt.provider_reference is None:
                attempt.provider = provider_name
                attempt.provider_reference = started.reference
                attempt.status = started.status
                _audit(
                    db,
                    "payment.initiate",
                    order.id,
                    user,
                    ctx,
                    {
                        "attempt_id": str(attempt.id),
                        "provider": provider_name,
                        "method": attempt.method,
                    },
                )
            elif attempt.provider_reference == started.reference:
                # A concurrent retry with the same key recorded it first (and, if the attempt
                # had already left 'created', recorded it for reconciliation too).
                late = attempt.status in ("expired", "cancelled")
            else:
                _record_late_reference(db, attempt, provider_name, started.reference, user, ctx)
                late = True
            if attempt.provider_reference == started.reference:
                _link_early_events(db, attempt, provider_name, user, ctx)
        if late:
            raise Conflict(NEEDS_RECOVERY, code="payment_initiation_needs_recovery")
        return _status(db, order, attempt, started.instructions)

    # ---- switching method (frontend phase 4, 2026-10-27) ---------------------------------------
    @staticmethod
    def change_method(
        db: Session,
        order_number: str,
        user: User | None,
        phone: str | None,
        method: str,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
    ) -> PaymentStatusResponse:
        """Switch an unpaid order to another payment method. The current attempt is cancelled
        (failed and cancelled ones are kept as they are) and a new one starts as checkout would
        (mobile money 'created', cash on delivery 'pending'). The stock hold follows the new
        method from the order's creation (§7 Q11, Q13): refused when that time has passed.
        A mobile-money request that is out (pending) or being started may still be approved,
        so switching then is refused. The same method changes nothing."""
        order = _accessible_order(db, order_number, user, phone, limiter, ctx)
        db.commit()
        with atomic(db):
            lock_order(db, order.id)
            locked = db.scalar(select(Order).where(Order.id == order.id).with_for_update())
            assert locked is not None
            order = locked
            attempt = _latest_attempt(db, order.id, lock=True)
            if attempt is None:
                raise NotFound(PAYMENT_NOT_FOUND, code="payment_not_found")
            if attempt.status == "succeeded":
                raise Conflict(ALREADY_PAID, code="payment_already_succeeded")
            if order.status in CLOSED_ORDER_STATUSES:
                raise Conflict(NOT_PAYABLE, code="order_not_payable")
            if method == attempt.method:
                return _status(db, order, attempt)
            zone = db.get(DeliveryZone, order.delivery_zone_id) if order.delivery_zone_id else None
            if method not in available_methods(bool(zone and zone.cod_available)):
                raise field_error(("body", "payment_method"), METHOD_UNAVAILABLE)
            started = attempt.provider is not None and attempt.method in MOBILE_MONEY
            if attempt.status in ("created", "pending") and started:
                raise Conflict(SWITCH_IN_PROGRESS, code="payment_in_progress")
            expires = order.created_at + HOLDS[method]
            if expires <= database_now(db):
                raise Conflict(SWITCH_TOO_LATE, code="payment_method_change_too_late")
            try:
                change_hold_expiry(db, order.id, expires, actor=user, ctx=ctx)
            except HoldNotActive:
                raise Conflict(NOT_PAYABLE, code="order_not_payable") from None
            previous = attempt.method
            if attempt.status in ("created", "pending"):
                attempt.status = "cancelled"
            attempt = PaymentAttempt(
                order_id=order.id,
                method=method,
                amount=order.total,
                status="pending" if method == CASH_ON_DELIVERY else "created",
                idempotency_key=f"switch:{order.id}:{uuid.uuid4().hex}",
            )
            db.add(attempt)
            db.flush()
            _audit(
                db,
                "payment.method_change",
                order.id,
                user,
                ctx,
                {"attempt_id": str(attempt.id), "from": previous, "to": method},
            )
        logger.info("Order %s switched payment method to %s", order.order_number, method)
        return _status(db, order, attempt)

    # ---- webhooks ----------------------------------------------------------------------------
    @staticmethod
    def webhook(db: Session, provider_name: str, request: WebhookRequest) -> WebhookAck:
        provider = get_provider(provider_name) if provider_name != "cod" else None
        if provider is None:
            raise NotFound("Unknown payment provider.", code="provider_not_found")
        try:
            provider.verify_webhook(request)
        except ProviderNotConfigured:
            raise ServiceUnavailable(
                PROVIDER_UNAVAILABLE, code="payment_provider_unavailable"
            ) from None
        except InvalidWebhook as exc:
            logger.warning("Rejected a %s webhook: %s", provider_name, exc)
            raise InvalidSignature() from None
        try:
            event = provider.parse_event(request)
        except MalformedWebhook as exc:
            logger.warning("Malformed %s webhook (%s)", provider_name, exc)
            raise MalformedEvent() from None
        with atomic(db):
            now = database_now(db)
            event_id = db.scalar(
                insert(PaymentEvent)
                .values(
                    id=uuid.uuid4(),
                    provider=provider_name,
                    event_key=event.event_key,
                    payload_digest=hashlib.sha256(request.body).hexdigest(),
                    verification_status="verified",
                    processing_status="pending",
                    received_at=now,
                    payload_metadata=event.metadata,
                )
                .on_conflict_do_nothing(index_elements=["provider", "event_key"])
                .returning(PaymentEvent.id)
            )
            if event_id is None:
                return WebhookAck(status="duplicate")
            outcome, summary, attempt_id, order_id = _apply(db, provider_name, event)
            stored = db.get(PaymentEvent, event_id)
            assert stored is not None
            stored.attempt_id = attempt_id
            stored.processing_status = outcome
            stored.processed_at = func.now()  # type: ignore[assignment]
            stored.result_summary = summary
            if order_id is not None:
                _audit(
                    db,
                    "payment.event",
                    order_id,
                    None,
                    None,
                    {
                        "provider": provider_name,
                        "event_status": event.status,
                        "outcome": outcome,
                        "summary": summary,
                        "attempt_id": str(attempt_id) if attempt_id else None,
                    },
                )
        logger.info("Payment event %s from %s: %s", event.event_key, provider_name, outcome)
        return WebhookAck(status=outcome)  # type: ignore[arg-type]

    # ---- staff -------------------------------------------------------------------------------
    @staticmethod
    def confirm_cod(
        db: Session, actor: User, attempt_id: uuid.UUID, ctx: RequestContext
    ) -> StaffPaymentItem:
        """payments:manage: record the cash of a delivered COD order as collected. Delivery
        already does this automatically (§7 Q14); a confirmation of a succeeded payment is a
        no-op, and nothing can be confirmed before delivery (TC-12)."""
        attempt = db.get(PaymentAttempt, attempt_id)
        if attempt is None:
            raise NotFound(PAYMENT_NOT_FOUND, code="payment_not_found")
        with atomic(db):
            lock_order(db, attempt.order_id)
            order = db.scalar(select(Order).where(Order.id == attempt.order_id).with_for_update())
            attempt = db.get(
                PaymentAttempt, attempt_id, with_for_update=True, populate_existing=True
            )
            assert order is not None and attempt is not None
            if attempt.method != "cash_on_delivery":
                raise Conflict(NOT_COD, code="payment_not_cod")
            if attempt.status != "succeeded":
                if order.status != "delivered" or attempt.status != "pending":
                    raise Conflict(NOT_DELIVERED, code="order_not_delivered")
                attempt.status = "succeeded"
                attempt.succeeded_at = func.now()  # type: ignore[assignment]
                _audit(
                    db, "payment.cod_confirm", order.id, actor, ctx, {"attempt_id": str(attempt.id)}
                )
                issue_for_order(db, order, payment_method=attempt.method, actor=actor, ctx=ctx)
                record_order_event(db, order, "payment_succeeded")
        return _staff_items(db, [attempt])[0]

    @staticmethod
    def staff_list(
        db: Session,
        *,
        status: str | None,
        method: str | None,
        needs_reconciliation: bool | None,
        page: int,
        size: int,
    ) -> StaffPaymentPage:
        conditions = []
        if status is not None:
            conditions.append(PaymentAttempt.status == status)
        if method is not None:
            conditions.append(PaymentAttempt.method == method)
        flagged = exists().where(
            PaymentEvent.attempt_id == PaymentAttempt.id,
            PaymentEvent.processing_status == "needs_reconciliation",
        )
        if needs_reconciliation is not None:
            conditions.append(flagged if needs_reconciliation else ~flagged)
        total, amount_total = db.execute(
            select(
                func.count(PaymentAttempt.id), func.coalesce(func.sum(PaymentAttempt.amount), 0)
            ).where(*conditions)
        ).one()
        attempts = list(
            db.scalars(
                select(PaymentAttempt)
                .where(*conditions)
                .order_by(PaymentAttempt.created_at.desc(), PaymentAttempt.id)
                .offset(page_offset(page, size))
                .limit(size)
            )
        )
        return StaffPaymentPage(
            items=_staff_items(db, attempts),
            total=total,
            page=page,
            size=size,
            amount_total=int(amount_total),
        )

    @staticmethod
    def staff_events(
        db: Session, *, processing_status: str | None, page: int, size: int
    ) -> Page[StaffPaymentEventItem]:
        conditions = []
        if processing_status is not None:
            conditions.append(PaymentEvent.processing_status == processing_status)
        total = db.scalar(select(func.count(PaymentEvent.id)).where(*conditions)) or 0
        events = db.scalars(
            select(PaymentEvent)
            .where(*conditions)
            .order_by(PaymentEvent.received_at.desc(), PaymentEvent.id)
            .offset(page_offset(page, size))
            .limit(size)
        )
        return Page(
            items=[
                StaffPaymentEventItem(
                    id=e.id,
                    attempt_id=e.attempt_id,
                    provider=e.provider,
                    event_key=e.event_key,
                    verification_status=e.verification_status,
                    processing_status=e.processing_status,  # type: ignore[arg-type]
                    received_at=e.received_at,
                    processed_at=e.processed_at,
                    result_summary=e.result_summary,
                    payload_metadata=e.payload_metadata,
                )
                for e in events
            ],
            total=total,
            page=page,
            size=size,
        )


def _for_payment(order: Order, attempt: PaymentAttempt) -> OrderForPayment:
    return OrderForPayment(
        order_id=str(order.id),
        order_number=order.order_number,
        amount=order.total,
        currency_code=order.currency_code,
        method=attempt.method,
        phone=order.recipient_phone,
        idempotency_key=attempt.idempotency_key,
    )


def _staff_items(db: Session, attempts: list[PaymentAttempt]) -> list[StaffPaymentItem]:
    if not attempts:
        return []
    ids = [a.id for a in attempts]
    numbers = dict(
        db.execute(
            select(Order.id, Order.order_number).where(Order.id.in_({a.order_id for a in attempts}))
        ).all()
    )
    flagged = set(
        db.scalars(
            select(PaymentEvent.attempt_id).where(
                PaymentEvent.attempt_id.in_(ids),
                PaymentEvent.processing_status == "needs_reconciliation",
            )
        )
    )
    for attempt in attempts:
        db.refresh(attempt)
    return [
        StaffPaymentItem(
            id=a.id,
            order_id=a.order_id,
            order_number=numbers[a.order_id],
            method=a.method,  # type: ignore[arg-type]
            provider=a.provider,
            provider_reference=a.provider_reference,
            status=a.status,  # type: ignore[arg-type]
            amount=a.amount,
            currency_code=a.currency_code,
            created_at=a.created_at,
            succeeded_at=a.succeeded_at,
            needs_reconciliation=a.id in flagged,
        )
        for a in attempts
    ]


def _apply(
    db: Session, provider_name: str, event: ProviderEvent
) -> tuple[str, str, uuid.UUID | None, uuid.UUID | None]:
    """Apply a new, verified event; returns (processing status, summary, attempt id, order id).
    Runs inside the webhook's transaction; takes the order's locks in the common order."""
    found = db.scalar(
        select(PaymentAttempt).where(
            PaymentAttempt.provider == provider_name,
            PaymentAttempt.provider_reference == event.reference,
        )
    )
    if found is None:
        return "needs_reconciliation", "unknown reference", None, None
    lock_order(db, found.order_id)
    order = db.scalar(select(Order).where(Order.id == found.order_id).with_for_update())
    attempt = db.get(PaymentAttempt, found.id, with_for_update=True, populate_existing=True)
    assert order is not None and attempt is not None
    if event.status == "succeeded":
        if attempt.status == "succeeded":
            return "processed", "already succeeded", attempt.id, order.id
        if (
            event.currency_code != attempt.currency_code
            or event.amount != attempt.amount
            or attempt.amount != order.total
        ):
            logger.error(
                "Payment success with a mismatched amount or currency (order %s)", order.id
            )
            return "needs_reconciliation", "amount or currency mismatch", attempt.id, order.id
        result = commit_order_reservations(db, order.id)
        if result.outcome in (TransitionOutcome.COMMITTED, TransitionOutcome.ALREADY_COMMITTED):
            attempt.status = "succeeded"
            attempt.succeeded_at = func.now()  # type: ignore[assignment]
            # §7 Q19: the invoice is issued with the recorded success, in this transaction.
            issue_for_order(db, order, payment_method=attempt.method)
            record_order_event(db, order, "payment_succeeded")
            return "processed", "succeeded; stock committed", attempt.id, order.id
        # Late payment (ADR-002): the hold lapsed or was released; nothing is committed or
        # re-reserved, the order is not marked paid, and finance reconciles the money.
        release_for_order(db, order.id, reason="expired")
        cancel_unpaid_order(db, order.id)
        logger.error("Late payment success for order %s: needs reconciliation", order.id)
        return (
            "needs_reconciliation",
            "late success: the stock hold had lapsed",
            attempt.id,
            order.id,
        )
    if event.status in ("failed", "cancelled"):
        if attempt.status == "succeeded":
            return "processed", f"{event.status} ignored: already succeeded", attempt.id, order.id
        if attempt.status in ("created", "pending"):
            attempt.status = event.status
            return "processed", event.status, attempt.id, order.id
        return (
            "processed",
            f"{event.status} ignored: attempt {attempt.status}",
            attempt.id,
            order.id,
        )
    if attempt.status == "created":
        attempt.status = "pending"
    return "processed", "pending", attempt.id, order.id
