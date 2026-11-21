"""Customer support messages (approved 2026-11-11).

Anyone can ask a question from the Contact page wizard with a topic, a name, a phone or an
email, a subject and an optional order number. Each question gets a random reference
(M-YYMMDD-XXXXXX, Kigali date). A signed-in customer's question is linked to their account, so
they can follow the conversation and reply under My messages. Every sender also gets a private
link (app.services.support_access), shown after sending and put in the reply email, that opens
the conversation without an account; guests read and answer support there.

Every new question and every customer reply counts against a fixed-window limit per sender (the
keyed pseudonym of the account, phone or email, never the value) and per client network
(SUPPORT_MESSAGE_* settings); beyond it the request answers 429, and an unreachable limit store
refuses (503).

Staff with 'support:read' (administrator) read the conversations; those with
'support:reply' (administrator) reply and close them. A staff reply sets the status to
'answered' and is emailed to the sender's address (outbox event 'support_reply'), a customer
reply sets it to 'open', and closing sets 'closed'. Replies and status changes are audited as
'support.reply' and 'support.status_change'; message text is never put in the audit trail.
"""

import logging
import secrets
import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import NotFound, ServiceUnavailable, TooManyRequests
from app.core.kigali_time import KIGALI
from app.core.rate_limit import LoginRateLimiter, RateLimitStoreUnavailable, client_network
from app.core.request_context import RequestContext
from app.core.roles import Role, effective_roles
from app.core.security import pseudonymize_identifier
from app.db.transaction import atomic
from app.models.common import utc_now
from app.models.identity import User
from app.models.support import SupportMessage, SupportThread
from app.schemas.pagination import page_offset
from app.schemas.support import SupportMessageCreate
from app.services.audit_service import AuditService
from app.services.notification_service import record_email_event
from app.services.support_access import key_matches

logger = logging.getLogger("app.support")

REFERENCE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O, 1/I: read aloud by phone
REFERENCE_SUFFIX = 6
PREVIEW_LENGTH = 160
LIMITED = "Too many messages; try again later or contact us on WhatsApp."
UNAVAILABLE = "Messages cannot be sent right now; try again shortly."
NOT_FOUND = "Conversation not found."


def is_customer(user: User | None) -> bool:
    return user is not None and not user.is_staff and effective_roles(user) == {Role.CUSTOMER.value}


def _new_reference(db: Session, now: datetime) -> str:
    for _ in range(10):
        suffix = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(REFERENCE_SUFFIX))
        reference = f"M-{now.astimezone(KIGALI):%y%m%d}-{suffix}"
        if db.scalar(select(SupportThread.id).where(SupportThread.reference == reference)) is None:
            return reference
    raise RuntimeError("could not allocate a support reference")  # pragma: no cover


def _count_attempt(limiter: LoginRateLimiter, sender: str, ctx: RequestContext) -> None:
    key = get_settings().audit_hmac_key.get_secret_value()
    sender_ref = pseudonymize_identifier(sender, key)
    network = client_network(ctx.ip_address)
    try:
        decision = limiter.check(sender_ref, network)
        if decision.allowed:
            limiter.record_failure(sender_ref, network)  # every message counts
    except RateLimitStoreUnavailable:
        logger.error("Support message refused: the rate-limit store is unavailable")
        raise ServiceUnavailable(UNAVAILABLE, code="support_unavailable") from None
    if not decision.allowed:
        logger.warning("Support message limit reached (%s)", decision.scope)
        raise TooManyRequests(
            LIMITED, code="rate_limited", headers={"Retry-After": str(decision.retry_after)}
        )


def _with_messages():  # noqa: ANN202 - a loader option
    return selectinload(SupportThread.messages)


def _locked(db: Session, *conditions: ColumnElement[bool]) -> SupportThread:
    thread = db.scalar(select(SupportThread).where(*conditions).with_for_update())
    if thread is None:
        raise NotFound(NOT_FOUND, code="support_thread_not_found")
    return thread


