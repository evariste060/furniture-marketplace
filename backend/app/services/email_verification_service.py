"""Email verification of new customer accounts (ADR-006 amendment 2026-11-12).

Rules:
- A customer who registers with an email address and a password starts unverified
  (users.email_verified_at NULL) and gets no session. A link with a 256-bit token goes to the
  address; only the token's SHA-256 is stored, with its expiry (EMAIL_VERIFICATION_TTL_HOURS,
  24 by default) and the address it verifies. Phone-only registration is unchanged.
- Password login refuses an unverified customer (403 email_not_verified), only after the
  password was checked, so the answer reveals nothing to someone without the password. Staff and
  accounts without an email are never asked to verify; accounts that existed before the feature
  were marked verified by the migration; Continue with Google creates verified customers (the
  ID token's email_verified claim is required).
- POST /auth/email/verify uses a token once: the row is locked, checked (known, not revoked, not
  used, not expired, still the account's address) and consumed together with marking the account
  verified and revoking its other open tokens, in one transaction. A concurrent use of the same
  token waits for the lock and then finds it used. Failed attempts count per client network.
- POST /auth/email/verification/resend gives the same 202 whether the address belongs to an
  unverified customer, a verified one, staff, nobody, or is still in its cooldown. Every request
  counts against the resend limits per address and per IP. A new token revokes the older ones.
- Without a mailer that reaches people (see app.integrations.notifications.verification),
  registration with an email and resend answer 503 email_verification_unavailable before any
  account is created or looked up.
- The link is sent after the commit, once, through the notification provider abstraction. A
  delivery failure is logged as its error type only (never the token, link, recipient or provider
  text); the account stays unverified and the customer can ask for a new link. Tokens are never
  written to notification_logs, logs or audit records.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ServiceUnavailable, TooManyRequests, ValidationFailed
from app.core.rate_limit import LoginRateLimiter, RateLimitStoreUnavailable, client_network
from app.core.request_context import RequestContext
from app.core.security import generate_verification_token, hash_verification_token
from app.db.transaction import atomic
from app.integrations.notifications import OutboundMessage, email_allowed
from app.integrations.notifications.verification import VerificationMailer
from app.models.identity import User
from app.repositories.email_verification_repository import EmailVerificationRepository
from app.repositories.user_repository import UserRepository
from app.services import email_templates
from app.services.audit_service import AuditService, identifier_ref
from app.services.notification_service import record_email_event

UNAVAILABLE_DETAIL = "Email verification is temporarily unavailable. Please try again later."
LIMIT_STORE_DETAIL = "Email verification is temporarily unavailable. Please try again shortly."
RATE_LIMITED_DETAIL = "Too many requests. Try again later."
INVALID_DETAIL = "This verification link is not valid. Request a new one."
EXPIRED_DETAIL = "This verification link has expired. Request a new one."
USED_DETAIL = "This verification link has already been used."
VERIFIED_MESSAGE = "Your email address is verified. You can now sign in."
RESEND_MESSAGE = (
    "If an account with this email address is waiting for verification, a new link has been sent."
)
NOT_VERIFIED_DETAIL = (
    "Please verify your email address before signing in. Check your inbox for the link, or "
    "request a new one."
)
TOKEN_MIN, TOKEN_MAX = 32, 128  # token_urlsafe(32) is 43 characters
logger = logging.getLogger("app.email_verification")

Outcome = Literal["verified", "invalid", "expired", "used"]


def unavailable() -> ServiceUnavailable:
    return ServiceUnavailable(UNAVAILABLE_DETAIL, code="email_verification_unavailable")


def needs_verification(user: User) -> bool:
    """A customer with an email address that was never proven: no session until it is."""
    return not user.is_staff and user.email is not None and user.email_verified_at is None


def deliver_verification_email(
    mailer: VerificationMailer, recipient: str, name: str, token: str, key: str
) -> None:
    """Background task: send the link once. Never raises; logs no token, link, recipient or
    provider text. EMAIL_ALLOWED_RECIPIENTS applies as to every email."""
    if not email_allowed(recipient):
        logger.info("Verification email not sent: recipient not allowed (%s)", mailer.sender.name)
        return
    hours = get_settings().email_verification_ttl_hours
    rendered = email_templates.email_verification(
        name, email_templates.Link("Confirm my email", mailer.link(token)), hours
    )
    message = OutboundMessage(
        channel="email",
        recipient=recipient,
        subject=rendered.subject,
        text=rendered.text,
        idempotency_key=f"email-verification:{key}",
        html=rendered.html,
    )
    try:
        mailer.sender.send(message)
    except Exception as exc:
        logger.error(
            "Verification email not delivered (via %s): %s",
            mailer.sender.name,
            type(exc).__name__,
        )


class EmailVerificationService:
    @staticmethod
    def issue(db: Session, user: User, now: datetime) -> tuple[str, str]:
        """Stage a new token for the user's current address in the caller's transaction, revoking
        older open ones. Returns (raw token, row id); the raw token is only ever sent."""
        assert user.email is not None
        token = generate_verification_token()
        ttl = timedelta(hours=get_settings().email_verification_ttl_hours)
        EmailVerificationRepository.revoke_open(db, user.id, now)
        row = EmailVerificationRepository.create(
            db, user.id, user.email, hash_verification_token(token), now + ttl
        )
        return token, str(row.id)

    @staticmethod
    def schedule_delivery(
        background: BackgroundTasks,
        mailer: VerificationMailer,
        user: User,
        token: str,
        key: str,
    ) -> None:
        assert user.email is not None
        name = (user.full_name or "").split(" ")[0] or "there"
        background.add_task(deliver_verification_email, mailer, user.email, name, token, key)

    # ---- verify ------------------------------------------------------------------------------
    @staticmethod
    def _limit(limiter: LoginRateLimiter, ctx: RequestContext, db: Session, action: str) -> None:
        network = client_network(ctx.ip_address)
        try:
            decision = limiter.check(network, network)
        except RateLimitStoreUnavailable:
            raise ServiceUnavailable(LIMIT_STORE_DETAIL, code="login_unavailable") from None
        if not decision.allowed:
            AuditService.record_standalone(
                db,
                action=action,
                status="rate_limited",
                entity_type="client_network",
                entity_id=identifier_ref(network),
                context=ctx,
                details={"scope": decision.scope},
            )
            raise TooManyRequests(
                RATE_LIMITED_DETAIL,
                code="rate_limited",
                headers={"Retry-After": str(decision.retry_after)},
            )

    @staticmethod
    def verify(db: Session, token: str, ctx: RequestContext, limiter: LoginRateLimiter) -> User:
        EmailVerificationService._limit(limiter, ctx, db, "auth.email_verify")
        now = datetime.now(UTC)
        outcome: Outcome = "invalid"
        user: User | None = None
        well_formed = TOKEN_MIN <= len(token) <= TOKEN_MAX
        with atomic(db):
            row = (
                EmailVerificationRepository.lock_by_hash(db, hash_verification_token(token))
                if well_formed
                else None
            )
            if row is not None:
                user = db.get(User, row.user_id)
            if row is None or user is None or row.revoked_at is not None:
                outcome = "invalid"
            elif row.consumed_at is not None:
                outcome = "used"
            elif row.expires_at <= now:
                outcome = "expired"
            elif (user.email or "").lower() != row.email.lower():
                outcome = "invalid"  # the address changed since the link was sent
            else:
                UserRepository.lock_by_id(db, user.id)
                first = user.email_verified_at is None
                row.consumed_at = now
                if first:
                    user.email_verified_at = now
                EmailVerificationRepository.revoke_open(db, user.id, now, keep=row.id)
                AuditService.log_event(
                    db,
                    action="auth.email_verify",
                    status="success",
                    actor=user,
                    entity_type="user",
                    entity_id=user.id,
                    context=ctx,
                )
                if first:
                    # The welcome email waits for a proven address (owner decision 2026-11-12).
                    record_email_event(db, "welcome", user.id, user.email)
                outcome = "verified"
        if outcome == "verified":
            assert user is not None
            return user

        network = client_network(ctx.ip_address)
        try:
            limiter.record_failure(network, network)
        except RateLimitStoreUnavailable:
            raise ServiceUnavailable(LIMIT_STORE_DETAIL, code="login_unavailable") from None
        AuditService.record_standalone(
            db,
            action="auth.email_verify",
            status="failure",
            actor=user,
            entity_type="user" if user is not None else "client_network",
            entity_id=user.id if user is not None else identifier_ref(network),
            context=ctx,
            details={"reason": outcome},
        )
        detail, code = {
            "invalid": (INVALID_DETAIL, "verification_token_invalid"),
            "expired": (EXPIRED_DETAIL, "verification_token_expired"),
            "used": (USED_DETAIL, "verification_token_used"),
        }[outcome]
        raise ValidationFailed(detail, code=code)

    # ---- resend ------------------------------------------------------------------------------
    @staticmethod
    def resend(
        db: Session,
        email: str,
        ctx: RequestContext,
        limiter: LoginRateLimiter,
        mailer: VerificationMailer | None,
        background: BackgroundTasks,
    ) -> str:
        """Issue and send a new link when an unverified customer has this address and the
        cooldown has passed. The same reply in every case."""
        if mailer is None:
            raise unavailable()  # before any lookup: reveals nothing about accounts
        ref = identifier_ref(email)
        try:
            decision = limiter.check(ref, ctx.ip_address)
            if decision.allowed:
                limiter.record_failure(ref, ctx.ip_address)  # every request counts
        except RateLimitStoreUnavailable:
            raise ServiceUnavailable(LIMIT_STORE_DETAIL, code="login_unavailable") from None
        if not decision.allowed:
            AuditService.record_standalone(
                db,
                action="auth.email_verification_resend",
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

        now = datetime.now(UTC)
        user = UserRepository.get_by_email(db, email)
        reason: str | None = None
        if user is None:
            reason = "unknown_email"
        elif not needs_verification(user):
            reason = "staff_account" if user.is_staff else "already_verified"
        elif not user.is_active:
            reason = "account_inactive"
        else:
            cooldown = timedelta(seconds=get_settings().email_verification_resend_cooldown_seconds)
            last = EmailVerificationRepository.latest_issued_at(db, user.id)
            if last is not None and now - last < cooldown:
                reason = "cooldown"
        if reason is not None:
            AuditService.record_standalone(
                db,
                action="auth.email_verification_resend",
                status="ignored",
                entity_type="login_identifier",
                entity_id=ref,
                context=ctx,
                details={"reason": reason},
            )
            return RESEND_MESSAGE

        assert user is not None
        with atomic(db):
            UserRepository.lock_by_id(db, user.id)
            token, key = EmailVerificationService.issue(db, user, now)
            AuditService.log_event(
                db,
                action="auth.email_verification_resend",
                status="success",
                actor=user,
                entity_type="user",
                entity_id=user.id,
                context=ctx,
            )
        # Sent after the commit and after the response, so the reply time does not reveal
        # whether an account matched.
        EmailVerificationService.schedule_delivery(background, mailer, user, token, key)
        return RESEND_MESSAGE
