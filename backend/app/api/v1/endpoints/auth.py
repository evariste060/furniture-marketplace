from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.notifier import Notifier
from app.api.v1.responses import (
    AUTHENTICATED,
    ERR,
    UNAUTHORIZED_401,
    VALIDATION_422,
    ResponseMap,
)
from app.core.dependencies import get_current_session, get_current_user
from app.core.rate_limit import (
    LoginRateLimiter,
    get_email_verify_rate_limiter,
    get_login_rate_limiter,
    get_password_reset_rate_limiter,
    get_reset_code_rate_limiter,
    get_verification_resend_rate_limiter,
)
from app.core.request_context import RequestContext, get_request_context
from app.db.session import get_db
from app.integrations.notifications import NotificationProvider, get_message_sender
from app.integrations.notifications.verification import (
    VerificationMailer,
    get_verification_mailer,
)
from app.models.identity import User
from app.models.session import UserSession
from app.repositories.oauth_repository import OAuthRepository
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    MessageResponse,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    UserResponse,
    VerifyEmailRequest,
)
from app.services.auth_service import AuthService
from app.services.email_verification_service import VERIFIED_MESSAGE, EmailVerificationService
from app.services.password_reset_service import PasswordResetService

router = APIRouter(prefix="/auth", tags=["Authentication"])


Mailer = Annotated[VerificationMailer | None, Depends(get_verification_mailer)]


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new retail customer account",
    description=(
        "Registers a **customer** using an email address and/or a Rwandan mobile number "
        "(+2507XXXXXXXX, 2507XXXXXXXX or 07XXXXXXXX; stored as +2507XXXXXXXX). Any role or "
        "status fields in the body are ignored: public registration only creates customers.\n\n"
        "- **With an email address** (ADR-006 amendment 2026-11-12): the account is created "
        "unverified and a verification link, valid for EMAIL_VERIFICATION_TTL_HOURS (24 by "
        "default), is emailed. No session is returned (`verification_required: true`; "
        "`session_token`, `token_type` and `expires_at` are null); the customer signs in after "
        "verifying. 503 `email_verification_unavailable` when no email can be delivered.\n"
        "- **Phone only:** returns a session token valid for 7 days, as before "
        "(`verification_required: false`)."
    ),
    responses={
        409: {**ERR, "description": "Email or phone number already in use"},
        503: {
            **ERR,
            "description": "email_verification_unavailable: no email provider or SITE_URL",
        },
        **VALIDATION_422,
    },
)
def register(
    req: RegisterRequest,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    db: Annotated[Session, Depends(get_db)],
    background: BackgroundTasks,
    notifier: Notifier,
    mailer: Mailer,
) -> RegisterResponse:
    done = AuthService.register_customer(db=db, req=req, ctx=ctx, mailer=mailer)
    if done.verification is not None:
        assert mailer is not None  # register_customer refuses an email without a mailer
        token, key = done.verification
        EmailVerificationService.schedule_delivery(background, mailer, done.user, token, key)
    notifier.schedule(background, db)  # the welcome email (phone-only registration)
    return RegisterResponse(
        user=UserResponse.from_user(done.user),
        session_token=done.session_token,
        token_type="bearer" if done.session_token else None,
        expires_at=done.expires_at,
        verification_required=done.verification is not None,
    )


@router.post(
    "/email/verify",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify an email address",
    description=(
        "Uses the token from the verification link once and marks the account's email address "
        "verified (ADR-006 amendment 2026-11-12). It does not sign in: the customer then signs "
        "in with their password. A token is refused when unknown or superseded by a newer link "
        "(`verification_token_invalid`), expired (`verification_token_expired`) or already "
        "used (`verification_token_used`); concurrent uses of one token succeed once.\n\n"
        "**Rate limit:** failed attempts count per client network (429 with Retry-After)."
    ),
    responses={
        422: {
            **ERR,
            "description": (
                "Invalid request, verification_token_invalid, verification_token_expired or "
                "verification_token_used"
            ),
        },
        429: {
            **ERR,
            "description": "Too many failed attempts; see Retry-After (seconds)",
            "headers": {"Retry-After": {"schema": {"type": "integer"}}},
        },
        503: {**ERR, "description": "login_unavailable: rate-limit store unavailable"},
    },
)
def verify_email(
    req: VerifyEmailRequest,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    db: Annotated[Session, Depends(get_db)],
    limiter: Annotated[LoginRateLimiter, Depends(get_email_verify_rate_limiter)],
    background: BackgroundTasks,
    notifier: Notifier,
) -> MessageResponse:
    EmailVerificationService.verify(db, req.token, ctx, limiter)
    notifier.schedule(background, db)  # the welcome email, now that the address is proven
    return MessageResponse(message=VERIFIED_MESSAGE)


