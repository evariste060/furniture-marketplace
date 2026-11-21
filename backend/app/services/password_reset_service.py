"""Password reset by one-time code (module 2; approved plan Q1/Q2, owner decisions 2026-10-23).

Rules:
- Only active customer accounts can reset. Staff passwords stay administrator-managed (ADR-006).
- A 6-digit code is sent to the identifier given (email -> email, phone -> SMS). It is valid for
  15 minutes and 5 attempts; requesting a new code invalidates older ones.
- Every reply is the same whether or not an eligible account exists (no account enumeration).
  Every wrong, expired, used or unknown code gives the same 422.
- Code requests and failed code entries each use the login rate-limit policy on their own
  counters (`reset`, `reset_code`), and fail closed (503) if the counter store is down.
- A successful reset sets the new password, consumes the code and revokes every session, in one
  transaction with its audit record.
- Without a configured message sender both endpoints answer 503 (no silent drop of codes).
  Only a provider that reaches the person counts (module 17): the console in development, or
  smtp in development and staging. The mock order-notification provider does not, and no
  production SMS or email provider exists until ADR-005 is decided (§7 Q22). A code request on
  a channel the provider cannot deliver (a phone number with smtp) answers 503 too, before any
  account is looked up, so it reveals nothing about accounts.
- The code is sent after the commit, once, through the notification provider abstraction. A
  delivery failure is logged as its error type only (never the code, the recipient or provider
  text) and leaves the issued code valid. Codes are not written to notification_logs and are
  never retried: a retry would need the code stored; the customer can request a new one.
"""

import hmac
import logging
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ServiceUnavailable, TooManyRequests, ValidationFailed
from app.core.rate_limit import LoginRateLimiter, RateLimitStoreUnavailable
from app.core.request_context import RequestContext
from app.core.security import generate_reset_code, hash_password, hash_reset_code
from app.db.transaction import atomic
from app.integrations.notifications import (
    Channel,
    NotificationProvider,
    OutboundMessage,
    email_allowed,
)
from app.models.identity import User
from app.repositories.password_reset_repository import PasswordResetRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import ResetPasswordRequest
from app.services import email_templates
from app.services.audit_service import AuditService, identifier_ref

CODE_LIFETIME = timedelta(minutes=15)
MAX_ATTEMPTS = 5

UNAVAILABLE_DETAIL = "Password reset is temporarily unavailable. Please try again later."
RATE_LIMITED_DETAIL = "Too many password reset attempts. Try again later."
INVALID_CODE_DETAIL = "The reset code is invalid or has expired."
REQUESTED_MESSAGE = (
    "If an account matches this email or phone number, a reset code has been sent. "
    "It expires in 15 minutes."
)
RESET_MESSAGE = "Your password has been reset. Please log in with your new password."
RESET_SUBJECT = "Your password reset code"
logger = logging.getLogger("app.password_reset")


def deliver_reset_code(
    sender: NotificationProvider, channel: Channel, recipient: str, code: str, key: str
) -> None:
    """Background task: send the code once. Never raises; logs no code, recipient or provider
    text, so a failure cannot leak the code or invalidate the request. Email is HTML with a
    plain-text alternative; EMAIL_ALLOWED_RECIPIENTS applies as to every email."""
    if channel == "email" and not email_allowed(recipient):
        logger.info("Password reset code not sent: recipient not allowed (%s)", sender.name)
        return
    rendered = email_templates.password_reset(code)
    message = OutboundMessage(
        channel=channel,
        recipient=recipient,
        subject=RESET_SUBJECT,
        text=rendered.sms if channel == "sms" else rendered.text,
        idempotency_key=f"password-reset:{key}",
        html=rendered.html if channel == "email" else None,
    )
    try:
        sender.send(message)
    except Exception as exc:
        logger.error(
            "Password reset code not delivered (%s via %s): %s",
            channel,
            sender.name,
            type(exc).__name__,
        )


def _unavailable() -> ServiceUnavailable:
    return ServiceUnavailable(UNAVAILABLE_DETAIL, code="password_reset_unavailable")


def _code_hash(user: User, code: str) -> str:
    key = get_settings().audit_hmac_key.get_secret_value()
    return hash_reset_code(str(user.id), code, key)


def _eligible(user: User | None) -> bool:
    return bool(user and user.is_active and not user.is_staff and user.password_hash)


def _ineligible_reason(user: User | None) -> str:
    if user is None:
        return "unknown_identifier"
    if user.is_staff:
        return "staff_account"
    return "account_inactive"


