"""Business quote requests (module 19, approved 2026-10-29; Contact page, PR-01).

Anyone can send a request from the Contact page. Every attempt counts against a fixed-window
limit per phone number (its keyed pseudonym, never the number) and per client network
(QUOTE_REQUEST_* settings); beyond it the request answers 429, and an unreachable limit store
refuses (503) so the form cannot be used to flood the table. The request gets a random reference
(Q-YYMMDD-XXXXXX, Kigali date) to quote when calling. Nothing is sent to the buyer or to staff
yet (notifications are module 17).

Staff with 'quotes:manage' (administrator, sales) list requests, newest first, and move them
between new, contacted and closed. handled_at and handled_by_user_id record who last moved a
request out of 'new' (cleared when it goes back to new). Each change is audited as
'quote.status_change'.
"""

import logging
import secrets
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFound, ServiceUnavailable, TooManyRequests, field_error
from app.core.kigali_time import KIGALI
from app.core.rate_limit import LoginRateLimiter, RateLimitStoreUnavailable, client_network
from app.core.request_context import RequestContext
from app.core.security import pseudonymize_identifier
from app.db.transaction import atomic
from app.models.common import utc_now
from app.models.content import QuoteRequest
from app.models.identity import User
from app.schemas.pagination import page_offset
from app.schemas.quotes import QuoteRequestCreate
from app.services.audit_service import AuditService
from app.services.notification_service import record_email_event

logger = logging.getLogger("app.quotes")

REFERENCE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O, 1/I: read aloud by phone
REFERENCE_SUFFIX = 6
NEEDED_BY_MAX_DAYS = 366
LIMITED = "Too many quote requests; try again later or contact us on WhatsApp."
UNAVAILABLE = "Quote requests cannot be sent right now; try again shortly."
NOT_FOUND = "Quote request not found."
NEEDED_BY_RULE = "Choose a date from today up to one year ahead."


def _new_reference(db: Session, now: datetime) -> str:
    for _ in range(10):
        suffix = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(REFERENCE_SUFFIX))
        reference = f"Q-{now.astimezone(KIGALI):%y%m%d}-{suffix}"
        if db.scalar(select(QuoteRequest.id).where(QuoteRequest.reference == reference)) is None:
            return reference
    raise RuntimeError("could not allocate a quote reference")  # pragma: no cover


def _check_needed_by(value: date | None, now: datetime) -> None:
    if value is None:
        return
    today = now.astimezone(KIGALI).date()
    if not today <= value <= today + timedelta(days=NEEDED_BY_MAX_DAYS):
        raise field_error(("body", "needed_by"), NEEDED_BY_RULE)


class QuoteService:
    @staticmethod
    def create(
        db: Session, req: QuoteRequestCreate, limiter: LoginRateLimiter, ctx: RequestContext
    ) -> QuoteRequest:
        now = utc_now()
        _check_needed_by(req.needed_by, now)
        key = get_settings().audit_hmac_key.get_secret_value()
        phone_ref = pseudonymize_identifier(req.phone, key)
        network = client_network(ctx.ip_address)
        try:
            decision = limiter.check(phone_ref, network)
            if decision.allowed:
                limiter.record_failure(phone_ref, network)  # every attempt counts
        except RateLimitStoreUnavailable:
            logger.error("Quote request refused: the rate-limit store is unavailable")
            raise ServiceUnavailable(UNAVAILABLE, code="quote_unavailable") from None
        if not decision.allowed:
            logger.warning("Quote request limit reached (%s)", decision.scope)
            raise TooManyRequests(
                LIMITED, code="rate_limited", headers={"Retry-After": str(decision.retry_after)}
            )
        with atomic(db):
            quote = QuoteRequest(
                reference=_new_reference(db, now),
                company=req.company,
                contact_name=req.contact_name,
                phone=req.phone,
                email=req.email,
                lines=[line.model_dump() for line in req.lines],
                delivery_location=req.delivery_location,
                needed_by=req.needed_by,
                message=req.message,
                locale=req.locale,
                status="new",
            )
            db.add(quote)
            db.flush()
            record_email_event(db, "quote_received", quote.id, quote.email)
        return quote

    @staticmethod
    def staff_page(
        db: Session, status: str | None, page: int, size: int
    ) -> tuple[list[QuoteRequest], int]:
        filters = [QuoteRequest.status == status] if status else []
        total = db.scalar(select(func.count(QuoteRequest.id)).where(*filters)) or 0
        rows = db.scalars(
            select(QuoteRequest)
            .where(*filters)
            .order_by(QuoteRequest.created_at.desc(), QuoteRequest.id.desc())
            .offset(page_offset(page, size))
            .limit(size)
        )
        return list(rows), total

    @staticmethod
    def set_status(
        db: Session, actor: User, quote_id: uuid.UUID, status: str, ctx: RequestContext
    ) -> QuoteRequest:
        with atomic(db):
            quote = db.scalar(
                select(QuoteRequest).where(QuoteRequest.id == quote_id).with_for_update()
            )
            if quote is None:
                raise NotFound(NOT_FOUND, code="quote_request_not_found")
            if quote.status == status:
                return quote  # nothing changed: not audited
            before = quote.status
            quote.status = status
            if status == "new":
                quote.handled_at = None
                quote.handled_by_user_id = None
            else:
                quote.handled_at = utc_now()
                quote.handled_by_user_id = actor.id
            db.flush()
            AuditService.log_event(
                db=db,
                action="quote.status_change",
                status="success",
                actor=actor,
                entity_type="quote_request",
                entity_id=quote.id,
                context=ctx,
                details={"from": before, "to": status, "reference": quote.reference},
            )
        db.refresh(quote)
        return quote