@router.post(
    "/email/verification/resend",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a new email verification link",
    description=(
        "Sends a new verification link if the address belongs to a customer who has not "
        "verified it yet, at most once per EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS (60); the "
        "new link replaces older ones. The reply is always the same, whether or not such an "
        "account exists (no account enumeration).\n\n"
        "**Rate limit:** EMAIL_VERIFICATION_RESEND_MAX_PER_EMAIL (5) per address and "
        "EMAIL_VERIFICATION_RESEND_MAX_PER_IP (20) per IP per hour; every request counts (429 "
        "with Retry-After). 503 `email_verification_unavailable` when no email can be delivered."
    ),
    responses={
        429: {
            **ERR,
            "description": "Too many requests; see Retry-After (seconds)",
            "headers": {"Retry-After": {"schema": {"type": "integer"}}},
        },
        503: {
            **ERR,
            "description": (
                "email_verification_unavailable (no email provider or SITE_URL), or "
                "login_unavailable (rate-limit store unavailable)"
            ),
        },
        **VALIDATION_422,
    },
)
def resend_verification(
    req: ResendVerificationRequest,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    db: Annotated[Session, Depends(get_db)],
    limiter: Annotated[LoginRateLimiter, Depends(get_verification_resend_rate_limiter)],
    mailer: Mailer,
    background: BackgroundTasks,
) -> MessageResponse:
    message = EmailVerificationService.resend(db, req.email, ctx, limiter, mailer, background)
    return MessageResponse(message=message)