def _add_message(
    db: Session, thread: SupportThread, author: str, body: str, staff: User | None = None
) -> SupportMessage:
    now = utc_now()
    message = SupportMessage(
        thread_id=thread.id,
        author=author,
        staff_user_id=staff.id if staff else None,
        body=body,
        created_at=now,
    )
    db.add(message)
    thread.last_message_at = now
    return message


def summary_fields(thread: SupportThread) -> dict[str, object]:
    """The list fields computed from a thread's (loaded) messages."""
    last = thread.messages[-1] if thread.messages else None
    preview = " ".join((last.body if last else "").split())
    if len(preview) > PREVIEW_LENGTH:
        preview = preview[: PREVIEW_LENGTH - 1].rstrip() + "…"
    return {
        "message_count": len(thread.messages),
        "last_author": last.author if last else "customer",
        "last_preview": preview,
    }


class SupportService:
    # ---- customers and guests ---------------------------------------------------------------
    @staticmethod
    def create(
        db: Session,
        req: SupportMessageCreate,
        user: User | None,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
    ) -> SupportThread:
        customer = user if is_customer(user) else None
        sender = f"user:{customer.id}" if customer else (req.phone or req.email or "")
        _count_attempt(limiter, sender, ctx)
        now = utc_now()
        with atomic(db):
            thread = SupportThread(
                reference=_new_reference(db, now),
                customer_user_id=customer.id if customer else None,
                name=req.name,
                topic=req.topic,
                phone=req.phone,
                email=req.email,
                subject=req.subject,
                order_number=req.order_number,
                locale=req.locale,
                status="open",
                last_message_at=now,
            )
            db.add(thread)
            db.flush()
            _add_message(db, thread, "customer", req.body)
            db.flush()
        return thread

    @staticmethod
    def customer_page(
        db: Session, user: User, page: int, size: int
    ) -> tuple[list[SupportThread], int]:
        mine = SupportThread.customer_user_id == user.id
        total = db.scalar(select(func.count(SupportThread.id)).where(mine)) or 0
        rows = db.scalars(
            select(SupportThread)
            .where(mine)
            .options(_with_messages())
            .order_by(SupportThread.last_message_at.desc(), SupportThread.id.desc())
            .offset(page_offset(page, size))
            .limit(size)
        )
        return list(rows), total

    @staticmethod
    def customer_thread(db: Session, user: User, reference: str) -> SupportThread:
        thread = db.scalar(
            select(SupportThread)
            .where(
                SupportThread.reference == reference.strip().upper(),
                SupportThread.customer_user_id == user.id,
            )
            .options(_with_messages())
        )
        if thread is None:  # someone else's conversation answers the same
            raise NotFound(NOT_FOUND, code="support_thread_not_found")
        return thread

    @staticmethod
    def customer_reply(
        db: Session,
        user: User,
        reference: str,
        body: str,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
    ) -> SupportThread:
        SupportService.customer_thread(db, user, reference)  # 404 before counting
        _count_attempt(limiter, f"user:{user.id}", ctx)
        with atomic(db):
            thread = _locked(
                db,
                SupportThread.reference == reference.strip().upper(),
                SupportThread.customer_user_id == user.id,
            )
            _add_message(db, thread, "customer", body)
            thread.status = "open"
            db.flush()
        db.expire_all()
        return SupportService.customer_thread(db, user, reference)

    @staticmethod
    def guest_thread(db: Session, reference: str, key: str) -> SupportThread:
        """The conversation behind a private link; a wrong reference or key answers the same."""
        thread = db.scalar(
            select(SupportThread)
            .where(SupportThread.reference == reference.strip().upper())
            .options(_with_messages())
        )
        if thread is None or not key_matches(thread.id, key):
            raise NotFound(NOT_FOUND, code="support_thread_not_found")
        return thread

    @staticmethod
    def guest_reply(
        db: Session,
        reference: str,
        key: str,
        body: str,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
    ) -> SupportThread:
        thread_id = SupportService.guest_thread(db, reference, key).id  # 404 before counting
        _count_attempt(limiter, f"thread:{thread_id}", ctx)
        with atomic(db):
            thread = _locked(db, SupportThread.id == thread_id)
            _add_message(db, thread, "customer", body)
            thread.status = "open"
            db.flush()
        db.expire_all()
        return SupportService.guest_thread(db, reference, key)

    # ---- staff ------------------------------------------------------------------------------
    @staticmethod
    def staff_page(
        db: Session, status: str | None, q: str | None, page: int, size: int
    ) -> tuple[list[SupportThread], int]:
        filters: list[ColumnElement[bool]] = []
        if status:
            filters.append(SupportThread.status == status)
        if q and q.strip():
            text = q.strip()
            filters.append(
                or_(
                    SupportThread.reference.contains(text.upper(), autoescape=True),
                    SupportThread.name.icontains(text, autoescape=True),
                    SupportThread.subject.icontains(text, autoescape=True),
                    SupportThread.email.icontains(text, autoescape=True),
                    SupportThread.phone.contains(text, autoescape=True),
                    SupportThread.order_number.contains(text.upper(), autoescape=True),
                )
            )
        total = db.scalar(select(func.count(SupportThread.id)).where(*filters)) or 0
        rows = db.scalars(
            select(SupportThread)
            .where(*filters)
            .options(_with_messages())
            .order_by(SupportThread.last_message_at.desc(), SupportThread.id.desc())
            .offset(page_offset(page, size))
            .limit(size)
        )
        return list(rows), total

    @staticmethod
    def staff_thread(db: Session, thread_id: uuid.UUID) -> SupportThread:
        thread = db.scalar(
            select(SupportThread).where(SupportThread.id == thread_id).options(_with_messages())
        )
        if thread is None:
            raise NotFound(NOT_FOUND, code="support_thread_not_found")
        return thread

    @staticmethod
    def staff_names(db: Session, thread: SupportThread) -> dict[uuid.UUID, str]:
        ids = {m.staff_user_id for m in thread.messages if m.staff_user_id is not None}
        if not ids:
            return {}
        rows = db.execute(select(User.id, User.full_name, User.email).where(User.id.in_(ids)))
        return {uid: (name or email or "Staff") for uid, name, email in rows}

    @staticmethod
    def staff_reply(
        db: Session, actor: User, thread_id: uuid.UUID, body: str, ctx: RequestContext
    ) -> SupportThread:
        with atomic(db):
            thread = _locked(db, SupportThread.id == thread_id)
            before = thread.status
            message = _add_message(db, thread, "staff", body, actor)
            thread.status = "answered"
            db.flush()
            record_email_event(db, "support_reply", message.id, thread.email)
            AuditService.log_event(
                db=db,
                action="support.reply",
                status="success",
                actor=actor,
                entity_type="support_thread",
                entity_id=thread.id,
                context=ctx,
                details={"reference": thread.reference, "from": before, "to": "answered"},
            )
        db.expire_all()
        return SupportService.staff_thread(db, thread_id)

    @staticmethod
    def set_status(
        db: Session, actor: User, thread_id: uuid.UUID, status: str, ctx: RequestContext
    ) -> SupportThread:
        with atomic(db):
            thread = _locked(db, SupportThread.id == thread_id)
            if thread.status != status:
                before = thread.status
                thread.status = status
                db.flush()
                AuditService.log_event(
                    db=db,
                    action="support.status_change",
                    status="success",
                    actor=actor,
                    entity_type="support_thread",
                    entity_id=thread.id,
                    context=ctx,
                    details={"from": before, "to": status, "reference": thread.reference},
                )
        db.expire_all()
        return SupportService.staff_thread(db, thread_id)
