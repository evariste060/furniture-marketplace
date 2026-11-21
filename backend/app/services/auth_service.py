from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import (
    Conflict,
    Forbidden,
    ServiceUnavailable,
    TooManyRequests,
    Unauthorized,
    ValidationFailed,
)
from app.core.rate_limit import LoginRateLimiter, RateLimitStoreUnavailable
from app.core.request_context import RequestContext
from app.core.security import (
    burn_password_check,
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.db.transaction import atomic
from app.integrations.notifications.verification import VerificationMailer
from app.models.identity import User
from app.models.session import UserSession
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.audit_service import AuditService, identifier_ref
from app.services.email_verification_service import (
    NOT_VERIFIED_DETAIL,
    EmailVerificationService,
    needs_verification,
)
from app.services.email_verification_service import unavailable as verification_unavailable
from app.services.notification_service import record_email_event

SESSION_LIFETIME = timedelta(days=7)

DUPLICATE_EMAIL_DETAIL = "A customer account with this email already exists."
DUPLICATE_PHONE_DETAIL = "A customer account with this phone number already exists."
INVALID_CREDENTIALS_DETAIL = "Invalid email/phone or password."
RATE_LIMITED_DETAIL = "Too many failed login attempts. Try again later."
RATE_LIMIT_UNAVAILABLE_DETAIL = "Login is temporarily unavailable. Please try again shortly."
CURRENT_PASSWORD_DETAIL = "The current password is not correct."
STAFF_PASSWORD_DETAIL = "Staff passwords are managed by an administrator."


def duplicate_field_from_integrity_error(exc: IntegrityError) -> str | None:
    """Map a uniqueness violation to 'email' or 'phone' without exposing database internals."""
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    name = (getattr(diag, "constraint_name", None) or str(exc.orig)).lower()
    if "email" in name:
        return "email"
    if "phone" in name:
        return "phone"
    return None


@dataclass(frozen=True)
class Registration:
    user: User
    # The session, for phone-only registration; None while an email is waiting for verification.
    session_token: str | None
    expires_at: datetime | None
    # (raw token, row id) of the verification link to send after the commit, or None.
    verification: tuple[str, str] | None


class AuthService:
    @staticmethod
    def _duplicate(db: Session, field: str, req: RegisterRequest, ctx: RequestContext) -> None:
        value = req.email if field == "email" else req.phone
        AuditService.record_standalone(
            db,
            action="auth.register",
            status="failure",
            entity_type="login_identifier",
            entity_id=identifier_ref(value) if value else "unknown",
            context=ctx,
            details={"reason": f"duplicate_{field}"},
        )
        raise Conflict(
            DUPLICATE_EMAIL_DETAIL if field == "email" else DUPLICATE_PHONE_DETAIL,
            code="email_taken" if field == "email" else "phone_taken",
        )

    @staticmethod
    def register_customer(
        db: Session,
        req: RegisterRequest,
        ctx: RequestContext,
        mailer: VerificationMailer | None = None,
    ) -> "Registration":
        """Create a customer. With an email address the account starts unverified: no session,
        and a verification link is staged for sending after the commit (ADR-006 amendment
        2026-11-12). Phone-only registration signs in at once, as before."""
        if req.email and mailer is None:
            # No link could reach the address: create nothing rather than an account that can
            # never be verified.
            raise verification_unavailable()
        # Fast-path checks give a clear 409; the unique indexes remain the source of truth.
        if req.email and UserRepository.get_by_email(db, req.email):
            AuthService._duplicate(db, "email", req, ctx)
        if req.phone and UserRepository.get_by_phone(db, req.phone):
            AuthService._duplicate(db, "phone", req, ctx)

        now = datetime.now(UTC)
        raw_token: str | None = None
        expires_at: datetime | None = None
        verification: tuple[str, str] | None = None
        try:
            with atomic(db):
                # Public registration only ever creates customers (is_staff=false, no roles).
                user = UserRepository.create_customer(
                    db=db,
                    full_name=req.full_name,
                    password_hash=hash_password(req.password),
                    email=req.email,
                    phone=req.phone,
                )
                if user.email:
                    verification = EmailVerificationService.issue(db, user, now)
                else:
                    raw_token = generate_session_token()
                    expires_at = now + SESSION_LIFETIME
                    SessionRepository.create(
                        db=db,
                        user_id=user.id,
                        token_hash=hash_session_token(raw_token),
                        expires_at=expires_at,
                        ip_address=ctx.ip_address,
                        user_agent=ctx.user_agent,
                    )
                AuditService.log_event(
                    db=db,
                    action="auth.register",
                    status="success",
                    actor=user,
                    entity_type="user",
                    entity_id=user.id,
                    context=ctx,
                    details={"verification_required": verification is not None},
                )
                if verification is None:
                    # Email accounts get their welcome email once verified.
                    record_email_event(db, "welcome", user.id, user.email)
        except IntegrityError as exc:
            # A concurrent request registered the same identifier between check and insert.
            field = duplicate_field_from_integrity_error(exc)
            if field is None:
                raise
            AuthService._duplicate(db, field, req, ctx)

        return Registration(user, raw_token, expires_at, verification)

    @staticmethod
    def login_user(
        db: Session, req: LoginRequest, ctx: RequestContext, limiter: LoginRateLimiter
    ) -> tuple[User, str, datetime]:
        identifier = req.identifier  # already normalised by LoginRequest
        ref = identifier_ref(identifier)

        try:
            decision = limiter.check(ref, ctx.ip_address)
        except RateLimitStoreUnavailable:
            # Fail closed: never silently disable brute-force protection.
            raise ServiceUnavailable(
                RATE_LIMIT_UNAVAILABLE_DETAIL, code="login_unavailable"
            ) from None
        if not decision.allowed:
            AuditService.record_standalone(
                db,
                action="auth.login",
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

        user = UserRepository.get_by_identifier(db, identifier)
        if user is None or user.password_hash is None:
            burn_password_check(req.password)  # same work as a real check: no timing oracle
            password_ok = False
        else:
            password_ok = verify_password(req.password, user.password_hash)

        if not password_ok:
            try:
                limiter.record_failure(ref, ctx.ip_address)
            except RateLimitStoreUnavailable:
                raise ServiceUnavailable(
                    RATE_LIMIT_UNAVAILABLE_DETAIL, code="login_unavailable"
                ) from None
            AuditService.record_standalone(
                db,
                action="auth.login",
                status="failure",
                entity_type="login_identifier",
                entity_id=ref,
                context=ctx,
                details={"reason": "invalid_credentials"},
            )
            raise Unauthorized(INVALID_CREDENTIALS_DETAIL, code="invalid_credentials")

        # The failed-credentials branch above exits when no password-bearing user was found.
        assert user is not None
        if not user.is_active:
            AuditService.record_standalone(
                db,
                action="auth.login",
                status="failure",
                actor=user,
                entity_type="user",
                entity_id=user.id,
                context=ctx,
                details={"reason": "account_inactive"},
            )
            raise Forbidden(
                "Your account has been deactivated. Please contact support.",
                code="account_inactive",
            )

        if needs_verification(user):
            # Checked after the password, so only someone who knows it learns the account's
            # state. Not a failed attempt: the lockout counters are left alone.
            AuditService.record_standalone(
                db,
                action="auth.login",
                status="failure",
                actor=user,
                entity_type="user",
                entity_id=user.id,
                context=ctx,
                details={"reason": "email_not_verified"},
            )
            raise Forbidden(NOT_VERIFIED_DETAIL, code="email_not_verified")

        raw_token = generate_session_token()
        expires_at = datetime.now(UTC) + SESSION_LIFETIME
        with atomic(db):
            SessionRepository.create(
                db=db,
                user_id=user.id,
                token_hash=hash_session_token(raw_token),
                expires_at=expires_at,
                ip_address=ctx.ip_address,
                user_agent=ctx.user_agent,
            )
            AuditService.log_event(
                db=db,
                action="auth.login",
                status="success",
                actor=user,
                entity_type="user",
                entity_id=user.id,
                context=ctx,
            )
        try:
            limiter.record_success(ref)
        except RateLimitStoreUnavailable:
            pass  # login already succeeded; the counter simply expires with its window

        return user, raw_token, expires_at

    @staticmethod
    def logout(db: Session, session: UserSession, ctx: RequestContext) -> None:
        with atomic(db):
            SessionRepository.revoke(db, session)
            AuditService.log_event(
                db=db,
                action="auth.logout",
                status="success",
                actor=session.user,
                entity_type="session",
                entity_id=session.id,
                context=ctx,
            )

    @staticmethod
    def change_password(
        db: Session,
        session: UserSession,
        current_password: str,
        new_password: str,
        ctx: RequestContext,
        limiter: LoginRateLimiter,
    ) -> int:
        """A signed-in customer changes their password (approved 2026-10-28). A wrong current
        password counts as a failed login for the account's identifier, so it shares the login
        lockout. Every other session of the account is revoked; this one stays. Staff passwords
        are managed by administrators (ADR-006), so staff get 403."""
        user = session.user
        if user.is_staff:
            raise Forbidden(STAFF_PASSWORD_DETAIL, code="staff_password_managed")
        ref = identifier_ref(user.email or user.phone or str(user.id))
        try:
            decision = limiter.check(ref, ctx.ip_address)
        except RateLimitStoreUnavailable:
            raise ServiceUnavailable(
                RATE_LIMIT_UNAVAILABLE_DETAIL, code="login_unavailable"
            ) from None
        if not decision.allowed:
            raise TooManyRequests(
                RATE_LIMITED_DETAIL,
                code="rate_limited",
                headers={"Retry-After": str(decision.retry_after)},
            )
        if user.password_hash is None or not verify_password(current_password, user.password_hash):
            try:
                limiter.record_failure(ref, ctx.ip_address)
            except RateLimitStoreUnavailable:
                raise ServiceUnavailable(
                    RATE_LIMIT_UNAVAILABLE_DETAIL, code="login_unavailable"
                ) from None
            AuditService.record_standalone(
                db,
                action="auth.password_change",
                status="failure",
                actor=user,
                entity_type="user",
                entity_id=user.id,
                context=ctx,
                details={"reason": "current_password_invalid"},
            )
            raise ValidationFailed(
                CURRENT_PASSWORD_DETAIL,
                code="current_password_invalid",
                details=[
                    {
                        "type": "value_error",
                        "loc": ["body", "current_password"],
                        "msg": CURRENT_PASSWORD_DETAIL,
                    }
                ],
            )
        with atomic(db):
            user.password_hash = hash_password(new_password)
            revoked = SessionRepository.revoke_all_user_sessions(db, user.id, keep=session.id)
            AuditService.log_event(
                db=db,
                action="auth.password_change",
                status="success",
                actor=user,
                entity_type="user",
                entity_id=user.id,
                context=ctx,
                details={"sessions_revoked": revoked},
            )
        try:
            limiter.record_success(ref)
        except RateLimitStoreUnavailable:
            pass  # the change succeeded; the counter simply expires with its window
        return revoked

    @staticmethod
    def logout_everywhere(db: Session, session: UserSession, ctx: RequestContext) -> int:
        """Revoke every session of the user, this one included (approved 2026-10-28)."""
        user = session.user
        with atomic(db):
            revoked = SessionRepository.revoke_all_user_sessions(db, user.id)
            AuditService.log_event(
                db=db,
                action="auth.logout_all",
                status="success",
                actor=user,
                entity_type="user",
                entity_id=user.id,
                context=ctx,
                details={"sessions_revoked": revoked},
            )
        return revoked