@router.post(
    "/login",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate customer or staff member",
    description=(
        "Validates credentials and issues a database-backed session token (7 days). The "
        "identifier is an email or a Rwandan mobile number in any approved format.\n\n"
        "**Rate limit:** after 5 failed attempts for one identifier, or 20 from one IP, within "
        "15 minutes, further attempts return 429 with `Retry-After` until the window ends. "
        "Unknown and known identifiers are treated identically."
    ),
    responses={
        401: {**ERR, "description": "Invalid credentials"},
        403: {
            **ERR,
            "description": (
                "account_inactive, or email_not_verified (a customer who registered with an "
                "email has not verified it; checked only after a correct password)"
            ),
        },
        429: {
            **ERR,
            "description": "Too many failed attempts; see Retry-After (seconds)",
            "headers": {"Retry-After": {"schema": {"type": "integer"}}},
        },
        503: {**ERR, "description": "Rate-limit store unavailable; login refused (fail closed)"},
        **VALIDATION_422,
    },
)
def login(
    req: LoginRequest,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    db: Annotated[Session, Depends(get_db)],
    limiter: Annotated[LoginRateLimiter, Depends(get_login_rate_limiter)],
) -> AuthResponse:
    user, token, expires_at = AuthService.login_user(db=db, req=req, ctx=ctx, limiter=limiter)
    return AuthResponse(
        user=UserResponse.from_user(user),
        session_token=token,
        token_type="bearer",
        expires_at=expires_at,
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Log out and invalidate current session",
    description="Revokes the presented session token in PostgreSQL; it cannot be used again.",
    responses={**UNAUTHORIZED_401},
)
def logout(
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    session: Annotated[UserSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    AuthService.logout(db=db, session=session, ctx=ctx)
    return MessageResponse(message="Successfully logged out and session revoked.")


@router.post(
    "/logout-all",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Log out on all devices",
    description=(
        "Revokes every session of the signed-in user, this one included (approved by the "
        "project owner 2026-10-28). Audited as auth.logout_all."
    ),
    responses={**UNAUTHORIZED_401},
)
def logout_all(
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    session: Annotated[UserSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    AuthService.logout_everywhere(db=db, session=session, ctx=ctx)
    return MessageResponse(message="Logged out on all devices.")


@router.post(
    "/change-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Change the password (customers)",
    description=(
        "A signed-in customer gives the current password and a new one (at least 8 characters "
        "with upper- and lower-case letters and a digit or symbol). Every other session of the "
        "account is revoked; this one stays. A wrong current password returns 422 "
        "`current_password_invalid` and counts as a failed login for the account, so the login "
        "limits apply (429 with Retry-After). Staff passwords are managed by administrators "
        "(403 `staff_password_managed`). Approved by the project owner 2026-10-28."
    ),
    responses={
        **UNAUTHORIZED_401,
        403: {**ERR, "description": "staff_password_managed, or account_inactive"},
        422: {**ERR, "description": "Invalid request, weak password, or current_password_invalid"},
        429: {
            **ERR,
            "description": "Too many failed attempts; see Retry-After (seconds)",
            "headers": {"Retry-After": {"schema": {"type": "integer"}}},
        },
        503: {**ERR, "description": "Rate-limit store unavailable (fail closed)"},
    },
)
def change_password(
    req: ChangePasswordRequest,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    session: Annotated[UserSession, Depends(get_current_session)],
    _: Annotated[User, Depends(get_current_user)],  # active accounts only (403 otherwise)
    db: Annotated[Session, Depends(get_db)],
    limiter: Annotated[LoginRateLimiter, Depends(get_login_rate_limiter)],
) -> MessageResponse:
    AuthService.change_password(
        db, session, req.current_password, req.new_password, ctx=ctx, limiter=limiter
    )
    return MessageResponse(message="Password changed.")


@router.get(
    "/me",
    response_model=MeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current authenticated user",
    description=(
        "Returns the identity of the currently authenticated user, with `google_linked` and "
        "`has_password` (how the account can sign in; ADR-006 amendment 2026-11-11)."
    ),
    responses={**AUTHENTICATED},
)
def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MeResponse:
    linked = OAuthRepository.get_user_identity(db, current_user.id, "google") is not None
    return MeResponse(
        **UserResponse.from_user(current_user).model_dump(),
        google_linked=linked,
        has_password=current_user.password_hash is not None,
    )


RESET_ERRORS: ResponseMap = {
    429: {
        **ERR,
        "description": "Too many requests or failed attempts; see Retry-After (seconds)",
        "headers": {"Retry-After": {"schema": {"type": "integer"}}},
    },
    503: {
        **ERR,
        "description": "Password reset unavailable (no message provider, or rate-limit store "
        "down); code password_reset_unavailable",
    },
}
ResetLimiter = Annotated[LoginRateLimiter, Depends(get_password_reset_rate_limiter)]
ResetCodeLimiter = Annotated[LoginRateLimiter, Depends(get_reset_code_rate_limiter)]
Sender = Annotated[NotificationProvider | None, Depends(get_message_sender)]


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset code",
    description=(
        "Sends a 6-digit code, valid for 15 minutes, to the email address or Rwandan mobile "
        "number given, if it belongs to an active **customer** account (staff passwords are "
        "managed by administrators). The reply is always the same, whether or not an account "
        "matches. Requesting a new code invalidates older ones.\n\n"
        "**Rate limit:** 5 requests per identifier and 20 per IP within 15 minutes."
    ),
    responses={**RESET_ERRORS, **VALIDATION_422},
)
def forgot_password(
    req: ForgotPasswordRequest,
    background: BackgroundTasks,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    db: Annotated[Session, Depends(get_db)],
    limiter: ResetLimiter,
    sender: Sender,
) -> MessageResponse:
    message = PasswordResetService.request_code(
        db, req.identifier, ctx, limiter, sender, background
    )
    return MessageResponse(message=message)


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset the password with a code",
    description=(
        "Sets a new password when the code matches the newest code sent to this identifier, "
        "is under 15 minutes old and has had fewer than 5 attempts. Every session of the account "
        "is revoked, so the user logs in again. A wrong, expired or used code returns 422 "
        "`reset_code_invalid` without saying which."
    ),
    responses={
        422: {**ERR, "description": "Invalid request, weak password, or reset_code_invalid"},
        **RESET_ERRORS,
    },
)
def reset_password(
    req: ResetPasswordRequest,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    db: Annotated[Session, Depends(get_db)],
    limiter: ResetCodeLimiter,
    sender: Sender,
) -> MessageResponse:
    message = PasswordResetService.reset_password(db, req, ctx, limiter, sender)
    return MessageResponse(message=message)