class PasswordResetService:
    @staticmethod
    def _check_limit(
        limiter: LoginRateLimiter, ref: str, ctx: RequestContext, db: Session, action: str
    ):
        try:
            decision = limiter.check(ref, ctx.ip_address)
        except RateLimitStoreUnavailable:
            raise _unavailable() from None
        if not decision.allowed:
            AuditService.record_standalone(
                db,
                action=action,
                status="rate_limited",
                entity_type="login_identifier",
                entity_id=ref,
                context=ctx,
                details={"scope": decision.scope},
            )
            raise TooManyRequests(
                RATE_LIMITED_DETAIL,
                code="rate_limited",
                headers={"Retry-After": str(decision.retry_after)},
            )

    @staticmethod
    def _count(limiter: LoginRateLimiter, ref: str, ctx: RequestContext) -> None:
        try:
            limiter.record_failure(ref, ctx.ip_address)
        except RateLimitStoreUnavailable:
            raise _unavailable() from None

    @staticmethod
    def request_code(
        db: Session,
        identifier: str,
        ctx: RequestContext,
        limiter: LoginRateLimiter,
        sender: NotificationProvider | None,
        background: BackgroundTasks,
    ) -> str:
        """Issue and send a code when an eligible account matches. Same reply either way."""
        channel: Channel = "email" if "@" in identifier else "sms"
        if sender is None or channel not in sender.channels:
            raise _unavailable()
        ref = identifier_ref(identifier)
        PasswordResetService._check_limit(limiter, ref, ctx, db, "auth.password_reset_request")
        PasswordResetService._count(limiter, ref, ctx)

        user = UserRepository.get_by_identifier(db, identifier)
        if not _eligible(user):
            AuditService.record_standalone(
                db,
                action="auth.password_reset_request",
                status="ignored",
                entity_type="login_identifier",
                entity_id=ref,
                context=ctx,
                details={"reason": _ineligible_reason(user)},
            )
            return REQUESTED_MESSAGE

        assert user is not None
        code = generate_reset_code()
        now = datetime.now(UTC)
        with atomic(db):
            PasswordResetRepository.supersede_open_codes(db, user.id, now)
            row = PasswordResetRepository.create(
                db, user.id, _code_hash(user, code), channel, now + CODE_LIFETIME
            )
            AuditService.log_event(
                db,
                action="auth.password_reset_request",
                status="success",
                actor=user,
                entity_type="user",
                entity_id=user.id,
                context=ctx,
                details={"channel": channel},
            )
        # Sent after the commit and after the response, so the reply time does not reveal
        # whether an account matched.
        background.add_task(deliver_reset_code, sender, channel, identifier, code, str(row.id))
        return REQUESTED_MESSAGE

    @staticmethod
    def reset_password(
        db: Session,
        req: ResetPasswordRequest,
        ctx: RequestContext,
        limiter: LoginRateLimiter,
        sender: NotificationProvider | None,
    ) -> str:
        if sender is None:
            raise _unavailable()
        ref = identifier_ref(req.identifier)
        PasswordResetService._check_limit(limiter, ref, ctx, db, "auth.password_reset")

        user = UserRepository.get_by_identifier(db, req.identifier)
        now = datetime.now(UTC)
        with atomic(db):
            row = None
            if _eligible(user):
                assert user is not None
                UserRepository.lock_by_id(db, user.id)
                row = PasswordResetRepository.latest_open(db, user.id, for_update=True)
            valid = bool(
                user is not None
                and row is not None
                and row.expires_at > now
                and row.attempts < MAX_ATTEMPTS
                and hmac.compare_digest(row.code_hash, _code_hash(user, req.code))
            )
            if not valid:
                if row is not None and row.expires_at > now:
                    row.attempts += 1
                    if row.attempts >= MAX_ATTEMPTS:
                        row.consumed_at = now  # used up: never valid again
                AuditService.log_event(
                    db,
                    action="auth.password_reset",
                    status="failure",
                    entity_type="login_identifier",
                    entity_id=ref,
                    context=ctx,
                    details={"reason": "invalid_code"},
                )
            else:
                assert user is not None and row is not None
                user.password_hash = hash_password(req.new_password)
                row.consumed_at = now
                revoked = SessionRepository.revoke_all_user_sessions(db, user.id)
                AuditService.log_event(
                    db,
                    action="auth.password_reset",
                    status="success",
                    actor=user,
                    entity_type="user",
                    entity_id=user.id,
                    context=ctx,
                    details={"sessions_revoked": revoked},
                )
        if not valid:
            PasswordResetService._count(limiter, ref, ctx)
            raise ValidationFailed(INVALID_CODE_DETAIL, code="reset_code_invalid")
        try:
            limiter.record_success(ref)
        except RateLimitStoreUnavailable:
            pass  # the reset succeeded; the counter simply expires with its window
        return RESET_MESSAGE
