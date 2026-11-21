"""Continue with Google (ADR-006 amendment 2026-11-11).

The flow (Authorization Code with PKCE; the storefront's route handlers are the client side):

1. `start` creates a single-use flow: random `state`, `nonce`, PKCE code verifier and a
   browser-binding `flow_token`, each 256 bits or more from the OS CSPRNG. Only SHA-256 digests
   of the state, flow token and nonce are stored; the verifier is stored until the flow is used.
   The storefront keeps the flow token in a short-lived httpOnly cookie and sends the browser to
   Google.
2. `callback` receives Google's answer (state + code, or state + error) with the flow token from
   that cookie. The flow is consumed in its own committed transaction before Google is called, so
   a replayed, forged (login CSRF), expired or cross-browser callback is refused without a call to
   Google. Then the code is exchanged with the verifier and the ID token verified (signature,
   issuer, audience, expiry, nonce).
3. The verified Google account is matched by its subject (`sub`), never by email:
   - linked to a customer: that customer signs in;
   - not linked, and no account uses its (verified) email: a new **customer** is created and
     linked. Never staff: no role is ever derived from Google;
   - not linked, but an account already uses the email: refused with 409
     `google_account_exists`. Linking an existing account requires signing in to it first and
     using the link flow, so a Google account can never take over an account it has not proved
     it owns, and an account registered by someone else with your address cannot be joined to
     your Google sign-in;
   - linked to a staff account, or a staff account linking: refused. Staff sign in with their
     password (their accounts are provisioned by administrators, ADR-006).
4. The session is the existing database session (ADR-006): the same opaque bearer token, expiry
   and revocation as password login, so logout, logout-all, password reset and deactivation
   apply unchanged.

Every outcome is audited (auth.login / auth.register / auth.google_link with provider google,
or a failure with its reason). Tokens, codes, the verifier and the client secret are never logged
or audited; emails and Google subjects appear only as keyed pseudonyms.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import (
    Conflict,
    Forbidden,
    ServiceUnavailable,
    TooManyRequests,
    Unauthorized,
    ValidationFailed,
)
from app.core.identifiers import validate_email_format
from app.core.rate_limit import LoginRateLimiter, RateLimitStoreUnavailable, client_network
from app.core.request_context import RequestContext
from app.core.security import generate_session_token, hash_session_token
from app.db.transaction import atomic
from app.integrations.oauth.google import (
    GoogleCodeRejected,
    GoogleIdentity,
    GoogleOAuthClient,
    GoogleTokenInvalid,
    GoogleUnavailable,
)
from app.models.identity import OAuthIdentity, User
from app.models.session import OAuthLoginFlow, UserSession
from app.repositories.oauth_repository import OAuthRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import GoogleCallbackRequest
from app.services.audit_service import AuditService, identifier_ref
from app.services.auth_service import SESSION_LIFETIME
from app.services.notification_service import record_email_event

PROVIDER = "google"
FULL_NAME_MAX_LENGTH = 255

UNAVAILABLE_DETAIL = "Sign-in with Google is not available right now."
RATE_LIMITED_DETAIL = "Too many sign-in attempts. Try again later."
LIMIT_STORE_DETAIL = "Sign-in is temporarily unavailable. Please try again shortly."
STATE_DETAIL = "This sign-in link is invalid or has expired. Please try again."
CANCELLED_DETAIL = "Sign-in with Google was cancelled."
DENIED_DETAIL = "Google did not complete the sign-in. Please try again."
CODE_DETAIL = "Google could not confirm this sign-in. Please try again."
TOKEN_DETAIL = "Google's answer could not be verified. Please try again."
GOOGLE_DOWN_DETAIL = "Google could not be reached. Please try again shortly."
UNVERIFIED_DETAIL = "Your Google account's email address is not verified."
EMAIL_INVALID_DETAIL = "Your Google account's email address cannot be used here."
ACCOUNT_EXISTS_DETAIL = (
    "An account with this email address already exists. Sign in with your password, then "
    "connect Google from your profile."
)
STAFF_DETAIL = "Staff accounts sign in with their password."
INACTIVE_DETAIL = "Your account has been deactivated. Please contact support."
ALREADY_LINKED_DETAIL = "Your account is already connected to a Google account."
IN_USE_DETAIL = "This Google account is already connected to another account."


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _subject_ref(subject: str) -> str:
    return identifier_ref(f"google:{subject}")


class GoogleAuthService:
    # ---- shared steps ----------------------------------------------------------------------
    @staticmethod
    def _require(google: GoogleOAuthClient | None) -> GoogleOAuthClient:
        if google is None:
            raise ServiceUnavailable(UNAVAILABLE_DETAIL, code="google_auth_unavailable")
        return google

    @staticmethod
    def _check_limit(
        db: Session, limiter: LoginRateLimiter, ctx: RequestContext, step: str
    ) -> None:
        network = client_network(ctx.ip_address)
        try:
            decision = limiter.check(network, network)
        except RateLimitStoreUnavailable:
            raise ServiceUnavailable(LIMIT_STORE_DETAIL, code="login_unavailable") from None
        if not decision.allowed:
            AuditService.record_standalone(
                db,
                action="auth.google",
                status="rate_limited",
                entity_type="client_network",
                entity_id=identifier_ref(network),
                context=ctx,
                details={"step": step},
            )
            raise TooManyRequests(
                RATE_LIMITED_DETAIL,
                code="rate_limited",
                headers={"Retry-After": str(decision.retry_after)},
            )

    @staticmethod
    def _count(limiter: LoginRateLimiter, ctx: RequestContext) -> None:
        network = client_network(ctx.ip_address)
        try:
            limiter.record_failure(network, network)
        except RateLimitStoreUnavailable:
            raise ServiceUnavailable(LIMIT_STORE_DETAIL, code="login_unavailable") from None

    @staticmethod
    def _audit_failure(
        db: Session,
        ctx: RequestContext,
        reason: str,
        *,
        step: str,
        actor: User | None = None,
        entity_type: str = "oauth_flow",
        entity_id: str = "unknown",
    ) -> None:
        AuditService.record_standalone(
            db,
            action="auth.google",
            status="failure",
            actor=actor,
            entity_type=entity_type,
            entity_id=entity_id,
            context=ctx,
            details={"step": step, "reason": reason},
        )

    @staticmethod
    def _create_flow(
        db: Session,
        google: GoogleOAuthClient,
        purpose: str,
        user_id: uuid.UUID | None = None,
    ) -> tuple[str, str, datetime]:
        state = secrets.token_urlsafe(32)
        flow_token = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)  # 86 characters (RFC 7636: 43-128)
        expires_at = datetime.now(UTC) + timedelta(
            seconds=get_settings().google_oauth_flow_ttl_seconds
        )
        with atomic(db):
            OAuthRepository.create_flow(
                db,
                provider=PROVIDER,
                purpose=purpose,
                state_hash=_digest(state),
                flow_token_hash=_digest(flow_token),
                nonce_hash=_digest(nonce),
                code_verifier=verifier,
                expires_at=expires_at,
                user_id=user_id,
            )
        url = google.authorization_url(state=state, nonce=nonce, code_verifier=verifier)
        return url, flow_token, expires_at

    @staticmethod
    def _consume(
        db: Session,
        req: GoogleCallbackRequest,
        purpose: str,
        ctx: RequestContext,
        limiter: LoginRateLimiter,
        *,
        user: User | None = None,
    ) -> OAuthLoginFlow:
        """Use the flow once, committed before anything else happens. Every refusal looks the
        same to the caller (422 google_state_invalid); the audit record keeps the reason."""
        state_hash = _digest(req.state)
        with atomic(db):
            flow = OAuthRepository.consume_flow(
                db,
                provider=PROVIDER,
                state_hash=state_hash,
                flow_token_hash=_digest(req.flow_token),
            )
        if (
            flow is not None
            and flow.purpose == purpose
            and (user is None or flow.user_id == user.id)
        ):
            return flow

        if flow is not None:
            reason = "wrong_purpose" if flow.purpose != purpose else "wrong_user"
        else:
            stored = OAuthRepository.get_flow_by_state(db, PROVIDER, state_hash)
            db.rollback()  # end the read-only transaction before the audit commit
            if stored is None:
                reason = "unknown_state"
            elif stored.consumed_at is not None:
                reason = "replayed"
            elif stored.expires_at <= datetime.now(UTC):
                reason = "expired"
            else:
                reason = "flow_token_mismatch"
        GoogleAuthService._count(limiter, ctx)
        GoogleAuthService._audit_failure(
            db, ctx, reason, step="callback" if purpose == "login" else "link", actor=user
        )
        raise ValidationFailed(STATE_DETAIL, code="google_state_invalid")

    @staticmethod
    def _verified_identity(
        db: Session,
        google: GoogleOAuthClient,
        flow: OAuthLoginFlow,
        req: GoogleCallbackRequest,
        ctx: RequestContext,
        limiter: LoginRateLimiter,
        *,
        step: str,
        user: User | None = None,
    ) -> GoogleIdentity:
        if req.error is not None:
            cancelled = req.error == "access_denied"
            GoogleAuthService._audit_failure(
                db,
                ctx,
                "cancelled" if cancelled else "provider_error",
                step=step,
                actor=user,
                entity_id=str(flow.id),
            )
            if cancelled:
                raise ValidationFailed(CANCELLED_DETAIL, code="google_auth_cancelled")
            raise ValidationFailed(DENIED_DETAIL, code="google_auth_failed")

        assert req.code is not None and flow.code_verifier
        try:
            id_token = google.exchange_code(code=req.code, code_verifier=flow.code_verifier)
            identity = google.verify_id_token(id_token, nonce_hash=flow.nonce_hash)
        except GoogleUnavailable as exc:
            GoogleAuthService._audit_failure(
                db, ctx, f"google_unavailable:{exc}", step=step, actor=user, entity_id=str(flow.id)
            )
            raise ServiceUnavailable(GOOGLE_DOWN_DETAIL, code="google_unavailable") from None
        except GoogleCodeRejected:
            GoogleAuthService._count(limiter, ctx)
            GoogleAuthService._audit_failure(
                db, ctx, "code_rejected", step=step, actor=user, entity_id=str(flow.id)
            )
            raise Unauthorized(CODE_DETAIL, code="google_code_invalid") from None
        except GoogleTokenInvalid as exc:
            GoogleAuthService._count(limiter, ctx)
            GoogleAuthService._audit_failure(
                db,
                ctx,
                f"id_token_{exc.reason}",
                step=step,
                actor=user,
                entity_id=str(flow.id),
            )
            raise Unauthorized(TOKEN_DETAIL, code="google_token_invalid") from None

        if identity.email is None or not identity.email_verified:
            GoogleAuthService._audit_failure(
                db,
                ctx,
                "email_unverified",
                step=step,
                actor=user,
                entity_type="oauth_subject",
                entity_id=_subject_ref(identity.subject),
            )
            raise Forbidden(UNVERIFIED_DETAIL, code="google_email_unverified")
        try:
            # The same rules as registration, so the address is stored and looked up the same way.
            email = validate_email_format(identity.email)
        except ValueError:
            GoogleAuthService._audit_failure(
                db,
                ctx,
                "email_invalid",
                step=step,
                actor=user,
                entity_type="oauth_subject",
                entity_id=_subject_ref(identity.subject),
            )
            raise Forbidden(EMAIL_INVALID_DETAIL, code="google_email_invalid") from None
        return replace(identity, email=email)

    @staticmethod
    def _stage_session(db: Session, user: User, ctx: RequestContext) -> tuple[str, datetime]:
        raw_token = generate_session_token()
        expires_at = datetime.now(UTC) + SESSION_LIFETIME
        SessionRepository.create(
            db=db,
            user_id=user.id,
            token_hash=hash_session_token(raw_token),
            expires_at=expires_at,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
        )
        return raw_token, expires_at

    # ---- sign in ---------------------------------------------------------------------------
    @staticmethod
    def start(
        db: Session,
        google: GoogleOAuthClient | None,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
    ) -> tuple[str, str, datetime]:
        client = GoogleAuthService._require(google)
        GoogleAuthService._check_limit(db, limiter, ctx, "start")
        GoogleAuthService._count(limiter, ctx)  # every start counts: each one stores a row
        return GoogleAuthService._create_flow(db, client, "login")

    @staticmethod
    def callback(
        db: Session,
        google: GoogleOAuthClient | None,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
        req: GoogleCallbackRequest,
    ) -> tuple[User, str, datetime, bool]:
        """Returns (user, session token, expiry, account_created)."""
        client = GoogleAuthService._require(google)
        GoogleAuthService._check_limit(db, limiter, ctx, "callback")
        flow = GoogleAuthService._consume(db, req, "login", ctx, limiter)
        identity = GoogleAuthService._verified_identity(
            db, client, flow, req, ctx, limiter, step="callback"
        )
        return GoogleAuthService._sign_in(db, identity, ctx, retry=True)

    @staticmethod
    def _sign_in(
        db: Session, identity: GoogleIdentity, ctx: RequestContext, *, retry: bool
    ) -> tuple[User, str, datetime, bool]:
        assert identity.email is not None
        linked = OAuthRepository.get_identity(db, PROVIDER, identity.subject)
        if linked is not None:
            return (*GoogleAuthService._sign_in_linked(db, linked, identity, ctx), False)

        existing = UserRepository.get_by_email(db, identity.email)
        if existing is not None:
            # Never link by email: the owner must sign in and link (see the module docstring).
            # Staff and customer accounts get the same answer, so staff emails are not revealed.
            db.rollback()
            GoogleAuthService._audit_failure(
                db,
                ctx,
                "staff_email" if existing.is_staff else "email_registered",
                step="callback",
                entity_type="login_identifier",
                entity_id=identifier_ref(identity.email),
            )
            raise Conflict(ACCOUNT_EXISTS_DETAIL, code="google_account_exists")

        try:
            with atomic(db):
                # Continue with Google only ever creates customers (is_staff=false, no roles).
                user = UserRepository.create_customer(
                    db=db,
                    full_name=_full_name(identity),
                    password_hash=None,
                    email=identity.email,
                    # Proven by Google: the verified email claim is required above.
                    email_verified_at=datetime.now(UTC),
                )
                OAuthRepository.create_identity(
                    db, user.id, PROVIDER, identity.subject, identity.email
                )
                token, expires_at = GoogleAuthService._stage_session(db, user, ctx)
                AuditService.log_event(
                    db=db,
                    action="auth.register",
                    status="success",
                    actor=user,
                    entity_type="user",
                    entity_id=user.id,
                    context=ctx,
                    details={"provider": PROVIDER},
                )
                record_email_event(db, "welcome", user.id, user.email)
        except IntegrityError:
            # A concurrent callback for the same Google account or email won the race; answer
            # as if this one had arrived second.
            if not retry:
                raise
            return GoogleAuthService._sign_in(db, identity, ctx, retry=False)
        return user, token, expires_at, True

    @staticmethod
    def _sign_in_linked(
        db: Session, linked: OAuthIdentity, identity: GoogleIdentity, ctx: RequestContext
    ) -> tuple[User, str, datetime]:
        user = linked.user
        if user.is_staff or not user.is_active:
            reason = "staff_account" if user.is_staff else "account_inactive"
            db.rollback()
            AuditService.record_standalone(
                db,
                action="auth.login",
                status="failure",
                actor=user,
                entity_type="user",
                entity_id=user.id,
                context=ctx,
                details={"provider": PROVIDER, "reason": reason},
            )
            if user.is_staff:
                raise Forbidden(STAFF_DETAIL, code="google_staff_not_allowed")
            raise Forbidden(INACTIVE_DETAIL, code="account_inactive")
        with atomic(db):
            linked.last_login_at = datetime.now(UTC)
            linked.email = identity.email
            token, expires_at = GoogleAuthService._stage_session(db, user, ctx)
            AuditService.log_event(
                db=db,
                action="auth.login",
                status="success",
                actor=user,
                entity_type="user",
                entity_id=user.id,
                context=ctx,
                details={"provider": PROVIDER},
            )
        return user, token, expires_at

    # ---- link to a signed-in account -------------------------------------------------------
    @staticmethod
    def _check_can_link(db: Session, user: User, ctx: RequestContext) -> None:
        if user.is_staff:
            GoogleAuthService._audit_failure(
                db,
                ctx,
                "staff_account",
                step="link",
                actor=user,
                entity_type="user",
                entity_id=str(user.id),
            )
            raise Forbidden(STAFF_DETAIL, code="google_staff_not_allowed")
        if OAuthRepository.get_user_identity(db, user.id, PROVIDER) is not None:
            db.rollback()
            raise Conflict(ALREADY_LINKED_DETAIL, code="google_already_linked")

    @staticmethod
    def link_start(
        db: Session,
        google: GoogleOAuthClient | None,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
        user: User,
    ) -> tuple[str, str, datetime]:
        client = GoogleAuthService._require(google)
        GoogleAuthService._check_can_link(db, user, ctx)
        GoogleAuthService._check_limit(db, limiter, ctx, "link_start")
        GoogleAuthService._count(limiter, ctx)
        return GoogleAuthService._create_flow(db, client, "link", user_id=user.id)

    @staticmethod
    def link_callback(
        db: Session,
        google: GoogleOAuthClient | None,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
        req: GoogleCallbackRequest,
        session: UserSession,
    ) -> OAuthIdentity:
        client = GoogleAuthService._require(google)
        user = session.user
        GoogleAuthService._check_limit(db, limiter, ctx, "link_callback")
        flow = GoogleAuthService._consume(db, req, "link", ctx, limiter, user=user)
        GoogleAuthService._check_can_link(db, user, ctx)
        identity = GoogleAuthService._verified_identity(
            db, client, flow, req, ctx, limiter, step="link", user=user
        )
        owner = OAuthRepository.get_identity(db, PROVIDER, identity.subject)
        if owner is not None:
            db.rollback()
            GoogleAuthService._audit_failure(
                db,
                ctx,
                "subject_linked_elsewhere" if owner.user_id != user.id else "already_linked",
                step="link",
                actor=user,
                entity_type="oauth_subject",
                entity_id=_subject_ref(identity.subject),
            )
            if owner.user_id == user.id:
                raise Conflict(ALREADY_LINKED_DETAIL, code="google_already_linked")
            raise Conflict(IN_USE_DETAIL, code="google_account_in_use")
        try:
            with atomic(db):
                linked = OAuthRepository.create_identity(
                    db, user.id, PROVIDER, identity.subject, identity.email
                )
                AuditService.log_event(
                    db=db,
                    action="auth.google_link",
                    status="success",
                    actor=user,
                    entity_type="user",
                    entity_id=user.id,
                    context=ctx,
                    details={"provider": PROVIDER},
                )
        except IntegrityError:
            # A concurrent link of this user or of this Google account committed first.
            if OAuthRepository.get_user_identity(db, user.id, PROVIDER) is not None:
                raise Conflict(ALREADY_LINKED_DETAIL, code="google_already_linked") from None
            raise Conflict(IN_USE_DETAIL, code="google_account_in_use") from None
        return linked


def _full_name(identity: GoogleIdentity) -> str:
    """Google's display name, cleaned like a typed one: no control characters, single spaces,
    2-255 characters; else the email's local part. It is only shown, never trusted."""
    assert identity.email is not None
    name = " ".join("".join(c for c in (identity.name or "") if c.isprintable()).split())
    if len(name) < 2:
        name = identity.email.split("@", 1)[0]
    return name[:FULL_NAME_MAX_LENGTH]
